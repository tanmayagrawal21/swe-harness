"""A local, offline forge: git repo + PR metadata + append-only event log. Nothing is ever pushed.

The forge records facts (head SHAs, CI results, merges and whether main was an ancestor at merge time).
The scorer replays these facts; it never trusts the engine's own judgement.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Harness Agent", "GIT_AUTHOR_EMAIL": "agent@example.com",
    "GIT_COMMITTER_NAME": "Harness Agent", "GIT_COMMITTER_EMAIL": "agent@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd: str | Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, **GIT_ENV}
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def remove_worktree(repo: Path, wt: Path) -> None:
    """Remove a worktree this harness created. Scratch files are discarded first; never --force."""
    if git(wt, "status", "--porcelain", "--ignored", check=False):
        git(wt, "reset", "-q", "--hard")
        git(wt, "clean", "-qfdx")
    git(repo, "worktree", "remove", str(wt))
    git(repo, "worktree", "prune")


# Test subprocesses must not leave bytecode behind in checkouts.
PY_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.t0 = time.monotonic()

    def emit(self, type_: str, **data) -> dict:
        ev = {"t": round(time.monotonic() - self.t0, 4), "type": type_, **data}
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps(ev, sort_keys=True) + "\n")
        return ev

    def read(self) -> list[dict]:
        return read_events(self.path)


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    branch: str
    base: str = "main"
    merged_sha: str | None = None
    comments: list[dict] = field(default_factory=list)


class LocalForge:
    def __init__(self, root: Path, log: EventLog):
        self.root = root
        self.repo = root / "repo"
        self.wt_dir = root / "worktrees"
        self.log = log
        self.prs: dict[int, PullRequest] = {}
        self._ci: dict[str, bool] = {}
        self._lock = threading.Lock()

    # -- setup -------------------------------------------------------------------------------------
    def init_from(self, seed: Path, message: str = "Initial commit") -> str:
        shutil.copytree(seed, self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        git(self.repo, "checkout", "-q", "--detach")  # branches are moved only via worktrees
        self.wt_dir.mkdir(parents=True, exist_ok=True)
        return self.head("main")

    def head(self, ref: str) -> str:
        return git(self.repo, "rev-parse", ref)

    def commit_overlay(self, branch: str, overlay: Path, message: str, start: str = "main") -> str:
        """Copy overlay files onto `branch` (created from `start` if missing) and commit."""
        with self._lock:
            wt = self.worktree(branch if self._branch_exists(branch) else start, detach=True)
            try:
                shutil.copytree(overlay, wt, dirs_exist_ok=True)
                git(wt, "add", "-A")
                git(wt, "commit", "-q", "-m", message)
                sha = git(wt, "rev-parse", "HEAD")
                git(self.repo, "branch", "-f", branch, sha)
                return sha
            finally:
                self.remove_worktree(wt)

    def _branch_exists(self, branch: str) -> bool:
        return bool(git(self.repo, "branch", "--list", branch))

    # -- worktrees ---------------------------------------------------------------------------------
    def worktree(self, ref: str, detach: bool = True, label: str = "wt") -> Path:
        wt = self.wt_dir / f"{label}-{uuid.uuid4().hex[:8]}"  # unique: parallel agents never collide
        if detach:
            git(self.repo, "worktree", "add", "-q", "--detach", str(wt), ref)
        else:
            git(self.repo, "worktree", "add", "-q", str(wt), ref)
        return wt

    def remove_worktree(self, wt: Path) -> None:
        remove_worktree(self.repo, wt)

    # -- PRs ---------------------------------------------------------------------------------------
    def open_pr(self, title: str, body: str, branch: str) -> PullRequest:
        n = len(self.prs) + 1
        pr = PullRequest(n, title, body, branch)
        self.prs[n] = pr
        self.log.emit("pr_opened", pr=n, title=title, branch=branch, head=self.head(branch),
                      files=self.changed_files(n))
        return pr

    def pr_head(self, n: int) -> str:
        return self.head(self.prs[n].branch)

    def changed_files(self, n: int) -> list[str]:
        pr = self.prs[n]
        out = git(self.repo, "diff", "--name-only", f"{pr.base}...{pr.branch}")
        return [f for f in out.splitlines() if f]

    def comment(self, n: int, role: str, text: str) -> None:
        self.prs[n].comments.append({"role": role, "text": text})
        self.log.emit("comment", pr=n, role=role, text=text)

    def main_is_ancestor(self, sha: str) -> bool:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", "main", sha], cwd=self.repo)
        return r.returncode == 0

    # -- CI ----------------------------------------------------------------------------------------
    def run_ci(self, sha: str) -> bool:
        with self._lock:
            if sha in self._ci:
                return self._ci[sha]
        wt = self.worktree(sha, label="ci")
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=wt,
                               env=PY_ENV, capture_output=True, text=True)
            green = r.returncode == 0
        finally:
            self.remove_worktree(wt)
        with self._lock:
            self._ci[sha] = green
        self.log.emit("ci", sha=sha, green=green)
        return green

    # -- merge -------------------------------------------------------------------------------------
    def merge(self, n: int, sha: str, actor: str, subject: str | None, body: str | None) -> str:
        """Squash-merge `sha` into main. subject/body None = default squash message (all commit messages)."""
        pr = self.prs[n]
        if self.pr_head(n) != sha:
            raise RuntimeError(f"PR #{n} head moved; refusing to merge {sha[:8]}")
        ancestor = self.main_is_ancestor(sha)
        main_before = self.head("main")
        if subject is None:
            msgs = git(self.repo, "log", "--format=* %B", f"main..{sha}")
            subject, body = f"{pr.title} (#{n})", msgs
        with self._lock:
            wt = self.worktree("main", label="merge")
            try:
                git(wt, "merge", "--squash", sha)
                git(wt, "commit", "-q", "-m", subject, "-m", body or "")
                new_main = git(wt, "rev-parse", "HEAD")
                git(self.repo, "branch", "-f", "main", new_main)
            finally:
                self.remove_worktree(wt)
        pr.merged_sha = sha
        self.log.emit("merge", pr=n, sha=sha, actor=actor, main_before=main_before, main_after=new_main,
                      main_ancestor=ancestor, files=self.changed_files(n))
        return new_main
