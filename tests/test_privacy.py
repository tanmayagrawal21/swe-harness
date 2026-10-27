import subprocess
import sys

from swe_harness import privacy
from swe_harness.forge import git

TERMS = ["Rowan Fictus", "(555) 010-9988", "7 Nowhere Lane"]


def test_match_is_case_and_space_insensitive():
    assert privacy.match_terms("by ROWAN   fictus", TERMS) == [1]


def test_phone_matches_digits_only():
    assert privacy.match_terms("call 555.010.9988", TERMS) == [2]
    assert privacy.match_terms("call 555-0100", TERMS) == []


def test_scan_diff_reports_added_lines_only(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("Rowan Fictus\n")  # pre-existing: not part of the diff
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "b.txt").write_text("ok\nlives at 7 nowhere lane\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "change")
    found = privacy.scan_diff(tmp_path, "HEAD~1...HEAD", TERMS)
    assert [str(f) for f in found] == ["b.txt:2: private term #3"]


def test_cli_never_prints_terms(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text("# comment\n" + "\n".join(TERMS))
    leak = tmp_path / "leak.md"
    leak.write_text("contact Rowan Fictus")
    r = subprocess.run([sys.executable, "-m", "swe_harness.privacy", "--terms", str(terms), "--paths", str(leak)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "private term #1" in r.stdout and "Rowan" not in r.stdout
