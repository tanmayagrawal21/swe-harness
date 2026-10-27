"""Benchmark tasks: a pre-written PR against the seed repo, plus ground-truth labels kept outside the repo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

KINDS = {"clean", "bug", "leak", "unsafe"}


@dataclass
class Task:
    id: str
    dir: Path
    kind: str  # ground truth for the first PR: clean | bug | leak | unsafe
    title: str
    issue: str
    pr_title: str
    pr_body: str
    pr_message: str
    fix_message: str = ""
    faults: list[dict] = field(default_factory=list)  # [{role, round}] -> that agent goes silent once
    main_move: dict | None = None  # {after_round, message}: an unrelated commit lands on main
    seed: dict | None = None  # {git, commit}: start from an upstream repo instead of bench/seed
    oracle: str = "test"  # test: hidden_test.py decides; label: the dataset's published label decides
    ci: str = "run"  # skip: the upstream suite needs its own environment; CI is recorded as skipped
    review_note: str = ""  # a benchmark condition the gates are told (e.g. tests are evaluated separately)
    pr_reverse: bool = False  # apply pr.patch in reverse (e.g. a security fix reverted)
    pr_exclude: list[str] = field(default_factory=list)  # path globs left out of pr.patch

    @property
    def pr_dir(self) -> Path:
        return self.dir / "pr"

    @property
    def pr_patch(self) -> Path | None:
        p = self.dir / "pr.patch"
        return p if p.exists() else None

    @property
    def fix_dir(self) -> Path | None:
        d = self.dir / "fix"
        return d if d.is_dir() else None

    @property
    def main_move_dir(self) -> Path:
        return self.dir / "main_move"

    @property
    def hidden_test(self) -> Path | None:
        p = self.dir / "hidden_test.py"
        return p if p.exists() else None


def load_task(d: Path) -> Task:
    data = yaml.safe_load((d / "task.yaml").read_text())
    kind = data["kind"]
    if kind not in KINDS:
        raise ValueError(f"{d}: kind must be one of {sorted(KINDS)}")
    pr = data["pr"]
    t = Task(id=data["id"], dir=d, kind=kind, title=data["title"], issue=data["issue"], pr_title=pr["title"],
             pr_body=pr.get("body", ""), pr_message=pr["commit_message"],
             fix_message=(data.get("fix") or {}).get("commit_message", "Address review"),
             faults=list(data.get("faults") or []), main_move=data.get("main_move"), seed=data.get("seed"),
             oracle=data.get("oracle", "test"), ci=data.get("ci", "run"), pr_reverse=bool(pr.get("reverse")),
             pr_exclude=list(pr.get("exclude") or []), review_note=data.get("review_note", ""))
    if t.oracle not in ("test", "label") or t.ci not in ("run", "skip"):
        raise ValueError(f"{d}: oracle must be test|label and ci run|skip")
    if kind in ("bug", "unsafe") and t.oracle == "test" and t.hidden_test is None:
        raise ValueError(f"{d}: {kind} tasks need hidden_test.py")
    return t


def load_tasks(root: Path, only: list[str] | None = None) -> list[Task]:
    tasks = [load_task(p.parent) for p in sorted(root.glob("*/task.yaml"))]
    return [t for t in tasks if not only or t.id in only]
