from toyshop.pricing import bulk_discount


def test_bulk_discount():
    assert bulk_discount(20) == 0.10
    assert bulk_discount(1) == 0.0
