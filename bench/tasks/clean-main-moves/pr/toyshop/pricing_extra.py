def item_count(items: list[tuple[float, int]]) -> int:
    return sum(qty for _, qty in items)
