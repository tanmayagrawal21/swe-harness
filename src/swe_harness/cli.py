"""Command line: validate a workflow spec, or run the benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import spec
from .bench import ROOT, run_bench


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="swe-harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="load and check workflow specs")
    v.add_argument("workflows", nargs="+", type=Path)

    b = sub.add_parser("bench", help="run workflow variants over the benchmark")
    b.add_argument("--workflows", nargs="+", type=Path,
                   default=[ROOT / "workflows" / "reference.yaml", *sorted((ROOT / "workflows" / "variants").glob("*.yaml"))])
    b.add_argument("--executor", default="scripted", choices=["scripted", "claude", "codex", "opencode"])
    b.add_argument("--tasks", nargs="*", help="task ids (default: all)")
    b.add_argument("--out", type=Path)
    b.add_argument("--jobs", type=int, default=4)
    b.add_argument("--whip-seconds", type=float, help="override every whip threshold (dry runs use 0.3)")
    b.add_argument("--max-budget-usd", type=float, default=1.0, help="claude executor: cap per agent call")
    b.add_argument("--model", default="", help="claude executor: one model for every role")
    b.add_argument("--require-zero-bypass", default="reference",
                   help="exit non-zero if this variant has any gate-bypass merge ('' to disable)")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        for p in a.workflows:
            wf = spec.load(p)
            print(f"ok  {wf.name}: gates={wf.gates} merger={wf.merge.merger} requires={wf.merge.requires}")
        return 0

    if a.executor != "scripted" and not a.tasks:
        print("live executors spend real tokens: pass --tasks explicitly", file=sys.stderr)
        return 2
    whip = a.whip_seconds if a.whip_seconds is not None else (0.3 if a.executor == "scripted" else None)
    opts = {"max_budget_usd": a.max_budget_usd, "model_override": a.model} if a.executor == "claude" else {}
    res = run_bench(a.workflows, a.executor, a.out, a.tasks, whip, a.jobs, opts)
    print((Path(res["out"]) / "report.md").read_text())
    print(f"results: {res['out']}")
    gate = a.require_zero_bypass
    if gate and gate in res["results"] and res["results"][gate]["summary"]["gate_bypass_merges"]:
        print(f"FAIL: {gate} has gate-bypass merges", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
