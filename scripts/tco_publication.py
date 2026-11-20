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
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


class PublicationBlocked(RuntimeError):
    """Raised when a publication attempt is not safe to perform."""


def canonical_bytes(value: Any) -> bytes:
    """Stable UTF-8 bytes for hashing a JSON value."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


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
    """Hash the exact statutory input file; a rule edit changes this digest."""
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise PublicationBlocked("country code must be two uppercase letters")
    path = Path(root) / "country-packs" / country / "manifest.yaml"
    if not path.is_file():
        raise PublicationBlocked(f"country pack manifest is missing: {country}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_attestation(
    *,
    payload: dict[str, Any],
    base_sha: str,
    catalog_sha256: str,
    country_pack: str,
    engine_version: str,
    country_pack_sha256: str | None = None,
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
    if country_pack_sha256 is not None and (
        not isinstance(country_pack_sha256, str) or _SHA256.fullmatch(country_pack_sha256) is None
    ):
        raise PublicationBlocked("country_pack_sha256 must be a SHA-256 digest")
    return {
        "schema_version": 1,
        "base_sha": base_sha,
        "catalog_sha256": catalog_sha256,
        "country_pack": country_pack,
        "country_pack_sha256": country_pack_sha256,
        "engine_version": engine_version,
        "run_url": run_url,
        "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def assert_attestation(artifact: Any, expected: dict[str, Any]) -> None:
    """Reject any artifact whose attestation is missing or does not match."""
    if not isinstance(artifact, dict) or not isinstance(artifact.get("attestation"), dict):
        raise PublicationBlocked("published artifact lacks an attestation")
    if artifact["attestation"] != expected:
        raise PublicationBlocked("published artifact attestation does not match inputs")


def parse_status_paths(status_output: str) -> list[str]:
    """Parse ``git status --porcelain`` into paths without executing git."""
    if not isinstance(status_output, str):
        raise PublicationBlocked("git status output must be text")
    paths: list[str] = []
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
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
    return (
        isinstance(existing, dict)
        and isinstance(existing.get("attestation"), dict)
        and existing["attestation"].get("payload_sha256") == attestation.get("payload_sha256")
        and isinstance(existing.get("results"), list)
    )


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
