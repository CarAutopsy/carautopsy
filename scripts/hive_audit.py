"""Strict parsing for independent Hive audit verdicts."""

MAX_VERDICT_CHARS = 240


def concise_audit_verdict(raw):
    """Accept only one exact PASS token or one explicit single-line FAIL reason."""
    if not isinstance(raw, str):
        return "INVALID_AUDIT_RESPONSE"
    response = raw.strip()
    if response == "PASS":
        return "PASS"
    if len(response.splitlines()) != 1:
        return "INVALID_AUDIT_RESPONSE"
    if response.startswith("FAIL: ") and response[6:].strip():
        return " ".join(response.split())[:MAX_VERDICT_CHARS]
    return "INVALID_AUDIT_RESPONSE"
