"""Task sources: materialise benchmark tasks from public datasets into a cache outside the repo."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

from ..forge import git

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def cache_dir() -> Path:
    return Path(os.environ.get("SWE_HARNESS_CACHE", Path.home() / ".cache" / "swe-harness")).resolve()


def seed_repo(seed: Path) -> Path:
    """A cached git repo whose single commit is `seed`'s tree; episodes clone it (hardlinked objects)."""
    with _guard:
        lock = _locks.setdefault(str(seed), threading.Lock())
    with lock:
        repo = seed.with_name(seed.name + ".repo")
        if repo.exists():
            return repo
        tmp = seed.with_name(seed.name + ".repo.part")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(seed, tmp)
        git(tmp, "init", "-q", "-b", "main")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "Initial commit")
        tmp.rename(repo)
        return repo


def git_seed(url: str, commit: str, cache: Path | None = None) -> Path:
    """A plain directory with the tree of `url` at `commit` (no .git). Blobless mirror, cached per repo."""
    if not url.startswith("https://github.com/") or not all(c.isalnum() for c in commit):
        raise ValueError("seed must be a GitHub https URL and a hex commit")
    cache = cache or cache_dir()
    name = url.removeprefix("https://github.com/").removesuffix(".git").replace("/", "__")
    with _guard:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:
        dest = cache / "seeds" / f"{name}@{commit[:12]}"
        if dest.exists():
            return dest
        mirror = cache / "git" / f"{name}.git"
        if not mirror.exists():
            mirror.parent.mkdir(parents=True, exist_ok=True)
            git(mirror.parent, "clone", "-q", "--bare", "--filter=blob:none", url, mirror.name)
        tmp = dest.with_name(dest.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        archive = subprocess.run(["git", "archive", "--format=tar", commit], cwd=mirror, check=True,
                                 capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive, check=True)
        tmp.rename(dest)
        return dest
