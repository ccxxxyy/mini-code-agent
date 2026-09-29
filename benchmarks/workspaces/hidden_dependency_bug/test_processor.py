from processor import sum_column


def test_sum_middle_column():
    assert sum_column(["1,2,3", "4,5,6"], 1) == 7


def test_sum_first_column():
    assert sum_column(["10,20", "30,40"], 0) == 40
