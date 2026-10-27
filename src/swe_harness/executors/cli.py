"""Generic CLI executor for other agent tools (Codex, OpenCode). EXPERIMENTAL: untested against live tools.

A command template gets {prompt} (role prompt + brief) and {model}. Each stdout line is a heartbeat.
Usage is not parsed; cost metrics for these executors read as zero until an adapter parses their output.
"""

from __future__ import annotations

import selectors
import subprocess

from .base import AgentCall, AgentResult, Executor

PRESETS = {
    "codex": ["codex", "exec", "--full-auto", "{prompt}"],
    "opencode": ["opencode", "run", "{prompt}"],
}


class CLIExecutor(Executor):
    def __init__(self, template: list[str], name: str = "cli"):
        self.template = template
        self.name = name

    @classmethod
    def preset(cls, name: str, **_):
        return cls(PRESETS[name], name)

    def command(self, call: AgentCall) -> list[str]:
        prompt = f"{call.role.prompt}\n\n{call.brief}"
        return [a.replace("{prompt}", prompt).replace("{model}", call.role.model) for a in self.template]

    def run(self, call, heartbeat, cancel) -> AgentResult:
        proc = subprocess.Popen(self.command(call), cwd=call.cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        lines: list[str] = []
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
                lines.append(line)
        finally:
            sel.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        return AgentResult(text="".join(lines[-200:]), ok=proc.returncode == 0)
