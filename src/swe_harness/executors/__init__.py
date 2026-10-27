from .base import AgentCall, AgentResult, Executor, HangOnce, run_supervised

__all__ = ["AgentCall", "AgentResult", "Executor", "HangOnce", "run_supervised", "make_executor"]


def make_executor(name: str, **opts) -> Executor:
    if name == "scripted":
        from .scripted import ScriptedExecutor
        return ScriptedExecutor(**opts)
    if name == "claude":
        from .claude_code import ClaudeCodeExecutor
        return ClaudeCodeExecutor(**opts)
    if name in ("codex", "opencode"):
        from .cli import CLIExecutor
        return CLIExecutor.preset(name, **opts)
    raise ValueError(f"unknown executor {name!r} (scripted, claude, codex, opencode)")
