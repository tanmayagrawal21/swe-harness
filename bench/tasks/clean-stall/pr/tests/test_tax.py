from toyshop.tax import with_tax


def test_with_tax():
    assert with_tax(10.0, 0.1) == 11.0
