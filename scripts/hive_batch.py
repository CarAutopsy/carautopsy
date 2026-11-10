"""Bounded batch sizing for unattended Hive research runs."""


def bounded_batch_size(raw, default=3, maximum=5):
    """Parse a positive batch size and clamp it to a safe upper bound."""
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), maximum)
