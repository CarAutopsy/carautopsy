import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hive_batch import bounded_batch_size


def test_default_batch_is_three():
    assert bounded_batch_size(None) == 3


def test_batch_size_is_clamped_to_safe_range():
    assert bounded_batch_size("99") == 5
    assert bounded_batch_size("0") == 1
    assert bounded_batch_size("-4") == 1


def test_invalid_batch_size_uses_default():
    assert bounded_batch_size("overnight") == 3


def test_next_unattempted_task_skips_and_rotates_previously_attempted_variant():
    from hive_batch import next_unattempted_task

    first = {"variant_id": "A"}
    second = {"variant_id": "B"}
    queue = [first, second]

    selected = next_unattempted_task(queue, {"A"})

    assert selected is second
    assert queue == [second, first]


def test_next_unattempted_task_restores_queue_when_all_variants_were_attempted():
    from hive_batch import next_unattempted_task

    first = {"variant_id": "A"}
    second = {"variant_id": "B"}
    queue = [first, second]

    selected = next_unattempted_task(queue, {"A", "B"})

    assert selected is None
    assert queue == [first, second]


def test_next_unattempted_task_returns_first_task_when_none_were_attempted():
    from hive_batch import next_unattempted_task

    first = {"variant_id": "A"}
    second = {"variant_id": "B"}
    queue = [first, second]

    assert next_unattempted_task(queue, set()) is first
    assert queue == [first, second]
