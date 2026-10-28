"""Count words in text."""

import re
from collections import Counter

WORD = re.compile(r"[A-Za-z0-9']+")


def count_words(text: str) -> dict[str, int]:
    return dict(Counter(w.lower() for w in WORD.findall(text)))


def top_words(counts: dict[str, int], n: int) -> list[tuple[str, int]]:
    if n <= 0:
        return []
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
