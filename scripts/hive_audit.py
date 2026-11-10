"""Strict parsing for independent Hive audit verdicts."""

MAX_VERDICT_CHARS = 240


def concise_audit_verdict(raw):
    """Accept an unambiguous standalone PASS or explicit FAIL: verdict."""
    if not isinstance(raw, str):
        return "INVALID_AUDIT_RESPONSE"
    passes = []
    failures = []
    for line in raw.splitlines():
        line = line.strip()
        if line.upper() in {"PASS", "PASS."}:
            passes.append("PASS")
        elif line.upper().startswith("FAIL:"):
            failures.append(" ".join(line.split())[:MAX_VERDICT_CHARS])
    if passes and failures:
        return "INVALID_AUDIT_RESPONSE"
    if len(passes) == 1:
        return "PASS"
    if failures:
        return failures[0]
    return "INVALID_AUDIT_RESPONSE"
