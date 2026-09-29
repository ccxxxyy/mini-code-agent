"""Column aggregation built on parser. 基于 parser 的列聚合。"""

from parser import parse_csv_line


def sum_column(lines: list[str], index: int) -> int:
    total = 0
    for line in lines:
        fields = parse_csv_line(line)
        total += int(fields[index])
    return total
