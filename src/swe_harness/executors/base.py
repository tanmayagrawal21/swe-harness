"""Executor interface plus whip supervision. Executors run one agent call and exit (on-demand agents)."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..spec import Role, Whip


@dataclass
class AgentCall:
    role: Role
    brief: str  # the user message: task, SHA, rules block
    cwd: Path  # the agent's own worktree
    pr: int
    sha: str = ""
    round: int = 1
    purpose: str = ""  # author: fix | merge_main; gate: review; observer: observe
    context: dict = field(default_factory=dict)  # harness facts for executors (paths, base ref, task id)


@dataclass
class AgentResult:
    text: str
    ok: bool = True
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    synthetic_usage: bool = False  # True when usage is estimated (dry mode), not reported by a model


Heartbeat = Callable[[], None]


class Executor(ABC):
    name = "base"

    @abstractmethod
    def run(self, call: AgentCall, heartbeat: Heartbeat, cancel: threading.Event) -> AgentResult:
        """Run one agent to completion. Call heartbeat() on every sign of progress; stop when cancel is set."""


class HangOnce(Executor):
    """Fault injection: the first attempt goes silent until the whip cancels it."""

    name = "fault-hang"

    def __init__(self, inner: Executor):
        self.inner = inner
        self.fired = False

    def run(self, call, heartbeat, cancel):
        if not self.fired:
            self.fired = True
            while not cancel.wait(0.01):
                pass
            return AgentResult(text="(cancelled while silent)", ok=False)
        return self.inner.run(call, heartbeat, cancel)


def run_supervised(executor: Executor, call: AgentCall, whip: Whip | None, emit) -> AgentResult:
    """Run an agent under its role's whip: silence beyond the threshold cancels and respawns it."""
    attempt = 0
    while True:
        last = [time.monotonic()]
        cancel = threading.Event()
        box: list[AgentResult | BaseException | None] = [None]

        def beat() -> None:
            last[0] = time.monotonic()

        def target() -> None:
            try:
                box[0] = executor.run(call, beat, cancel)
            except BaseException as e:  # surfaced below; an executor crash is a failed call
                box[0] = e

        th = threading.Thread(target=target, daemon=True)
        th.start()
        poll = min(0.05, whip.silent_seconds / 5) if whip else 0.5
        silent = False
        while th.is_alive():
            th.join(poll)
            if whip and th.is_alive() and time.monotonic() - last[0] > whip.silent_seconds:
                silent = True
                emit("whip_silent", role=call.role.name, pr=call.pr, round=call.round, attempt=attempt)
                cancel.set()
                th.join(5)
                break
        if not silent:
            r = box[0]
            if isinstance(r, BaseException):
                emit("agent_error", role=call.role.name, pr=call.pr, error=type(r).__name__, msg=str(r)[:300])
                return AgentResult(text=f"executor error: {type(r).__name__}", ok=False)
            assert r is not None
            emit("agent_done", role=call.role.name, pr=call.pr, round=call.round, attempt=attempt,
                 purpose=call.purpose, ok=r.ok, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                 cost_usd=r.cost_usd, synthetic_usage=r.synthetic_usage)
            return r
        if attempt >= whip.max_restarts:
            emit("agent_dead", role=call.role.name, pr=call.pr, round=call.round)
            return AgentResult(text="agent silent; restarts exhausted", ok=False)
        attempt += 1
        emit("respawn", role=call.role.name, pr=call.pr, round=call.round, attempt=attempt)
