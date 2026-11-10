"""Strict parsing for independent Hive audit verdicts."""

MAX_VERDICT_CHARS = 240


def concise_audit_verdict(raw):
    """Accept only a standalone PASS or an explicit FAIL: line."""
    if not isinstance(raw, str):
        return "INVALID_AUDIT_RESPONSE"
    for line in raw.splitlines():
        line = line.strip()
        if line == "PASS":
            return "PASS"
        if line.startswith("FAIL:"):
            return " ".join(line.split())[:MAX_VERDICT_CHARS]
    return "INVALID_AUDIT_RESPONSE"
