from wordtally import top_words


def test_top_words():
    assert top_words({"b": 1, "a": 1, "c": 2}, 2) == [("c", 2), ("a", 1)]
    assert top_words({"a": 1}, 0) == []
