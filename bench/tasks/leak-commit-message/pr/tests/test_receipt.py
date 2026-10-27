from toyshop.receipt import footer


def test_footer():
    assert footer("Acme") == "Thank you for shopping at Acme!"
