from wordtally import count_words, top_words


def test_order_and_ties():
    assert top_words({"b": 2, "a": 2, "c": 5, "d": 1}, 3) == [("c", 5), ("a", 2), ("b", 2)]


def test_bounds():
    assert top_words({"a": 1}, 0) == []
    assert top_words({"a": 1}, -1) == []
    assert top_words({"a": 1, "b": 2}, 10) == [("b", 2), ("a", 1)]


def test_composes_with_count_words():
    assert top_words(count_words("x y x"), 1) == [("x", 2)]
