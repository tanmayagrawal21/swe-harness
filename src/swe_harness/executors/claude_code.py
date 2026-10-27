"""Claude Code executor: one headless `claude -p` process per agent call, streamed as stream-json.

Every stream line is a heartbeat for the whip. The final `result` line carries usage and cost.
User-level settings, memory and hooks are NOT loaded (`--setting-sources project,local`), so an agent never
sees the operator's private context.
"""

from __future__ import annotations

import json
import selectors
import shutil
import subprocess

from .base import AgentCall, AgentResult, Executor

GATE_DENY = ["Edit", "Write", "NotebookEdit", "Bash(git push*)", "Bash(git commit*)", "Bash(git merge*)"]


class ClaudeCodeExecutor(Executor):
    name = "claude"

    def __init__(self, binary: str = "claude", max_budget_usd: float = 1.0, model_override: str = ""):
        self.binary = binary
        self.max_budget_usd = max_budget_usd
        self.model_override = model_override

    def command(self, call: AgentCall) -> list[str]:
        role = call.role
        cmd = [self.binary, "-p", call.brief, "--output-format", "stream-json", "--verbose",
               "--system-prompt", role.prompt, "--setting-sources", "project,local",
               "--no-session-persistence", "--permission-mode", "acceptEdits",
               "--max-budget-usd", str(self.max_budget_usd)]
        model = self.model_override or role.model
        if model:
            cmd += ["--model", model]
        if role.tools:
            cmd += ["--allowedTools", *role.tools]
        if role.kind != "author":
            cmd += ["--disallowedTools", *GATE_DENY]
        return cmd

    def run(self, call, heartbeat, cancel) -> AgentResult:
        if not shutil.which(self.binary):
            raise FileNotFoundError(f"{self.binary} not on PATH")
        proc = subprocess.Popen(self.command(call), cwd=call.cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        final: dict | None = None
        try:
            while True:
                if cancel.is_set():
                    proc.kill()
                    return AgentResult(text="(cancelled)", ok=False)
                if not sel.select(timeout=0.2):
                    if proc.poll() is not None:
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                heartbeat()
                msg = parse_line(line)
                if msg and msg.get("type") == "result":
                    final = msg
        finally:
            sel.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        return result_from(final)


def parse_line(line: str) -> dict | None:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None


def result_from(final: dict | None) -> AgentResult:
    if not final:
        return AgentResult(text="(no result message)", ok=False)
    usage = final.get("usage") or {}
    tokens_in = sum(int(usage.get(k) or 0) for k in
                    ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return AgentResult(text=str(final.get("result") or ""), ok=not final.get("is_error", False),
                       input_tokens=tokens_in, output_tokens=int(usage.get("output_tokens") or 0),
                       cost_usd=float(final.get("total_cost_usd") or 0.0))
