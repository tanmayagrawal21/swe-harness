from toyshop.guard import can_auto_submit


def test_bad_totals():
    assert not can_auto_submit(-5.0, approved_by="Jane Doe")
    assert not can_auto_submit(float("nan"))
