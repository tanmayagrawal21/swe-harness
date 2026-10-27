"""Security tier from the GitHub Advisory Database (CC0): reviewed pip advisories with a fix commit.

Each advisory yields a pair of review items, labelled by construction:
- the fix applied to its parent commit (should merge), and
- the fix reverted on top of the fix commit (should be blocked: it reintroduces the vulnerability).
  Test files are excluded from the revert, so the PR looks like an ordinary code change.
Only small Python-only fixes in small repositories are kept. Data is fetched at run time via the `gh` CLI
(the user's own authentication; nothing is stored in this repo) into the cache.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from ..forge import git
from . import cache_dir, git_seed

COMMIT = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/commit/([0-9a-f]{40})$")
TEST_GLOBS = ["*test*", "*/tests/*", "*conftest*", "*.md", "*.rst", "*.txt", "*CHANGES*", "*HISTORY*"]


def _gh(path: str, cache: Path, accept: str = "") -> str:
    key = cache / "api" / (re.sub(r"[^\w.-]", "_", path.strip("/")) + (".diff" if accept else ".json"))
    if not key.exists():
        cmd = ["gh", "api", path] + (["-H", f"Accept: {accept}"] if accept else [])
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(out)
    return key.read_text()


def _is_test(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in TEST_GLOBS)


def candidates(cache: Path, pages: int = 3) -> list[dict]:
    """Advisories whose single referenced fix commit is small, Python-only and in a small repo."""
    out, seen = [], set()
    for page in range(1, pages + 1):
        for adv in json.loads(_gh(f"/advisories?ecosystem=pip&type=reviewed&per_page=100&page={page}", cache)):
            commits = {m.groups() for r in adv.get("references") or [] if (m := COMMIT.match(r))}
            if len(commits) != 1:
                continue
            owner, repo, sha = commits.pop()
            if sha in seen:
                continue
            seen.add(sha)
            try:
                info = json.loads(_gh(f"/repos/{owner}/{repo}", cache))
                c = json.loads(_gh(f"/repos/{owner}/{repo}/commits/{sha}", cache))
            except subprocess.CalledProcessError:
                continue
            files = c.get("files") or []
            src = [f for f in files if not _is_test(f["filename"])]
            if (info.get("size", 1e9) > 80_000 or len(c.get("parents") or []) != 1 or not src or len(files) > 8
                    or not all(f["filename"].endswith(".py") for f in src)
                    or sum(f["changes"] for f in src) > 150):
                continue
            out.append({"ghsa": adv["ghsa_id"], "summary": adv.get("summary", ""), "cwes": [
                w["cwe_id"] for w in adv.get("cwes") or []], "severity": adv.get("severity"), "owner": owner,
                "repo": repo, "sha": sha, "parent": c["parents"][0]["sha"]})
    return out


def _check(seed: Path, diff: str, reverse: bool) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".diff") as tmp:
        tmp.write(diff)
        tmp.flush()
        args = ["apply", "--check"] + (["-R"] if reverse else []) + [f"--exclude={g}" for g in TEST_GLOBS]
        try:
            git(seed, *args, tmp.name)
            return True
        except RuntimeError:
            return False


def build(out: Path, limit: int = 15, pages: int = 8, cache: Path | None = None) -> Path:
    cache = cache or cache_dir() / "ghsa"
    if out.exists():
        shutil.rmtree(out)
    kept = dropped = 0
    for adv in candidates(cache, pages):
        if kept >= limit:
            break
        o, r, sha = adv["owner"], adv["repo"], adv["sha"]
        url = f"https://github.com/{o}/{r}.git"
        try:
            diff = _gh(f"/repos/{o}/{r}/commits/{sha}", cache, accept="application/vnd.github.diff")
            fixed, vulnerable = git_seed(url, sha), git_seed(url, adv["parent"])
        except (subprocess.CalledProcessError, RuntimeError):
            dropped += 1
            continue
        if not (_check(vulnerable, diff, False) and _check(fixed, diff, True)):
            dropped += 1
            continue
        issue = (f"Maintenance change in {o}/{r}. Review it like any other PR.\n\n"
                 f"(Benchmark note, not shown to gates: {adv['ghsa']}.)")
        for kind, seed_sha, reverse in (("clean", adv["parent"], False), ("unsafe", sha, True)):
            tid = f"ghsa-{adv['ghsa'].lower()}-{'fix' if kind == 'clean' else 'revert'}"
            d = out / "tasks" / tid
            d.mkdir(parents=True)
            (d / "pr.patch").write_text(diff)
            title = f"Update {o}/{r}" if reverse else f"Fix: {adv['summary'][:70]}"
            (d / "task.yaml").write_text(yaml.safe_dump({
                "id": tid, "kind": kind, "title": title, "issue": issue.split("\n\n(")[0] if reverse else
                f"{adv['summary']}\n\nApply the fix.",
                "pr": {"title": title, "commit_message": title, "reverse": reverse,
                       "exclude": TEST_GLOBS if reverse else []},
                "seed": {"git": url, "commit": seed_sha}, "oracle": "label", "ci": "skip",
                "source": {"dataset": "GitHub Advisory Database (CC0)", "advisory": adv["ghsa"],
                           "cwes": adv["cwes"], "fix_commit": f"{o}/{r}@{sha}"},
            }, sort_keys=False))
        kept += 1
    pp = out / "private_profile"
    pp.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[3] / "bench" / "private_profile" / "terms.txt", pp / "terms.txt")
    (out / "SOURCE.md").write_text(f"GitHub Advisory Database security tier: {kept} advisories ({kept} fix items, "
                                   f"{kept} revert items), {dropped} dropped (patch did not apply cleanly).\n")
    return out
