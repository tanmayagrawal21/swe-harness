from toyshop.pricing_extra import item_count


def test_item_count():
    assert item_count([(1.0, 2), (3.0, 4)]) == 6
