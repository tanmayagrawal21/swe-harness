import subprocess
import sys
from pathlib import Path

from wordtally import load_stopwords

ROOT = Path(__file__).resolve().parent


def run(*args):
    return subprocess.run([sys.executable, "-m", "wordtally", *args], cwd=ROOT, capture_output=True, text=True)


def test_load_stopwords(tmp_path):
    s = tmp_path / "stop.txt"
    s.write_text("The\n\nAND\n", encoding="utf-8")
    assert load_stopwords(s) == {"the", "and"}


def test_excluded_before_top(tmp_path):
    f, s = tmp_path / "a.txt", tmp_path / "stop.txt"
    f.write_text("the the the cat and cat dog", encoding="utf-8")
    s.write_text("THE\nand\n", encoding="utf-8")
    assert run(str(f), "--stopwords", str(s), "--top", "1").stdout.splitlines() == ["cat\t2"]


def test_unchanged_without_flag(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("b a b", encoding="utf-8")
    assert run(str(f)).stdout.splitlines() == ["b\t2", "a\t1"]
