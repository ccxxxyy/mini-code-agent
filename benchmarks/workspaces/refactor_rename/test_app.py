from helpers import calculate_total
from app import process_order

def test_calculate_total():
    assert calculate_total([10, 20, 30]) == 66.0

def test_process_order():
    items = [{"price": 10}, {"price": 20}]
    result = process_order(items)
    assert result["total"] == 33.0
