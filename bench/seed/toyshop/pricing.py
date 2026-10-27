from __future__ import annotations


def subtotal(items: list[tuple[float, int]]) -> float:
    """Sum of price * quantity."""
    return sum(price * qty for price, qty in items)
