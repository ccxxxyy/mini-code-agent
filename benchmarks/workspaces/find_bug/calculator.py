def sum_range(n):
    """Return sum of 1 to n inclusive."""
    total = 0
    for i in range(1, n):  # BUG: should be n+1
        total += i
    return total
