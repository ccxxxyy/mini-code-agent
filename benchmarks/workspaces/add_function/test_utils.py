from utils import parse_csv

def test_parse_csv_basic():
    assert parse_csv("a,b,c") == ["a", "b", "c"]

def test_parse_csv_with_spaces():
    assert parse_csv("a, b, c") == ["a", "b", "c"]

def test_parse_csv_empty():
    assert parse_csv("") == []
