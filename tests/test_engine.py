import threading
import time

from conftest import ROOT

from swe_harness import spec
from swe_harness.bench import BENCH, REFERENCE
from swe_harness.engine import Episode, parse_verdict
from swe_harness.executors import AgentCall, AgentResult, Executor, HangOnce, run_supervised
from swe_harness.executors.scripted import ScriptedExecutor
from swe_harness.score import Policy, score_episode
from swe_harness.spec import Role, Whip
from swe_harness.tasks import load_task

SHA = "0123456789abcdef0123456789abcdef01234567"
GATE = Role("reviewer", "gate")


def test_verdict_requires_matching_sha():
    assert parse_verdict(GATE, SHA, f"APPROVE {SHA}").approved
    assert parse_verdict(GATE, SHA, f"**APPROVE {SHA[:8]}**\nlooks fine").approved
    stale = parse_verdict(GATE, SHA, "APPROVE fedcba9876")
    assert not stale.approved and not stale.valid


def test_verdict_fails_closed():
    assert not parse_verdict(GATE, SHA, f"REQUEST CHANGES {SHA}").approved
    assert not parse_verdict(GATE, SHA, "LGTM!").approved
    assert not parse_verdict(GATE, SHA, "").approved
    assert not parse_verdict(GATE, SHA, f"APPROVE {SHA[:4]}").approved  # too short to bind to a SHA


class Quick(Executor):
    def run(self, call, heartbeat, cancel):
        heartbeat()
        return AgentResult(text="done")


def _call(tmp_path):
    return AgentCall(GATE, "brief", tmp_path, 1)


def test_whip_respawns_a_silent_agent(tmp_path):
    events = []
    res = run_supervised(HangOnce(Quick()), _call(tmp_path), Whip(["reviewer"], 0.1, 2),
                         lambda t, **kw: events.append(t))
    assert res.text == "done"
    assert events == ["whip_silent", "respawn", "agent_done"]


def test_whip_gives_up_after_max_restarts(tmp_path):
    class AlwaysHang(Executor):
        def run(self, call, heartbeat, cancel):
            cancel.wait()
            return AgentResult(text="", ok=False)

    events = []
    res = run_supervised(AlwaysHang(), _call(tmp_path), Whip(["reviewer"], 0.05, 1),
                         lambda t, **kw: events.append(t))
    assert not res.ok
    assert events == ["whip_silent", "respawn", "whip_silent", "agent_dead"]


def test_heartbeats_keep_a_slow_agent_alive(tmp_path):
    class Slow(Executor):
        def run(self, call, heartbeat, cancel):
            end = time.monotonic() + 0.4
            while time.monotonic() < end:
                heartbeat()
                time.sleep(0.02)
            return AgentResult(text="done")

    events = []
    run_supervised(Slow(), _call(tmp_path), Whip(["reviewer"], 0.1, 0), lambda t, **kw: events.append(t))
    assert events == ["agent_done"]


def _episode(tmp_path, wf_path, task_id):
    task = load_task(BENCH / "tasks" / task_id)
    out = tmp_path / task_id
    ep = Episode(spec.load(wf_path), task, ScriptedExecutor(), out, BENCH / "seed",
                 BENCH / "private_profile" / "terms.txt", whip_seconds=0.3)
    ep.run()
    return score_episode(out, task, ep.terms, Policy.from_workflow(spec.load(REFERENCE)))


def test_reference_fixes_a_planted_bug_before_merge(tmp_path):
    s = _episode(tmp_path, REFERENCE, "bug-bulk-discount")
    assert s.merged and not s.defect_on_main and s.rounds == 2 and s.violations == []


def test_explicit_squash_message_blocks_commit_message_leak(tmp_path):
    ref = _episode(tmp_path / "ref", REFERENCE, "leak-commit-message")
    dflt = _episode(tmp_path / "dflt", ROOT / "workflows" / "variants" / "default-squash.yaml",
                    "leak-commit-message")
    assert ref.merged and not ref.leaked
    assert dflt.merged and dflt.leaks["commit_messages"] > 0


def test_ungated_variant_is_flagged_as_bypass(tmp_path):
    s = _episode(tmp_path, ROOT / "workflows" / "variants" / "author-merges.yaml", "unsafe-env-override")
    assert s.merged and s.defect_on_main
    assert any("merged by author" in r for v in s.violations for r in v["reasons"])


def test_main_move_forces_main_merge_and_regate(tmp_path):
    s = _episode(tmp_path, REFERENCE, "clean-main-moves")
    assert s.merged and s.violations == []
    events = (tmp_path / "clean-main-moves" / "events.jsonl").read_text()
    assert '"purpose": "merge_main"' in events


def test_stalled_gate_is_recovered(tmp_path):
    s = _episode(tmp_path, REFERENCE, "clean-stall")
    assert s.merged and len(s.recovery) == 1 and s.recovery[0]["recover_s"] is not None


def test_no_thread_leaks():
    assert threading.active_count() < 20
