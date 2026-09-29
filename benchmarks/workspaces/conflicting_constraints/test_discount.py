from discount import final_price


def test_plain():
    assert final_price(100.0, 1, False) == 100.0


def test_bulk_only():
    assert final_price(10.0, 10, False) == 90.0


def test_member_only():
    assert final_price(100.0, 1, True) == 95.0


def test_member_and_bulk_are_additive():
    assert final_price(10.0, 10, True) == 85.0
