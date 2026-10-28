"""Count words in text."""

import re
from collections import Counter

WORD = re.compile(r"[A-Za-z0-9']+")


def count_words(text: str) -> dict[str, int]:
    return dict(Counter(w.lower() for w in WORD.findall(text)))
