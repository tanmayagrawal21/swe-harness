import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*args):
    return subprocess.run([sys.executable, "-m", "wordtally", *args], cwd=ROOT, capture_output=True, text=True)


def test_prints_all_words(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("b a b c", encoding="utf-8")
    r = run(str(f))
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["b\t2", "a\t1", "c\t1"]


def test_top(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("b a b c", encoding="utf-8")
    assert run(str(f), "--top", "1").stdout.splitlines() == ["b\t2"]


def test_missing_file(tmp_path):
    r = run(str(tmp_path / "nope.txt"))
    assert r.returncode == 1
    assert "Traceback" not in r.stderr and r.stderr.strip()
