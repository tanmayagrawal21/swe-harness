from wordtally import count_words


def test_counts_case_insensitively():
    assert count_words("The cat, the hat.") == {"the": 2, "cat": 1, "hat": 1}


def test_empty_and_punctuation_only():
    assert count_words("") == {}
    assert count_words(" ,.; !") == {}


def test_apostrophes_and_digits():
    assert count_words("Don't stop: 2 don't") == {"don't": 2, "stop": 1, "2": 1}
