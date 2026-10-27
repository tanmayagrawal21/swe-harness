from toyshop.pricing import subtotal


def test_subtotal():
    assert subtotal([(2.0, 3), (1.5, 2)]) == 9.0
