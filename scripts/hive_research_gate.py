"""Fail-closed guard for autonomous Hive research execution."""


class ResearchPaused(RuntimeError):
    """Raised when research cannot proceed without verified source retrieval."""

    exit_code = 2


PAUSE_REASON = (
    "verified source retrieval is not available; Hive research is paused before "
    "provider calls and before any queue, ledger, branch, or PR mutation"
)


def require_verified_retrieval(available):
    """Stop research-only execution unless verified retrieval is explicitly ready."""
    if available is not True:
        raise ResearchPaused(PAUSE_REASON)
