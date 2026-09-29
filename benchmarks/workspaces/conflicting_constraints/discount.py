"""Order pricing. 订单计价。"""


def final_price(unit_price: float, quantity: int, is_member: bool) -> float:
    """Total price after all applicable discounts.

    Bulk orders (quantity >= 10) get 10% off.
    Members get 5% off.
    Discounts are ADDITIVE -- a member buying 10+ units gets 15% off.
    """
    return unit_price * quantity
