def format_price(cents: int) -> str:
    """Format integer cents as dollars, e.g. 1234 -> "$12.34"."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
