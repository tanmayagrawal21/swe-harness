import argparse
import sys

from . import count_words, load_stopwords, top_words


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wordtally")
    ap.add_argument("file")
    ap.add_argument("--top", type=int)
    ap.add_argument("--stopwords")
    a = ap.parse_args(argv)
    try:
        with open(a.file, encoding="utf-8") as fh:
            counts = count_words(fh.read())
        stop = load_stopwords(a.stopwords) if a.stopwords else set()
    except OSError as e:
        print(f"wordtally: {e}", file=sys.stderr)
        return 1
    counts = {w: n for w, n in counts.items() if w not in stop}
    for word, n in top_words(counts, a.top if a.top is not None else len(counts)):
        print(f"{word}\t{n}")
    return 0


sys.exit(main())
