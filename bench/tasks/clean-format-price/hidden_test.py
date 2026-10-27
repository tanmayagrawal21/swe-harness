from toyshop.fmt import format_price


def test_hidden():
    assert format_price(100) == "$1.00"
