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
