from toyshop.fmt import format_price


def test_format_price():
    assert format_price(1234) == "$12.34"
    assert format_price(5) == "$0.05"
    assert format_price(-250) == "-$2.50"
