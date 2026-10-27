"""Private-terms scanner. Reports matches by term index only; never prints a term.

Used by the privacy gate (as a tool) and by the scorer (as ground truth for leaks).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.casefold()).strip()


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass(frozen=True)
class Finding:
    where: str  # file:line, or a surface name such as "commit abc1234"
    term: int  # 1-based index into the terms file

    def __str__(self) -> str:
        return f"{self.where}: private term #{self.term}"


def load_terms(path: str | Path) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def match_terms(text: str, terms: list[str]) -> list[int]:
    """1-based indexes of terms found in text. Phone-like terms (>= 7 digits) also match digits-only."""
    norm, digits = _norm(text), _digits(text)
    hits = []
    for i, t in enumerate(terms, 1):
        d = _digits(t)
        if _norm(t) in norm or (len(d) >= 7 and len(d) >= len(t) // 2 and d in digits):
            hits.append(i)
    return hits


def scan_text(text: str, terms: list[str], where: str) -> list[Finding]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        found += [Finding(f"{where}:{n}", t) for t in match_terms(line, terms)]
    return found


def scan_diff(repo: str | Path, rng: str, terms: list[str]) -> list[Finding]:
    """Scan added lines and new filenames in `git diff rng`."""
    diff = subprocess.run(["git", "diff", "--no-color", "-U0", rng], cwd=repo, check=True,
                          capture_output=True, text=True).stdout
    found: list[Finding] = []
    path, lineno = "?", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
            found += [Finding(f"{path}:0", t) for t in match_terms(path, terms)]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+"):
            found += [Finding(f"{path}:{lineno}", t) for t in match_terms(line[1:], terms)]
            lineno += 1
    return found


def scan_tree(root: str | Path, terms: list[str]) -> list[Finding]:
    root = Path(root)
    found: list[Finding] = []
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts or not p.is_file():
            continue
        rel = str(p.relative_to(root))
        found += [Finding(f"{rel}:0", t) for t in match_terms(rel, terms)]
        try:
            found += scan_text(p.read_text(), terms, rel)
        except UnicodeDecodeError:
            continue
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--terms", required=True)
    ap.add_argument("--diff", help="git range, e.g. main...HEAD")
    ap.add_argument("--paths", nargs="*", default=[])
    a = ap.parse_args(argv)
    terms = load_terms(a.terms)
    found: list[Finding] = []
    if a.diff:
        found += scan_diff(".", a.diff, terms)
    for p in a.paths:
        found += scan_tree(p, terms) if Path(p).is_dir() else scan_text(Path(p).read_text(), terms, p)
    for f in found:
        print(f)
    print(f"{len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
