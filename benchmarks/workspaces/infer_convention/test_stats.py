from stats import mean


def test_mean_normal():
    assert mean([2.0, 4.0]) == 3.0


def test_mean_empty_follows_module_convention():
    assert mean([]) == 0.0
