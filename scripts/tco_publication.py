"""Fail-closed guards for the owner-dispatched TCO publication path.

Pure helpers only: no network, no git writes, no provider calls. The full TCO
route must use these guards before any state-changing command. Direct pushes to
``main`` are deliberately not produced here; publication remains disabled until
the owner separately approves a publication path.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


PUBLICATION_PATH = "apps/web/public/data/autopsies.json"
ATTESTATION_BINDING_FIELDS = (
    "schema_version",
    "payload_sha256",
    "catalog_sha256",
    "country_pack",
    "country_pack_sha256",
    "engine_version",
)
MAX_PACK_FILES = 200
PACK_RULE_EXTENSIONS = frozenset({".yaml", ".yml", ".json"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


class PublicationBlocked(RuntimeError):
    """Raised when a publication attempt is not safe to perform."""


def canonical_bytes(value: Any) -> bytes:
    """Stable UTF-8 bytes for hashing a JSON value."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without the run-specific ``envelope.generated_utc`` value.

    ``tco_engine.publication_artifact_is_current`` ignores this timestamp when
    deciding whether an artifact is current, so the attestation digest must too;
    otherwise a new timestamp would look like a new input on every run.
    """
    if not isinstance(payload, dict):
        raise PublicationBlocked("payload must be an object")
    envelope = payload.get("envelope")
    if not isinstance(envelope, dict) or "generated_utc" not in envelope:
        return dict(payload)
    stable_envelope = {key: value for key, value in envelope.items() if key != "generated_utc"}
    return {**payload, "envelope": stable_envelope}


def catalog_digest(root: Path) -> str:
    """Hash the exact catalog input set (names and bytes, in sorted order)."""
    variants = sorted((Path(root) / "catalog" / "variants").glob("*.json"))
    if not variants:
        raise PublicationBlocked("catalog input set is empty")
    hasher = hashlib.sha256()
    for path in variants:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


def country_pack_digest(root: Path, country: str = "AT") -> str:
    """Hash every rule file in the pack; a rule edit changes this digest."""
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise PublicationBlocked("country code must be two uppercase letters")
    pack = Path(root) / "country-packs" / country
    files = sorted(
        path for path in pack.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith((".", "~"))
        and not path.name.endswith(("~", ".tmp", ".bak"))
        and path.suffix.casefold() in PACK_RULE_EXTENSIONS
    )
    if not files:
        raise PublicationBlocked(f"country pack has no rule files: {country}")
    if len(files) > MAX_PACK_FILES:
        raise PublicationBlocked(f"country pack exceeds {MAX_PACK_FILES} rule files")
    hasher = hashlib.sha256()
    for path in files:
        relative = path.relative_to(pack).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()


def build_run_url(server: Any, repository: Any, run_id: Any) -> str | None:
    """Build exact run evidence from standard GitHub Actions values (pure)."""
    if not isinstance(server, str) or not server.startswith("https://"):
        return None
    if not isinstance(repository, str) or re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ) is None:
        return None
    if any(part in {".", ".."} for part in repository.split("/")):
        return None
    if not isinstance(run_id, str) or not run_id.isdigit():
        return None
    return f"{server.rstrip('/')}/{repository}/actions/runs/{run_id}"


def build_attestation(
    *,
    payload: dict[str, Any],
    base_sha: str,
    catalog_sha256: str,
    country_pack: str,
    engine_version: str,
    country_pack_sha256: str,
    run_url: str | None = None,
) -> dict[str, Any]:
    """Bind a payload to the exact inputs and run evidence that produced it."""
    if not isinstance(payload, dict):
        raise PublicationBlocked("payload must be an object")
    if not isinstance(base_sha, str) or _SHA1.fullmatch(base_sha) is None:
        raise PublicationBlocked("base_sha must be a 40-character commit SHA")
    if not isinstance(catalog_sha256, str) or _SHA256.fullmatch(catalog_sha256) is None:
        raise PublicationBlocked("catalog_sha256 must be a SHA-256 digest")
    for label, value in (("country_pack", country_pack), ("engine_version", engine_version)):
        if not isinstance(value, str) or not value.strip():
            raise PublicationBlocked(f"{label} is missing")
    if run_url is not None and (not isinstance(run_url, str) or len(run_url) > 300):
        raise PublicationBlocked("run_url must be a bounded string")
    if not isinstance(country_pack_sha256, str) or _SHA256.fullmatch(country_pack_sha256) is None:
        raise PublicationBlocked("country_pack_sha256 must be a SHA-256 digest")
    return {
        "schema_version": 1,
        "base_sha": base_sha,
        "catalog_sha256": catalog_sha256,
        "country_pack": country_pack,
        "country_pack_sha256": country_pack_sha256,
        "engine_version": engine_version,
        "run_url": run_url,
        "payload_sha256": hashlib.sha256(canonical_bytes(stable_payload(payload))).hexdigest(),
    }


def assert_attestation(artifact: Any, expected: dict[str, Any]) -> None:
    """Reject an artifact whose input binding differs.

    ``base_sha`` and ``run_url`` are not compared: they record the run that last
    changed the bound inputs, so an unchanged-payload run with a new commit or
    run URL does not invalidate the artifact.
    """
    if not isinstance(artifact, dict) or not isinstance(artifact.get("attestation"), dict):
        raise PublicationBlocked("published artifact lacks an attestation")
    actual = artifact["attestation"]
    if any(actual.get(field) != expected.get(field) for field in ATTESTATION_BINDING_FIELDS):
        raise PublicationBlocked("published artifact attestation does not match inputs")


def parse_status_paths(status_output: str) -> list[str]:
    """Parse ``git status --porcelain`` into paths without executing git."""
    if not isinstance(status_output, str):
        raise PublicationBlocked("git status output must be text")
    paths: list[str] = []
    for line in status_output.splitlines():
        if len(line) < 4 or line[2] != " ":
            raise PublicationBlocked("malformed git status line")
        # A rename/copy has two paths; accepting only its destination could
        # conceal mutation of an unrelated source path. Neither operation is
        # needed to refresh the single publication artifact.
        if "R" in line[:2] or "C" in line[:2]:
            raise PublicationBlocked("rename or copy blocks publication")
        raw = line[3:]
        if raw.startswith('"') and raw.endswith('"'):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError) as exc:
                raise PublicationBlocked("could not decode a quoted git status path") from exc
        if not isinstance(raw, str) or not raw:
            raise PublicationBlocked("git status produced an invalid path")
        paths.append(raw)
    return paths


def assert_only_publication_paths_changed(
    status_output: str, allowed: tuple[str, ...] = (PUBLICATION_PATH,)
) -> list[str]:
    """Reject any working-tree change outside the explicit publication allow-list."""
    changed = parse_status_paths(status_output)
    unrelated = sorted({path for path in changed if path not in allowed})
    if unrelated:
        raise PublicationBlocked(
            "unrelated working-tree changes block publication: " + ", ".join(unrelated[:10])
        )
    return changed


def assert_publication_gate(
    *,
    audit_failures: int,
    status_output: str,
    attestation: dict[str, Any],
    expected_attestation: dict[str, Any],
) -> list[str]:
    """Fail closed before any write when failures, stray files or drift exist."""
    if not isinstance(audit_failures, int) or isinstance(audit_failures, bool) or audit_failures < 0:
        raise PublicationBlocked("audit failure count is invalid")
    if audit_failures:
        raise PublicationBlocked("audit failures prevent publication")
    changed = assert_only_publication_paths_changed(status_output)
    assert_attestation({"attestation": attestation}, expected_attestation)
    return changed


def is_duplicate_publication(existing: Any, attestation: dict[str, Any]) -> bool:
    """True when the same payload is already published, ignoring a new HEAD SHA.

    Duplicate detection is based on the payload digest so that a new commit
    which does not change the calculation is not treated as a new publication.
    """
    existing_attestation = existing.get("attestation") if isinstance(existing, dict) else None
    return (
        isinstance(existing, dict)
        and isinstance(existing_attestation, dict)
        and isinstance(existing.get("results"), list)
        and all(
            existing_attestation.get(field) == attestation.get(field)
            for field in ("payload_sha256", "catalog_sha256", "country_pack_sha256")
        )
    )


def publication_needs_refresh(existing: Any, payload: dict[str, Any], attestation: dict[str, Any]) -> bool:
    """Decide whether the local artifact must be rewritten (no git write).

    HEAD SHA and run URL are run-specific evidence, not input bindings: they
    must not force a rewrite on every scheduled run.
    """
    from tco_engine import publication_artifact_is_current

    if not isinstance(existing, dict):
        return True
    actual = existing.get("attestation")
    binding_changed = (
        not isinstance(actual, dict)
        or any(actual.get(field) != attestation.get(field) for field in ATTESTATION_BINDING_FIELDS)
    )
    return binding_changed or not publication_artifact_is_current(existing, payload)


def classify_publication_response(response: Any) -> str:
    """Classify a write response; ambiguous results never authorize a retry."""
    if isinstance(response, dict):
        if response.get("reconciled") is True:
            return "reconciled"
        if response.get("status") in {"published", "created"} and response.get("reconciled") is not False:
            return "published"
    return "uncertain"


def draft_publication_proposal(
    *, base_sha: str, attestation: dict[str, Any], owner_approved: bool = False
) -> dict[str, Any]:
    """Return an owner-gated draft-PR proposal; never creates a PR or pushes."""
    proposal = {
        "schema_version": 1,
        "mode": "proposal-only",
        "base_sha": base_sha,
        "attestation": attestation,
        "target": "draft-pull-request",
        "direct_main_push": False,
        "draft_pr_created": False,
        "requires_owner_approval": True,
    }
    if not owner_approved:
        return proposal
    return {**proposal, "owner_approved": True, "publication_enabled": False}
