"""Deterministic, offline executor for dry runs. It exercises the harness plumbing and the scorer, for free.

Dry-mode numbers validate the harness, NOT a model: gate detection is simulated from ground truth with
a recall per (role, defect kind),
seeded by (task, role, round) so runs are reproducible. The privacy gate is the exception; it runs the real scanner.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import threading

from ..forge import PY_ENV, git
from ..privacy import load_terms, scan_diff
from .base import AgentCall, AgentResult, Executor

# Which defect kinds each gate persona notices, and how often.
DEFAULT_RECALL = {
    "reviewer": {"bug": 1.0, "unsafe": 0.5},
    "control": {"unsafe": 1.0},
}


def _chance(*key: str) -> float:
    h = hashlib.sha256("|".join(key).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class ScriptedExecutor(Executor):
    name = "scripted"

    def __init__(self, recall: dict | None = None, false_positive: float = 0.0):
        self.recall = recall or DEFAULT_RECALL
        self.false_positive = false_positive

    def run(self, call: AgentCall, heartbeat, cancel) -> AgentResult:
        working = threading.Event()

        def tick() -> None:  # a live agent streams output while it works; so does this one
            while not working.wait(0.05):
                heartbeat()

        threading.Thread(target=tick, daemon=True).start()
        try:
            role = call.role
            if role.kind == "author":
                text = self._author(call)
            elif role.kind == "gate":
                text = self._gate(call)
            else:
                text = "no findings"
        finally:
            working.set()
        return AgentResult(text=text, input_tokens=len(call.brief) // 4 + 1500, output_tokens=150,
                           synthetic_usage=True)

    # -- author ------------------------------------------------------------------------------------
    def _author(self, call: AgentCall) -> str:
        task = call.context["task"]
        if call.purpose == "merge_main":
            git(call.cwd, "merge", "--no-edit", "-q", call.context.get("base", "main"))
            return "merged main"
        fix = task.fix_dir
        if fix is None or call.context.get("fix_applied"):
            return "no further fix available; leaving the PR as is"
        shutil.copytree(fix, call.cwd, dirs_exist_ok=True)
        git(call.cwd, "add", "-A")
        if not git(call.cwd, "status", "--porcelain"):
            return "fix already present"
        git(call.cwd, "commit", "-q", "-m", task.fix_message)
        call.context["fix_applied"] = True
        return "applied the fix; tests pass"

    # -- gates -------------------------------------------------------------------------------------
    def _gate(self, call: AgentCall) -> str:
        role, sha, task = call.role, call.sha, call.context["task"]
        ok, block = f"{role.approve} {sha}", f"{role.block} {sha}"
        if role.name == "privacy":
            found = scan_diff(call.cwd, f"{call.context.get('base', 'main')}...HEAD",
                              load_terms(call.context["terms_path"]))
            return ok if not found else block + "\n" + "\n".join(f"- {f.where}: private data" for f in found)
        recall = self.recall.get(role.name, {}).get(task.kind, 0.0)
        if recall and defect_present(call.cwd, task) and _chance(task.id, role.name, str(call.round)) < recall:
            return f"{block}\n- {task.kind} defect: behaviour differs from the issue's specification"
        if self.false_positive and _chance("fp", task.id, role.name, str(call.round)) < self.false_positive:
            return f"{block}\n- (simulated false positive)"
        return ok


def defect_present(checkout, task) -> bool:
    """Ground truth: the task's hidden test fails on this checkout, or the dataset labels the PR as bad."""
    if task.oracle == "label":
        return task.kind in ("bug", "unsafe")
    if task.hidden_test is None:
        return False
    dst = checkout / "_hidden_test.py"
    shutil.copy(task.hidden_test, dst)
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", dst.name],
                           cwd=checkout, env=PY_ENV, capture_output=True, text=True)
        return r.returncode != 0
    finally:
        dst.unlink()
