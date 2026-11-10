"""Bounded batch sizing for unattended Hive research runs."""


def bounded_batch_size(raw, default=3, maximum=5):
    """Parse a positive batch size and clamp it to a safe upper bound."""
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), maximum)


def next_unattempted_task(tasks, attempted_variant_ids):
    """Rotate already-attempted tasks to the tail and return the next eligible task.

    At most one queue traversal is performed. If every remaining task was
    attempted in this batch, the original queue order is restored and None is
    returned so a later scheduled invocation can retry them.
    """
    for _ in range(len(tasks)):
        task = tasks[0]
        if task.get("variant_id") not in attempted_variant_ids:
            return task
        tasks.append(tasks.pop(0))
    return None
