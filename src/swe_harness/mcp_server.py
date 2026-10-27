"""MCP server (stdio, JSON-RPC 2.0, stdlib only) so a conversational agent can drive the harness.

Built for speed: no SDK import, no package manager on the start path, and every tool returns in
milliseconds. Benchmarks run as detached processes; tools only start them and read small files.
The server can start, watch and explain runs, and propose variants. It cannot merge, edit the reference
workflow or start a paid run without an explicit `confirm_live`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # computed here: importing bench would slow startup
BENCH = ROOT / "bench"
RUNS = ROOT / "runs"
VARIANTS = ROOT / "workflows" / "variants"
MAX_TEXT = 4000
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NOTABLE = {"whip_silent", "respawn", "agent_dead", "agent_error", "merge", "round_cap", "author_gave_up", "stuck"}
_procs: dict[str, subprocess.Popen] = {}


class ToolError(Exception):
    pass


# -- helpers -------------------------------------------------------------------------------------------
def _cap(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"\n... ({len(text) - MAX_TEXT} chars cut)"


def _run_dir(run_id: str) -> Path:
    if not NAME.match(run_id or ""):
        raise ToolError("invalid run_id")
    d = RUNS / run_id
    if not d.is_dir():
        raise ToolError(f"no run {run_id!r}")
    return d


def _workflow_path(p: str) -> Path:
    path = (ROOT / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    if ROOT not in path.parents or path.suffix not in (".yaml", ".yml"):
        raise ToolError(f"workflow must be a .yaml file inside the harness repo: {p}")
    return path


def _alive(run_id: str, pid: int) -> bool:
    proc = _procs.get(run_id)
    if proc is not None:
        return proc.poll() is None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _redactor():
    from .privacy import load_terms, match_terms

    terms = load_terms(BENCH / "private_profile" / "terms.txt")

    def redact(text: str) -> str:
        for i in match_terms(text, terms):
            text = re.sub(re.escape(terms[i - 1]), f"[private term #{i}]", text, flags=re.I)
        return text if not match_terms(text, terms) else "[redacted: contains private data]"

    return redact


# -- tools ---------------------------------------------------------------------------------------------
def validate_workflow(paths: list[str]) -> str:
    from . import spec

    out = []
    for p in paths:
        try:
            wf = spec.load(_workflow_path(p))
            out.append(f"ok {wf.name}: gates={wf.gates} merger={wf.merge.merger} requires={wf.merge.requires} "
                       f"squash={'explicit' if wf.merge.squash else 'default'} round_cap={wf.round_cap}")
        except (spec.SpecError, OSError, KeyError, TypeError) as e:
            out.append(f"INVALID {p}: {e}")
    return "\n".join(out)


def list_workflows() -> str:
    files = [ROOT / "workflows" / "reference.yaml", *sorted(VARIANTS.glob("*.y*ml"))]
    return "\n".join(str(f.relative_to(ROOT)) for f in files)


def list_tasks() -> str:
    from .tasks import load_tasks

    return "\n".join(f"{t.id} [{t.kind}] {t.title}" for t in load_tasks(BENCH / "tasks"))


def run_bench(workflows: list[str] | None = None, tasks: list[str] | None = None, executor: str = "scripted",
              max_budget_usd: float = 0.5, model: str = "", confirm_live: bool = False) -> str:
    if executor not in ("scripted", "claude", "codex", "opencode"):
        raise ToolError("executor must be scripted, claude, codex or opencode")
    if executor != "scripted":
        if not tasks:
            raise ToolError("live runs need an explicit task list")
        if not confirm_live:
            raise ToolError(f"live run spends real money (up to ${max_budget_usd} per agent call). Ask the owner, "
                            "then call again with confirm_live=true.")
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid() % 1000:03d}{len(_procs):02d}"
    out = RUNS / run_id
    out.mkdir(parents=True)
    cmd = [sys.executable, "-m", "swe_harness.cli", "bench", "--out", str(out), "--executor", executor]
    if workflows:
        cmd += ["--workflows", *[str(_workflow_path(w)) for w in workflows]]
    if tasks:
        if not all(NAME.match(t) for t in tasks):
            raise ToolError("invalid task id")
        cmd += ["--tasks", *tasks]
    if executor == "claude":
        cmd += ["--max-budget-usd", str(float(max_budget_usd))] + (["--model", model] if model else [])
    log = (out / "log.txt").open("w")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)
    _procs[run_id] = proc
    (out / "meta.json").write_text(json.dumps({"pid": proc.pid, "started": time.time(), "executor": executor,
                                               "workflows": workflows or "all", "tasks": tasks or "all"}))
    return f"started run {run_id} (executor={executor}). Check it with run_status."


def run_status(run_id: str, since: float = 0.0) -> str:
    d = _run_dir(run_id)
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    done = (d / "results.json").exists()
    eps, notable = 0, []
    for ev_file in d.glob("*/*/events.jsonl"):
        variant, task = ev_file.parent.parent.name, ev_file.parent.name
        for line in ev_file.read_text().splitlines():
            e = json.loads(line)
            if e["type"] == "episode_end":
                eps += 1
            if e["type"] in NOTABLE and e["t"] > since:
                notable.append(f"{variant}/{task} t={e['t']}: {e['type']} {e.get('role', e.get('actor', ''))}")
    state = "done" if done else ("running" if meta and _alive(run_id, meta["pid"]) else "failed")
    lines = [f"run {run_id}: {state}, {eps} episode(s) finished, "
             f"{round(time.time() - meta.get('started', time.time()))}s since start"]
    if state == "failed":
        lines.append("log tail:\n" + "\n".join((d / "log.txt").read_text().splitlines()[-8:]))
    lines += notable[-15:]
    return _cap("\n".join(lines))


def get_report(run_id: str, detail: str = "summary") -> str:
    d = _run_dir(run_id)
    if not (d / "results.json").exists():
        raise ToolError("run not finished; use run_status")
    results = json.loads((d / "results.json").read_text())
    if detail == "full":
        return _cap((d / "report.md").read_text())
    keys = ["bugs_caught", "unsafe_blocked", "leaks_blocked", "gate_bypass_merges", "clean_merged",
            "faults_recovered", "tokens_per_merged_pr", "cost_per_merged_pr"]
    lines = ["variant | " + " | ".join(keys)]
    for name, r in results.items():
        s = r["summary"]
        cells = [f"{s['faults_recovered']}/{s['faults']}" if k == "faults_recovered" else str(s.get(k)) for k in keys]
        lines.append(f"{name} | " + " | ".join(cells))
    bad = [n for n, r in results.items() if n == "reference" and r["summary"]["gate_bypass_merges"]]
    if bad:
        lines.append("ALERT: reference workflow has gate-bypass merges")
    lines.append(f"full report: {(d / 'report.md').relative_to(ROOT)}")
    return "\n".join(lines)


def explain_episode(run_id: str, variant: str, task: str) -> str:
    d = _run_dir(run_id)
    if not (NAME.match(variant) and NAME.match(task)):
        raise ToolError("invalid variant or task")
    f = d / variant / task / "events.jsonl"
    if not f.exists():
        raise ToolError("no such episode")
    redact = _redactor()  # comments may quote leaked values; never echo them
    out = []
    for line in f.read_text().splitlines():
        e = json.loads(line)
        t, k = e["t"], e["type"]
        sha = (e.get("sha") or "")[:8]
        if k == "verdict":
            out.append(f"{t} verdict {e['role']} {'APPROVE' if e['approved'] else 'BLOCK'} {sha}"
                       + ("" if e["valid"] else " (unparseable or wrong SHA: fail closed)"))
        elif k == "comment":
            first = redact(e["text"]).strip().splitlines()[1:3]
            if first:
                out.append(f"{t}   {e['role']}: " + " / ".join(x.strip() for x in first)[:200])
        elif k == "agent_done":
            out.append(f"{t} {e['role']} done ({e['purpose']}, {e['input_tokens'] + e['output_tokens']} tok)")
        elif k in ("ci", "head", "merge", "gates_dispatched"):
            extra = {"ci": f"green={e.get('green')}", "head": e.get("purpose", ""),
                     "merge": f"by {e.get('actor')} ancestor={e.get('main_ancestor')}",
                     "gates_dispatched": ",".join(e.get("gates", []))}[k]
            out.append(f"{t} {k} {sha} {extra}")
        elif k not in ("pr_opened", "episode_start"):
            out.append(f"{t} {k} {e.get('role', '')}".rstrip())
    return _cap("\n".join(out))


def list_runs(limit: int = 10) -> str:
    runs = sorted((p for p in RUNS.glob("*") if p.is_dir()), reverse=True)[: max(1, min(int(limit), 50))]
    return "\n".join(f"{p.name} {'done' if (p / 'results.json').exists() else 'not finished'}" for p in runs) \
        or "no runs yet"


def propose_variant(name: str, overrides: dict, base: str = "../reference.yaml") -> str:
    """Write workflows/variants/<name>.yaml extending a base. Never edits an existing file."""
    import yaml

    from . import spec

    if not NAME.match(name) or name == "reference":
        raise ToolError("invalid variant name")
    path = VARIANTS / f"{name}.yaml"
    if path.exists():
        raise ToolError(f"{path.relative_to(ROOT)} exists; pick a new name")
    if not isinstance(overrides, dict):
        raise ToolError("overrides must be an object")
    _workflow_path(str((VARIANTS / base).resolve()))
    body = {"extends": base, "name": name, **{k: v for k, v in overrides.items() if k not in ("extends", "name")}}
    text = yaml.safe_dump(body, sort_keys=False)
    path.write_text(text)
    try:
        wf = spec.load(path)
    except Exception as e:  # invalid proposal: remove it, report why
        path.unlink()
        raise ToolError(f"invalid variant, not written: {e}") from e
    return f"wrote {path.relative_to(ROOT)} (gates={wf.gates}, merger={wf.merge.merger})\n{text}"


S, ARR, NUM, BOOL, OBJ = ({"type": "string"}, {"type": "array", "items": {"type": "string"}}, {"type": "number"},
                          {"type": "boolean"}, {"type": "object"})
TOOLS = {
    "validate_workflow": (validate_workflow, "Load and check workflow YAML files.", {"paths": ARR}, ["paths"]),
    "list_workflows": (list_workflows, "List the reference workflow and its variants.", {}, []),
    "list_tasks": (list_tasks, "List benchmark tasks with their trap kind.", {}, []),
    "run_bench": (run_bench, "Start a benchmark run in the background and return its run_id at once. Live "
                  "executors need explicit tasks and confirm_live=true after the owner agreed to the cost.",
                  {"workflows": ARR, "tasks": ARR, "executor": {**S, "enum": ["scripted", "claude", "codex",
                                                                                "opencode"]},
                   "max_budget_usd": NUM, "model": S, "confirm_live": BOOL}, []),
    "run_status": (run_status, "Progress of a run plus notable events (whips, merges, round caps) after `since`.",
                   {"run_id": S, "since": NUM}, ["run_id"]),
    "get_report": (get_report, "Metrics table of a finished run. detail=full returns the markdown report.",
                   {"run_id": S, "detail": {**S, "enum": ["summary", "full"]}}, ["run_id"]),
    "explain_episode": (explain_episode, "Condensed, redacted timeline of one task in one variant.",
                        {"run_id": S, "variant": S, "task": S}, ["run_id", "variant", "task"]),
    "list_runs": (list_runs, "Most recent runs.", {"limit": NUM}, []),
    "propose_variant": (propose_variant, "Write a NEW variant that extends a base workflow with overrides "
                        "(e.g. gates, merge, whips). Validated; never overwrites.",
                        {"name": S, "overrides": OBJ, "base": S}, ["name", "overrides"]),
}


# -- JSON-RPC ------------------------------------------------------------------------------------------
def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None  # notification
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "swe-harness", "version": "0.1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p,
                                                                          "required": r}}
                            for n, (_, d, p, r) in TOOLS.items()]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        try:
            text, err = TOOLS[name][0](**args), False
        except (ToolError, TypeError, ValueError, OSError) as e:
            text, err = f"error: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
