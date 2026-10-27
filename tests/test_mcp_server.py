import json
import subprocess
import sys
import time

import pytest

from swe_harness import mcp_server as m


def _rpc(proc, mid, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


@pytest.fixture
def server():
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-m", "swe_harness.mcp_server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    init = _rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18"})
    yield proc, init, time.monotonic() - t0
    proc.stdin.close()
    proc.wait(5)


def test_fast_startup_and_calls(server):
    proc, init, startup = server
    assert init["result"]["serverInfo"]["name"] == "swe-harness"
    assert startup < 2.0, f"startup took {startup:.2f}s"
    t0 = time.monotonic()
    tools = _rpc(proc, 2, "tools/list")["result"]["tools"]
    args = {"paths": ["workflows/reference.yaml"]}
    res = _rpc(proc, 3, "tools/call", {"name": "validate_workflow", "arguments": args})
    per_call = (time.monotonic() - t0) / 2
    assert {t["name"] for t in tools} >= {"run_bench", "run_status", "get_report", "explain_episode"}
    assert res["result"]["content"][0]["text"].startswith("ok reference")
    assert per_call < 0.5, f"{per_call:.3f}s per call"


def test_errors_are_reported_not_raised(server):
    proc, _, _ = server
    assert _rpc(proc, 2, "nope")["error"]["code"] == -32601
    res = _rpc(proc, 3, "tools/call", {"name": "run_status", "arguments": {"run_id": "../etc"}})
    assert res["result"]["isError"] and "invalid run_id" in res["result"]["content"][0]["text"]


def test_live_run_needs_tasks_and_confirmation():
    with pytest.raises(m.ToolError, match="explicit task list"):
        m.run_bench(executor="claude")
    with pytest.raises(m.ToolError, match="confirm_live"):
        m.run_bench(executor="claude", tasks=["clean-stall"])


def test_workflow_paths_stay_inside_repo():
    with pytest.raises(m.ToolError):
        m._workflow_path("/etc/passwd")


def test_propose_variant_validates_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "VARIANTS", m.ROOT / "workflows" / "variants")
    name = f"tmp-test-{time.time_ns()}"
    try:
        out = m.propose_variant(name, {"gates": ["reviewer"], "merge": {"requires": ["reviewer"]}})
        assert "gates=['reviewer']" in out
        with pytest.raises(m.ToolError, match="exists"):
            m.propose_variant(name, {})
        with pytest.raises(m.ToolError, match="invalid variant"):
            m.propose_variant(name + "-bad", {"merge": {"merger": "ghost"}})
        assert not (m.VARIANTS / f"{name}-bad.yaml").exists()
        with pytest.raises(m.ToolError):
            m.propose_variant("reference", {})
    finally:
        (m.VARIANTS / f"{name}.yaml").unlink(missing_ok=True)


def test_explain_redacts_private_values(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "RUNS", tmp_path)
    ep = tmp_path / "r1" / "reference" / "t1"
    ep.mkdir(parents=True)
    events = [{"t": 1, "type": "comment", "role": "privacy",
               "text": "FAIL abc\n- leaked Marisol Quintero-Vance in examples/x.toml"},
              {"t": 2, "type": "verdict", "role": "privacy", "sha": "a" * 40, "approved": False, "valid": True}]
    (ep / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    out = m.explain_episode("r1", "reference", "t1")
    assert "Marisol" not in out and "[private term #1]" in out and "BLOCK" in out
