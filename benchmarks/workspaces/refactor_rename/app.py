from helpers import calc_total

def process_order(items):
    prices = [item["price"] for item in items]
    total = calc_total(prices)
    return {"total": total, "items": len(items)}
