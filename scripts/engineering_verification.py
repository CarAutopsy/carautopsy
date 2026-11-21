"""Offline verification runner and evidence artifact for the engineering agent.

This module is the deterministic verification seam of the owner-gated
engineering-agent design (issue #114 Phase 2, implementation step 3). It runs a
fixed registry of repository checks against a trusted checkout, re-hashes the
task snapshot after every check, and emits a stable, read-only evidence
artifact. It performs no provider call, no source request, no PR creation and
no activation.

Runtime isolation is deliberately *not* claimed here: scrubbing the environment
and using an allow-listed command registry reduce egress, but only a real
sandbox can demonstrate isolation. The artifact records that fact explicitly so
a later controller cannot mistake this primitive for end-to-end proof.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from engineering_task import (
    TaskContractError,
    snapshot_digest,
    snapshot_manifest,
    validate_task_contract,
)


class VerificationError(ValueError):
    """Raised when verification inputs or execution violate the offline contract."""


MAX_OUTPUT_BYTES = 256 * 1024
MAX_CHECK_SECONDS = 900
MAX_CHECKS = 10
MAX_EXCERPT_CHARS = 2_000
TIMEOUT_EXIT_CODE = 124
EXECUTION_ERROR_EXIT_CODE = 126
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")

# Trusted, fixed registry. Untrusted task text can never add or alter a command.
# The "python" sentinel is resolved to sys.executable only at execution time;
# the evidence artifact records the stable, relative declaration.
CHECK_REGISTRY: dict[str, tuple[str, ...]] = {
    "compile_sources": ("python", "-m", "compileall", "-q", "scripts", "tests"),
    "unit_tests": ("python", "-m", "unittest", "discover", "-s", "tests", "-v"),
    "catalog_validation": ("python", "scripts/validate_catalog.py"),
    "repo_audit": ("python", "scripts/repo_audit.py"),
    "python_probe": ("python", "--version"),
}
DEFAULT_CHECKS = (
    "compile_sources",
    "unit_tests",
    "catalog_validation",
    "repo_audit",
)

_SAFE_ENV_NAMES = ("PATH", "SystemRoot", "TEMP", "TMP")
_SECRET_ENV_MARKERS = (
    "key", "token", "secret", "password", "passwd", "credential", "cookie",
    "auth", "gh_", "github_", "openai", "gemini", "deepseek", "qwen", "proxy",
)
_SECRET_CONTENT_PATTERN = re.compile(r"ghp_|github_pat_|\bsk-|\bAKIA[0-9A-Z]{16}\b")


class _Completed:
    """Minimal process result shared by the real and injected runners."""

    def __init__(
        self,
        returncode: int,
        stdout: Any = b"",
        stderr: Any = b"",
        *,
        timed_out: bool = False,
        execution_error: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.execution_error = execution_error


def _default_runner(argv: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> _Completed:
    """Run an allow-listed argv with no shell, scrubbed env and a hard timeout."""
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _Completed(
            TIMEOUT_EXIT_CODE,
            exc.stdout or b"",
            exc.stderr or b"",
            timed_out=True,
        )
    except OSError:
        return _Completed(EXECUTION_ERROR_EXIT_CODE, b"", b"", execution_error=True)
    return _Completed(completed.returncode, completed.stdout, completed.stderr)


def assert_offline_command_registry() -> None:
    """Fail closed if a registered command could reach a shell or the network."""
    forbidden = {
        "sh", "bash", "cmd", "cmd.exe", "powershell", "curl", "wget", "ssh",
        "nc", "pip", "pip3", "gh", "requests", "http://", "https://", "-c",
    }
    for name, argv in CHECK_REGISTRY.items():
        if not isinstance(name, str) or not name or not argv or argv[0] != "python":
            raise VerificationError(f"invalid command registry entry: {name}")
        for part in argv:
            if not isinstance(part, str) or part.casefold() in forbidden:
                raise VerificationError(f"command registry entry is not offline: {name}")


def validate_check_names(names: Any) -> tuple[str, ...]:
    """Accept only known, unique check names supplied by a trusted controller."""
    if isinstance(names, str) or not isinstance(names, (list, tuple)):
        raise VerificationError("check names must be a list")
    if not names or len(names) > MAX_CHECKS:
        raise VerificationError("check names must be a bounded non-empty list")
    selected: list[str] = []
    for name in names:
        if not isinstance(name, str) or name not in CHECK_REGISTRY:
            raise VerificationError(f"unknown verification check: {name!r}")
        if name in selected:
            raise VerificationError(f"duplicate verification check: {name}")
        selected.append(name)
    return tuple(selected)


def scrub_environment(source: Any = None) -> dict[str, str]:
    """Build a minimal environment; credentials are never passed to a check."""
    values = os.environ if source is None else source
    environment: dict[str, str] = {}
    for name in _SAFE_ENV_NAMES:
        value = values.get(name)
        if isinstance(value, str) and value:
            environment[name] = value
    environment.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
    })
    for name in list(environment):
        if any(marker in name.casefold() for marker in _SECRET_ENV_MARKERS):
            environment.pop(name, None)
    return environment


def redact_output(text: str) -> str:
    """Replace secret-shaped lines before any output leaves the runner."""
    lines = []
    for line in text.splitlines():
        folded = line.casefold()
        if _SECRET_CONTENT_PATTERN.search(line) or any(
            marker in folded for marker in _SECRET_ENV_MARKERS
        ):
            lines.append("[REDACTED]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _bounded_text(data: Any) -> tuple[str, bool, str]:
    """Return bounded text, a truncation flag and a digest of the bounded bytes."""
    if data is None:
        raw = b""
    elif isinstance(data, bytes):
        raw = data
    elif isinstance(data, bytearray):
        raw = bytes(data)
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raise VerificationError("runner output must be bytes or text")
    bounded = raw[:MAX_OUTPUT_BYTES]
    return (
        bounded.decode("utf-8", errors="replace"),
        len(raw) > MAX_OUTPUT_BYTES,
        hashlib.sha256(bounded).hexdigest(),
    )


def parse_test_counts(text: str) -> dict[str, Any]:
    """Extract deterministic test counts from unittest output without trusting it."""
    run = re.search(r"Ran\s+(\d+)\s+test", text)
    counts: dict[str, Any] = {
        "tests_run": int(run.group(1)) if run else None,
        "failures": 0,
        "errors": 0,
        "passed": None,
    }
    failed = re.search(r"FAILED\s*\(([^)]*)\)", text)
    if failed:
        for field in ("failures", "errors"):
            match = re.search(rf"{field}=(\d+)", failed.group(1))
            if match:
                counts[field] = int(match.group(1))
        counts["passed"] = False
    elif re.search(r"\bOK\b", text):
        counts["passed"] = True
    return counts


def run_verification(
    contract: dict[str, Any],
    manifest: dict[str, str],
    patch_digest: str,
    *,
    root: Path,
    check_names: Any = DEFAULT_CHECKS,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run offline checks and return a deterministic evidence artifact.

    The supplied ``manifest`` must already match the checkout; it is recomputed
    after each check so a verification step that mutates an in-scope file fails
    closed. ``runner`` exists only for offline tests and must honour the same
    keyword contract as ``_default_runner``.
    """
    assert_offline_command_registry()
    try:
        normalized = validate_task_contract(contract)
    except TaskContractError as exc:
        raise VerificationError("verification requires a valid task contract") from exc
    selected = validate_check_names(check_names)
    if not isinstance(manifest, dict) or not manifest or any(
        not isinstance(path, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
        for path, digest in manifest.items()
    ):
        raise VerificationError("snapshot manifest is malformed")
    if not isinstance(patch_digest, str) or not _DIGEST.fullmatch(patch_digest):
        raise VerificationError("patch digest must be a SHA-256 hex digest")
    if not isinstance(root, Path) or not root.is_dir():
        raise VerificationError("verification root must be an existing directory")
    timeout = normalized["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise VerificationError("verification requires a positive timeout")
    per_check_timeout = min(timeout, MAX_CHECK_SECONDS)

    checkout = root.resolve()
    try:
        current = snapshot_manifest(checkout, normalized["allowed_paths"])
    except (TaskContractError, OSError) as exc:
        raise VerificationError("snapshot cannot be verified before checks") from exc
    if current != manifest:
        raise VerificationError("snapshot manifest does not match the checkout")

    run = runner if runner is not None else _default_runner
    records: list[dict[str, Any]] = []
    all_passed = True
    for name in selected:
        declared = CHECK_REGISTRY[name]
        argv = [sys.executable if part == "python" else part for part in declared]
        try:
            completed = run(
                argv,
                cwd=str(checkout),
                env=scrub_environment(),
                timeout=per_check_timeout,
            )
        except Exception:
            # A broken runner is a deterministic execution failure; never trust
            # or persist its exception text.
            completed = _Completed(EXECUTION_ERROR_EXIT_CODE, execution_error=True)
        stdout, stdout_truncated, stdout_digest = _bounded_text(
            getattr(completed, "stdout", b"")
        )
        stderr, stderr_truncated, stderr_digest = _bounded_text(
            getattr(completed, "stderr", b"")
        )
        returncode = getattr(completed, "returncode", EXECUTION_ERROR_EXIT_CODE)
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            returncode = EXECUTION_ERROR_EXIT_CODE
        timed_out = bool(getattr(completed, "timed_out", False)) or returncode == TIMEOUT_EXIT_CODE
        execution_error = (
            bool(getattr(completed, "execution_error", False))
            or returncode == EXECUTION_ERROR_EXIT_CODE
        )
        passed = returncode == 0 and not timed_out and not execution_error
        combined = f"{stdout}\n{stderr}"
        record: dict[str, Any] = {
            "name": name,
            "argv": list(declared),
            "exit_code": returncode,
            "timed_out": timed_out,
            "execution_error": execution_error,
            "passed": passed,
            "stdout_sha256": stdout_digest,
            "stderr_sha256": stderr_digest,
            "output_truncated": stdout_truncated or stderr_truncated,
            "test_counts": parse_test_counts(combined),
        }
        if not passed:
            record["output_excerpt"] = redact_output(combined.strip())[:MAX_EXCERPT_CHARS]
        try:
            after = snapshot_manifest(checkout, normalized["allowed_paths"])
        except (TaskContractError, OSError) as exc:
            raise VerificationError(f"snapshot cannot be re-verified after {name}") from exc
        if after != manifest:
            raise VerificationError(f"snapshot changed during verification check: {name}")
        records.append(record)
        all_passed = all_passed and passed

    artifact: dict[str, Any] = {
        "schema_version": 1,
        "task_id": normalized["task_id"],
        "base_sha": normalized["base_sha"],
        "snapshot_digest": snapshot_digest(manifest),
        "patch_digest": patch_digest,
        "checks": records,
        "passed": all_passed,
        "snapshot_intact": True,
        "provider_calls": 0,
        "live_source_requests": 0,
        "runtime_isolation_demonstrated": False,
        "execution_enabled": False,
        "draft_pr_created": False,
        "requires_owner_approval": True,
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    artifact["evidence_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return artifact


def verify_evidence_digest(artifact: Any) -> None:
    """Reject an artifact whose declared digest does not match its contents."""
    if not isinstance(artifact, dict):
        raise VerificationError("evidence artifact must be an object")
    declared = artifact.get("evidence_digest")
    if not isinstance(declared, str) or not _DIGEST.fullmatch(declared):
        raise VerificationError("evidence artifact has no valid digest")
    payload = dict(artifact)
    payload.pop("evidence_digest", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != declared:
        raise VerificationError("evidence digest mismatch")


def assert_offline_evidence(artifact: Any) -> None:
    """Fail closed if an artifact claims activity or isolation this runner cannot prove."""
    verify_evidence_digest(artifact)
    for field in ("provider_calls", "live_source_requests"):
        value = artifact.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise VerificationError(f"evidence field must be zero: {field}")
    if artifact.get("runtime_isolation_demonstrated") is not False:
        raise VerificationError("runtime isolation must not be claimed by this runner")
    if artifact.get("execution_enabled") is not False or artifact.get("draft_pr_created") is not False:
        raise VerificationError("verification evidence must remain non-executing")


def correction_feedback(artifact: dict[str, Any], *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """Return bounded, deterministic feedback that cites the exact failed checks."""
    assert_offline_evidence(artifact)
    if artifact.get("passed"):
        return ""
    lines = [
        f"verification failed for {artifact.get('task_id')} at {artifact.get('base_sha')}",
    ]
    for record in artifact.get("checks", []):
        if record.get("passed"):
            continue
        if record.get("timed_out"):
            reason = "timeout"
        elif record.get("execution_error"):
            reason = "execution error"
        else:
            reason = f"exit code {record.get('exit_code')}"
        lines.append(f"- {record.get('name')}: {reason}")
        excerpt = str(record.get("output_excerpt", "")).strip()
        if excerpt:
            lines.append(f"  {excerpt.splitlines()[0][:200]}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "[truncated]"
    return text
