from bigmodule import compute_checksum


def test_checksum_wraps_at_256():
    assert compute_checksum([255, 1]) == 0


def test_checksum_basic():
    assert compute_checksum([1, 2, 3]) == 6
