"""Run workflow variants over the benchmark tasks and write a comparison report."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from . import spec
from .engine import Episode
from .executors import make_executor
from .score import EpisodeScore, Policy, aggregate, score_episode
from .tasks import Task, load_tasks

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"
REFERENCE = ROOT / "workflows" / "reference.yaml"
COLUMNS = [
    ("bugs_caught", "bugs caught"), ("unsafe_blocked", "unsafe blocked"), ("leaks_blocked", "leaks blocked"),
    ("gate_bypass_merges", "gate-bypass merges"), ("clean_merged", "clean merged"),
    ("merged_prs", "merged PRs"), ("faults_recovered", "faults recovered"), ("mean_detect_s", "detect s"),
    ("mean_recover_s", "recover s"), ("tokens_per_merged_pr", "tokens/merged PR"),
    ("cached_tokens_per_merged_pr", "cached tokens/merged PR"),
    ("cost_per_merged_pr", "USD/merged PR"),
]


def run_variant(wf_path: Path, tasks: list[Task], executor: str, out: Path, policy: Policy,
                whip_seconds: float | None, jobs: int, executor_opts: dict | None = None,
                terms: Path | None = None) -> list[EpisodeScore]:
    wf = spec.load(wf_path)
    terms = terms or BENCH / "private_profile" / "terms.txt"

    def one(task: Task) -> EpisodeScore:
        ep_dir = out / wf.name / task.id
        ep = Episode(wf, task, make_executor(executor, **(executor_opts or {})), ep_dir, BENCH / "seed", terms,
                     whip_seconds=whip_seconds)
        ep.run()
        return score_episode(ep_dir, task, ep.terms, policy)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, tasks))


def run_bench(variants: list[Path], executor: str = "scripted", out: Path | None = None,
              only: list[str] | None = None, whip_seconds: float | None = None, jobs: int = 4,
              executor_opts: dict | None = None, task_root: Path | None = None) -> dict:
    """task_root: a task source directory with tasks/ and private_profile/terms.txt (default: bench/)."""
    out = out or ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    policy = Policy.from_workflow(spec.load(REFERENCE))
    src = (task_root or BENCH).resolve()
    tasks = load_tasks(src / "tasks", only)
    terms = src / "private_profile" / "terms.txt"
    results = {}
    for v in variants:
        scores = run_variant(v, tasks, executor, out, policy, whip_seconds, jobs, executor_opts, terms)
        name = spec.load(v).name
        results[name] = {"summary": aggregate(scores), "episodes": [asdict(s) for s in scores]}
    (out / "results.json").write_text(json.dumps(results, indent=2))
    (out / "report.md").write_text(report(results, executor))
    return {"out": str(out), "results": results}


def report(results: dict, executor: str) -> str:
    synthetic = any(r["summary"]["synthetic_usage"] for r in results.values())
    lines = [
        "# Benchmark results", "",
        f"Executor: `{executor}`. Policy: every merge is judged against the reference merge gate.",
    ]
    if synthetic:
        lines.append("Dry run: gate detection is simulated and token counts are synthetic. These numbers "
                     "validate the harness, not a model.")
    lines += ["", "| variant | " + " | ".join(c[1] for c in COLUMNS) + " |",
              "|---|" + "---|" * len(COLUMNS)]
    for name, r in results.items():
        s = r["summary"]
        cells = [str(s[k]) if s[k] is not None else "-" for k, _ in COLUMNS]
        cells[COLUMNS.index(("faults_recovered", "faults recovered"))] = f"{s['faults_recovered']}/{s['faults']}"
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Per task", "", "| variant | task | kind | merged | defect on main | leaked | bypass |",
              "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        for e in r["episodes"]:
            leaked = ", ".join(k for k, v in e["leaks"].items() if v) or "no"
            bypass = "; ".join(r2 for v in e["violations"] for r2 in v["reasons"]) or "-"
            lines.append(f"| {name} | {e['task']} | {e['kind']} | {e['merged']} | {e['defect_on_main']} | "
                         f"{leaked} | {bypass} |")
    return "\n".join(lines) + "\n"
