import json
from pathlib import Path

from swe_harness.executors import AgentCall, make_executor
from swe_harness.executors.claude_code import ClaudeCodeExecutor, parse_line, result_from
from swe_harness.executors.cli import CLIExecutor


def test_claude_command_isolates_settings_and_locks_gates(reference):
    ex = ClaudeCodeExecutor(max_budget_usd=0.5)
    gate = ex.command(AgentCall(reference.roles["privacy"], "review it", Path("."), 1))
    assert gate[:3] == ["claude", "-p", "review it"]
    assert gate[gate.index("--setting-sources") + 1] == "project,local"
    assert gate[gate.index("--model") + 1] == "sonnet"
    assert "Edit" in gate[gate.index("--disallowedTools"):]
    author = ex.command(AgentCall(reference.author, "fix it", Path("."), 1))
    assert "--disallowedTools" not in author


def test_claude_result_parsing():
    line = json.dumps({"type": "result", "result": "APPROVE abc1234", "total_cost_usd": 0.12,
                       "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5}})
    r = result_from(parse_line(line))
    assert (r.text, r.input_tokens, r.output_tokens, r.cost_usd, r.ok) == ("APPROVE abc1234", 100, 5, 0.12, True)
    assert parse_line("not json") is None
    assert not result_from(None).ok


def test_cli_presets(reference):
    ex = make_executor("codex")
    assert isinstance(ex, CLIExecutor)
    cmd = ex.command(AgentCall(reference.author, "do it", Path("."), 1))
    assert cmd[:2] == ["codex", "exec"] and cmd[-1].endswith("do it")
