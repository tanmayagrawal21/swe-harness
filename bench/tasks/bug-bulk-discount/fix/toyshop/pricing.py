from __future__ import annotations


def subtotal(items: list[tuple[float, int]]) -> float:
    """Sum of price * quantity."""
    return sum(price * qty for price, qty in items)


def bulk_discount(qty: int) -> float:
    """Discount rate for a line: 10% when buying in bulk."""
    return 0.10 if qty >= 10 else 0.0
