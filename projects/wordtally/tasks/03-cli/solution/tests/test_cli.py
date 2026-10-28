import subprocess
import sys


def test_cli(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("x y x", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "wordtally", str(f)], capture_output=True, text=True)
    assert r.stdout.splitlines() == ["x\t2", "y\t1"]
