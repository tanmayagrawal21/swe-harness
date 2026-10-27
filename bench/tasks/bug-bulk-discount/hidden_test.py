from toyshop.pricing import bulk_discount


def test_boundary():
    assert bulk_discount(10) == 0.10
    assert bulk_discount(9) == 0.0
