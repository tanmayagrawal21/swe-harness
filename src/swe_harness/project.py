"""Build a repository step by step: an ordered list of issues, each one a full gated episode whose author writes
the PR, and each starting from the main the previous merge produced. Every step carries a hidden acceptance
test; after the last step, all of them run on the final main, so a later step that broke an earlier one shows.

project.yaml:  name, steps: [task ids in order], optional terms (default: the benchmark's fictional terms).
Layout:        seed/ (the starting tree, may hold only a README), tasks/<id>/{task.yaml, hidden_test.py, solution/}
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from . import spec
from .bench import BENCH, REFERENCE
from .engine import Episode
from .executors import make_executor
from .executors.scripted import defect_present
from .forge import git, remove_worktree
from .score import EpisodeScore, Policy, score_episode
from .tasks import Task, load_task


@dataclass
class Project:
    name: str
    dir: Path
    steps: list[Task]
    terms: Path

    @property
    def seed(self) -> Path:
        return self.dir / "seed"


def load_project(d: Path) -> Project:
    d = d.resolve()
    data = yaml.safe_load((d / "project.yaml").read_text())
    steps = [load_task(d / "tasks" / tid) for tid in data["steps"]]
    for t in steps:
        if not t.writes or t.kind != "feature":
            raise ValueError(f"{t.dir}: project steps are feature tasks the author writes (no pr/ or pr.patch)")
    terms = d / data["terms"] if data.get("terms") else BENCH / "private_profile" / "terms.txt"
    return Project(data["name"], d, steps, terms)


def acceptance(repo: Path, steps: list[Task]) -> dict[str, bool]:
    """Each step's hidden test on the repo's main: True = passes."""
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "main"
        git(repo, "worktree", "add", "-q", "--detach", str(wt), "main")
        try:
            return {t.id: not defect_present(wt, t) for t in steps}
        finally:
            remove_worktree(repo, wt)


def build(project_dir: Path, out: Path, workflow: Path = REFERENCE, executor: str = "scripted",
          executor_opts: dict | None = None, whip_seconds: float | None = None, keep_going: bool = False) -> dict:
    """Run the steps in order. Stops at the first step not delivered (merged and accepted) unless keep_going."""
    p, wf = load_project(project_dir), spec.load(workflow)
    policy = Policy.from_workflow(spec.load(REFERENCE))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prev: Path | None = None
    scores: list[EpisodeScore] = []
    for i, task in enumerate(p.steps, 1):
        ep_dir = out / f"{i:02d}-{task.id}"
        ep = Episode(wf, task, make_executor(executor, **(executor_opts or {})), ep_dir, p.seed, p.terms,
                     whip_seconds=whip_seconds, start=prev)
        ep.run()
        s = score_episode(ep_dir, task, ep.terms, policy)
        scores.append(s)
        prev = ep_dir / "repo"
        if not (s.merged and not s.defect_on_main) and not keep_going:
            break
    final = acceptance(prev, p.steps) if prev else {}
    delivered = [s.task for s in scores if s.merged and not s.defect_on_main]
    result = {
        "project": p.name, "workflow": wf.name, "executor": executor, "steps": len(p.steps),
        "attempted": len(scores), "delivered": len(delivered),
        "final_acceptance": final, "regressions": [t for t in delivered if not final.get(t)],
        "gate_bypass_merges": sum(len(s.violations) for s in scores),
        "leaks": sum(s.leaked for s in scores),
        "tokens": sum(s.tokens for s in scores), "cached_tokens": sum(s.cache_read_tokens for s in scores),
        "cost_usd": round(sum(s.cost_usd for s in scores), 4),
        "synthetic_usage": any(s.synthetic_usage for s in scores),
        "final_repo": str(prev) if prev else None,
        "episodes": [asdict(s) for s in scores],
    }
    (out / "results.json").write_text(json.dumps(result, indent=2))
    (out / "report.md").write_text(report(result))
    return result


def report(r: dict) -> str:
    lines = [f"# Build: {r['project']}", "",
             f"Workflow `{r['workflow']}`, executor `{r['executor']}`. Every merge is judged against the "
             "reference merge gate; every step's acceptance test is re-run on the final main.", ""]
    if r["synthetic_usage"]:
        lines += ["Dry run: the author commits each step's known-good solution and gate detection is simulated. "
                  "This validates the harness, not a model.", ""]
    acc = sum(r["final_acceptance"].values())
    lines += [f"- Steps delivered: **{r['delivered']}/{r['steps']}** (attempted {r['attempted']})",
              f"- Acceptance on final main: **{acc}/{r['steps']}**; regressions: {r['regressions'] or 'none'}",
              f"- Gate-bypass merges: {r['gate_bypass_merges']}; episodes with leaks: {r['leaks']}",
              f"- Tokens: {r['tokens']} fresh, {r['cached_tokens']} cached; USD {r['cost_usd']}",
              f"- Final repo: `{r['final_repo']}`", "",
              "| step | merged | accepted then | rounds | agent calls | gates | USD |", "|---|---|---|---|---|---|---|"]
    for e in r["episodes"]:
        lines.append(f"| {e['task']} | {e['merged']} | {e['merged'] and not e['defect_on_main']} | {e['rounds']} | "
                     f"{e['agent_calls']} | {', '.join(e['gates_dispatched']) or '-'} | {e['cost_usd']} |")
    return "\n".join(lines) + "\n"
