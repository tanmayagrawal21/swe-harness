from wordtally import count_words


def test_count_words():
    assert count_words("A a b") == {"a": 2, "b": 1}
    assert count_words("") == {}
