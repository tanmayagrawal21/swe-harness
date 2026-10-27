def with_tax(amount: float, rate: float) -> float:
    return round(amount * (1 + rate), 2)
