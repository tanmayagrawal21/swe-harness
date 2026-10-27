"""SWE-bench Verified review tier: real model patches with published, test-based resolved labels.

Each instance yields review items: the gold patch (should merge) and each chosen experiment entry's patch,
labelled by that entry's published `resolved` list (resolved: merge; unresolved: block). The PR's repo state
is the upstream repo at `base_commit`. Nothing third-party is committed to this repo: data is fetched at run
time into the cache (default ~/.cache/swe-harness, override with SWE_HARNESS_CACHE).

Sources: princeton-nlp/SWE-bench_Verified (HF datasets-server JSON API) and swe-bench/experiments
(metadata + results on GitHub; patches in the public swe-bench-submissions S3 bucket).
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

import yaml

from ..forge import git
from . import cache_dir, git_seed

ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=princeton-nlp/SWE-bench_Verified"
            "&config=default&split=test&offset={offset}&length=100")
EXP_RAW = "https://raw.githubusercontent.com/swe-bench/experiments/main/evaluation/verified/{entry}/{path}"
DEFAULT_REPOS = ["psf/requests", "pylint-dev/pylint", "pytest-dev/pytest"]
DEFAULT_ENTRIES = ["20240402_sweagent_claude3opus", "20241022_tools_claude-3-5-haiku",
                   "20241029_OpenHands-CodeAct-2.1-sonnet-20241022"]
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "swe-harness"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (fixed https hosts above)
        return r.read()


def _cached(path: Path, url: str) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(_get(url))
        tmp.rename(path)
    return path


def rows(cache: Path) -> list[dict]:
    out: list[dict] = []
    for offset in range(0, 500, 100):
        page = _cached(cache / "verified" / f"rows_{offset}.json", ROWS_URL.format(offset=offset))
        out += [r["row"] for r in json.loads(page.read_text())["rows"]]
    return out


def entry(cache: Path, name: str) -> tuple[set[str], str]:
    """(resolved instance ids, https base URL of the entry's logs)."""
    if not SAFE.match(name):
        raise ValueError(f"bad entry name {name!r}")
    d = cache / "experiments" / name
    meta = yaml.safe_load(_cached(d / "metadata.yaml", EXP_RAW.format(entry=name, path="metadata.yaml")).read_text())
    logs = (meta.get("assets") or {}).get("logs") or ""
    if not logs.startswith("s3://"):
        raise ValueError(f"{name}: no published patch logs")
    bucket, _, key = logs[5:].partition("/")
    res = json.loads(_cached(d / "results.json", EXP_RAW.format(entry=name, path="results/results.json")).read_text())
    return set(res.get("resolved") or []), f"https://{bucket}.s3.amazonaws.com/{key}"


def patch(cache: Path, name: str, logs_url: str, iid: str) -> str:
    p = cache / "experiments" / name / "patches" / f"{iid}.diff"
    try:
        return _cached(p, f"{logs_url}/{iid}/patch.diff").read_text()
    except OSError:
        return ""  # no patch published for this instance


def _applies(seed: Path, diff: str) -> bool:
    if len(diff) > 200_000:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".diff") as tmp:
        tmp.write(diff)
        tmp.flush()
        try:
            git(seed, "apply", "--check", tmp.name)
            return True
        except RuntimeError:
            return False


def build(out: Path, repos: list[str] | None = None, entries: list[str] | None = None,
          limit: int | None = None, cache: Path | None = None) -> Path:
    """Materialise review tasks into `out` (tasks/ + private_profile/). Returns `out`."""
    cache = cache or cache_dir() / "swebench"
    repos, entries = repos or DEFAULT_REPOS, entries or DEFAULT_ENTRIES
    picked = [r for r in rows(cache) if r["repo"] in repos][:limit]
    labels = {e: entry(cache, e) for e in entries}
    if out.exists():
        shutil.rmtree(out)
    n = {"merge": 0, "block": 0, "dropped": 0}
    for r in picked:
        iid = r["instance_id"]
        seed = git_seed(f"https://github.com/{r['repo']}.git", r["base_commit"])
        items = [("gold", r["patch"], "merge")]
        for e, (resolved, logs) in labels.items():
            p = patch(cache, e, logs, iid)
            if p.strip():
                items.append((e, p, "merge" if iid in resolved else "block"))
        seen: set[str] = set()
        for src, diff, label in items:
            if diff in seen:
                continue  # identical patches are one item
            seen.add(diff)
            if not _applies(seed, diff):
                n["dropped"] += 1  # corrupt or oversized published patch: not a fair review item
                continue
            tid = f"swe-{iid}-{'gold' if src == 'gold' else src.split('_')[0] + '-' + src.split('_')[-1][:24]}"
            tid = re.sub(r"[^A-Za-z0-9._-]", "-", tid)
            d = out / "tasks" / tid
            d.mkdir(parents=True)
            (d / "pr.patch").write_text(diff)
            title = r["problem_statement"].strip().splitlines()[0][:80]
            (d / "task.yaml").write_text(yaml.safe_dump({
                "id": tid, "kind": "clean" if label == "merge" else "bug", "title": title,
                "issue": r["problem_statement"],
                "pr": {"title": f"Fix {iid}", "commit_message": f"Fix {iid}"},
                "seed": {"git": f"https://github.com/{r['repo']}.git", "commit": r["base_commit"]},
                "oracle": "label", "ci": "skip",
                "source": {"dataset": "SWE-bench_Verified", "instance": iid, "patch_from": src, "label": label},
            }, sort_keys=False))
            n[label] += 1
    pp = out / "private_profile"
    pp.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(__file__).resolve().parents[3] / "bench" / "private_profile" / "terms.txt", pp / "terms.txt")
    (out / "SOURCE.md").write_text(f"SWE-bench Verified review tier: {len(picked)} instances, {n['merge']} merge "
                                   f"items, {n['block']} block items ({n['dropped']} unusable patches dropped). "
                                   f"Entries: {', '.join(entries)}.\n")
    return out
