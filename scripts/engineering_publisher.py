"""Owner-gated draft-PR publisher and reconciliation for the engineering agent.

Pure, deterministic, offline helpers only. This module performs no network,
``gh``, ``git``-write or secret access and is not imported by any production
module or workflow. A future controller must obtain explicit owner approval
before any of these proposals can be acted on. The proposal objects produced
here always report ``draft_pr_created=False`` and ``publication_enabled=False``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from engineering_task import parse_audit_quorum, validate_task_contract
from engineering_verification import VerificationError, assert_offline_evidence, redact_output


class PublisherError(ValueError):
    """Raised when a publication or reconciliation input is unsafe or ambiguous."""


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BRANCH = re.compile(r"eng/eng-[a-z0-9][a-z0-9-]{1,63}\Z")
_DIGEST_MARKER = re.compile(r"proposal_digest:\s*([0-9a-f]{64})")
MAX_TITLE_CHARS = 200
MAX_BODY_CHARS = 4_000
MAX_EXCERPT_CHARS = 2_000


def _canonical(value: Any) -> bytes:
    """Stable UTF-8 bytes for a JSON value; non-finite numbers are rejected."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise PublisherError("proposal is not safely serializable JSON") from exc


def proposal_digest(proposal: dict[str, Any]) -> str:
    """SHA-256 over the canonical proposal with any prior digest removed."""
    if not isinstance(proposal, dict):
        raise PublisherError("proposal must be an object")
    payload = {key: value for key, value in proposal.items() if key != "proposal_digest"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def verify_proposal_digest(proposal: Any) -> None:
    """Reject a proposal whose declared digest does not match its contents."""
    if not isinstance(proposal, dict):
        raise PublisherError("proposal must be an object")
    declared = proposal.get("proposal_digest")
    if not isinstance(declared, str) or _SHA256.fullmatch(declared) is None:
        raise PublisherError("proposal has no valid digest")
    if not hmac.compare_digest(proposal_digest(proposal), declared):
        raise PublisherError("proposal digest mismatch")


def _validated_quorum(
    audit_quorum: Any, artifact: dict[str, Any]
) -> dict[str, Any]:
    """Bind the supplied audit records to this exact verification artifact."""
    result = parse_audit_quorum(
        audit_quorum,
        bundle_sha256=artifact["snapshot_digest"],
        base_sha=artifact["base_sha"],
    )
    if result.get("accepted") is not True:
        raise PublisherError(f"audit quorum was not accepted: {result.get('reason', 'unknown')}")
    if result.get("bundle_sha256") != artifact["snapshot_digest"]:
        raise PublisherError("audit quorum is not bound to this snapshot digest")
    if result.get("base_sha") != artifact["base_sha"]:
        raise PublisherError("audit quorum is not bound to this base SHA")
    return result


def build_draft_pr_proposal(
    contract: dict[str, Any],
    verification_artifact: dict[str, Any],
    audit_quorum: Any,
    *,
    owner_approved: bool = False,
    existing_prs: Any = (),
) -> dict[str, Any]:
    """Build a deterministic, inert draft-PR proposal; never creates a PR."""
    if type(owner_approved) is not bool:
        raise PublisherError("owner_approved must be a boolean")
    if not isinstance(existing_prs, (list, tuple)) or any(
        not isinstance(item, dict) for item in existing_prs
    ):
        raise PublisherError("existing_prs must be a list of objects")

    try:
        normalized = validate_task_contract(contract)
        assert_offline_evidence(verification_artifact)
    except (ValueError, VerificationError) as exc:
        raise PublisherError(f"verification evidence is not valid: {exc}") from exc

    if verification_artifact.get("passed") is not True:
        raise PublisherError("verification did not pass")
    if verification_artifact.get("working_tree_intact") is not True:
        raise PublisherError("working tree integrity was not established")
    if verification_artifact.get("task_id") != normalized["task_id"]:
        raise PublisherError("verification artifact task identity mismatch")
    if verification_artifact.get("base_sha") != normalized["base_sha"]:
        raise PublisherError("verification artifact base SHA mismatch")

    quorum = _validated_quorum(audit_quorum, verification_artifact)
    branch = f"eng/{normalized['task_id']}"
    if _BRANCH.fullmatch(branch) is None:
        raise PublisherError("deterministic branch name is not safe")

    title = redact_output(str(normalized["goal"]).strip())[:MAX_TITLE_CHARS]
    if not title:
        raise PublisherError("draft PR title must not be empty")
    body_lines = [
        f"task_id: {normalized['task_id']}",
        f"base_sha: {normalized['base_sha']}",
        f"snapshot_digest: {verification_artifact['snapshot_digest']}",
        "acceptance_criteria:",
    ]
    body_lines.extend(f"- {redact_output(str(item))[:200]}" for item in normalized["acceptance_criteria"])
    body_lines.append(f"evidence_digest: {verification_artifact['evidence_digest']}")
    body = "\n".join(body_lines)[:MAX_BODY_CHARS]

    proposal: dict[str, Any] = {
        "schema_version": 1,
        "task_id": normalized["task_id"],
        "base_sha": normalized["base_sha"],
        "branch": branch,
        "title": title,
        "body": body,
        "snapshot_digest": verification_artifact["snapshot_digest"],
        "evidence_digest": verification_artifact["evidence_digest"],
        "audit": {
            "vendors": quorum["vendors"],
            "verdicts": quorum["verdicts"],
            "bundle_sha256": quorum["bundle_sha256"],
            "base_sha": quorum["base_sha"],
        },
        "draft": True,
        "draft_pr_created": False,
        "execution_enabled": False,
        "publication_enabled": False,
        "direct_main_push": False,
        "requires_owner_approval": True,
        "owner_approved": owner_approved,
        "mode": "proposal-only",
    }
    proposal["proposal_digest"] = proposal_digest(proposal)
    verify_proposal_digest(proposal)
    return proposal


def _matching_prs(proposal: dict[str, Any], open_prs: Any) -> list[dict[str, Any]]:
    if not isinstance(open_prs, (list, tuple)) or any(not isinstance(item, dict) for item in open_prs):
        raise PublisherError("open_prs must be a list of objects")
    branch = proposal.get("branch")
    if not isinstance(branch, str) or _BRANCH.fullmatch(branch) is None:
        raise PublisherError("proposal branch is not safe")
    return [item for item in open_prs if item.get("headRefName") == branch]


def _pr_digest(pr: dict[str, Any]) -> str | None:
    declared = pr.get("proposal_digest")
    if isinstance(declared, str) and _SHA256.fullmatch(declared):
        return declared
    body = pr.get("body")
    match = _DIGEST_MARKER.search(body) if isinstance(body, str) else None
    return match.group(1) if match else None


def reconcile_draft_pr(proposal: dict[str, Any], open_prs: Any) -> dict[str, Any]:
    """Reconcile a proposal against supplied PR metadata; never fetches GitHub."""
    verify_proposal_digest(proposal)
    if proposal.get("draft") is not True or proposal.get("draft_pr_created") is not False:
        raise PublisherError("proposal must remain an uncreated draft")
    matches = _matching_prs(proposal, open_prs)
    if len(matches) > 1:
        raise PublisherError("ambiguous state: multiple open PRs claim the task branch")

    status: str
    matched_number: int | None = None
    if not matches:
        status = "create_draft_proposal"
    else:
        pr = matches[0]
        number = pr.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise PublisherError("matching PR has no valid number")
        matched_number = number
        base = pr.get("baseRefName")
        if base != "main":
            raise PublisherError("matching PR does not target main")
        if pr.get("isDraft") is not True:
            raise PublisherError("matching PR is not a draft")
        observed = _pr_digest(pr)
        if observed is None or _SHA256.fullmatch(observed) is None:
            raise PublisherError("matching PR has no verifiable proposal digest")
        if observed == proposal["proposal_digest"]:
            status = "already_open_same_digest"
        else:
            status = "needs_update_proposal"

    result = {
        "schema_version": 1,
        "status": status,
        "task_id": proposal["task_id"],
        "branch": proposal["branch"],
        "proposal_digest": proposal["proposal_digest"],
        "matched_pr_number": matched_number,
        "draft_pr_created": False,
        "execution_enabled": False,
        "direct_main_push": False,
        "requires_owner_approval": True,
    }
    result["reconciliation_digest"] = proposal_digest(result)
    return result


def classify_publish_response(response: Any) -> str:
    """Classify a write response; ambiguity never authorizes an automatic retry."""
    if isinstance(response, dict) and response.get("reconciled") is True:
        return "reconciled"
    if (
        isinstance(response, dict)
        and response.get("status") in {"published", "created"}
        and response.get("reconciled") is not False
    ):
        return "published"
    return "uncertain"


def redacted_excerpt(text: Any) -> str:
    """Return a bounded, secret-redacted excerpt of untrusted text."""
    if not isinstance(text, str):
        raise PublisherError("excerpt must be text")
    return redact_output(text.strip())[:MAX_EXCERPT_CHARS]
