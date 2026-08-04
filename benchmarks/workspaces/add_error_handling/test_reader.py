from reader import read_config

def test_missing_file():
    result = read_config("nonexistent.txt")
    assert result == {}

def test_valid_config(tmp_path):
    p = tmp_path / "cfg.txt"
    p.write_text("host=localhost\nport=8080\n")
    assert read_config(str(p)) == {"host": "localhost", "port": "8080"}
