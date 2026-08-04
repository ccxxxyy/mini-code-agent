from calculator import sum_range

def test_sum_range():
    assert sum_range(5) == 15
    assert sum_range(1) == 1
    assert sum_range(10) == 55
