"""Low-level CSV line parsing. 底层 CSV 行解析。"""


def parse_csv_line(line: str) -> list[str]:
    """Split one CSV line into fields."""
    return line.strip().split(";")
