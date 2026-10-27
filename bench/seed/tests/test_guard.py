from toyshop.guard import can_auto_submit


def test_small_order_auto():
    assert can_auto_submit(100.0)


def test_large_order_needs_approval():
    assert not can_auto_submit(900.0)
    assert can_auto_submit(900.0, approved_by="Jane Doe")
