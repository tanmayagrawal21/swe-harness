import json

import yaml

from swe_harness import spec
from swe_harness.bench import BENCH, REFERENCE
from swe_harness.engine import Episode
from swe_harness.executors.scripted import ScriptedExecutor
from swe_harness.score import Policy, score_episode
from swe_harness.sources import swebench
from swe_harness.tasks import load_tasks

GOOD = """--- a/toyshop/pricing.py
+++ b/toyshop/pricing.py
@@ -5,2 +5,6 @@ def subtotal(items: list[tuple[float, int]]) -> float:
     \"\"\"Sum of price * quantity.\"\"\"
     return sum(price * qty for price, qty in items)
+
+
+def double(x: float) -> float:
+    return 2 * x
"""
BAD = GOOD.replace("2 * x", "x + x + 1")
CORRUPT = "--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-missing\n+line\n"


def _fake_network(monkeypatch, tmp_path):
    row = {"instance_id": "acme__toy-1", "repo": "acme/toy", "base_commit": "abc123", "patch": GOOD,
           "problem_statement": "Add double(x).\nDetails follow."}
    pages = {o: json.dumps({"rows": [{"row": row}] if o == 0 else []}) for o in range(0, 500, 100)}
    patches = {"e1": BAD, "e2": CORRUPT, "e3": GOOD}

    def get(url):
        if "datasets-server" in url:
            return pages[int(url.split("offset=")[1].split("&")[0])].encode()
        if url.endswith("metadata.yaml"):
            entry = url.split("/")[-2]
            return yaml.safe_dump({"assets": {"logs": f"s3://bucket/verified/{entry}/logs"}}).encode()
        if url.endswith("results.json"):
            return json.dumps({"resolved": ["acme__toy-1"] if "/e3/" in url else []}).encode()
        name = next(e for e in patches if f"/{e}/" in url)
        return patches[name].encode()

    monkeypatch.setattr(swebench, "_get", get)
    monkeypatch.setattr(swebench, "EXP_RAW", "https://raw.example/{entry}/{path}")
    monkeypatch.setattr(swebench, "git_seed", lambda url, commit: BENCH / "seed")
    return swebench.build(tmp_path / "out", ["acme/toy"], ["e1", "e2", "e3"], cache=tmp_path / "cache")


def test_build_labels_dedupes_and_drops(monkeypatch, tmp_path):
    out = _fake_network(monkeypatch, tmp_path)
    tasks = {t.id: t for t in load_tasks(out / "tasks")}
    # gold (merge) and e1 (unresolved: block); e2 is corrupt and dropped; e3 equals gold and is deduped
    assert sorted(t.kind for t in tasks.values()) == ["bug", "clean"]
    assert all(t.oracle == "label" and t.ci == "skip" and t.pr_patch for t in tasks.values())
    assert "1 unusable patches dropped" in (out / "SOURCE.md").read_text()


def test_label_task_episode(monkeypatch, tmp_path):
    out = _fake_network(monkeypatch, tmp_path)
    policy = Policy.from_workflow(spec.load(REFERENCE))
    for t in load_tasks(out / "tasks"):
        t.seed = None  # use bench/seed directly: same tree as the faked git seed
        ep = Episode(spec.load(REFERENCE), t, ScriptedExecutor(), tmp_path / "ep" / t.id, BENCH / "seed",
                     out / "private_profile" / "terms.txt", whip_seconds=0.5)
        merged = ep.run()
        s = score_episode(tmp_path / "ep" / t.id, t, ep.terms, policy)
        assert merged == (t.kind == "clean") and not s.defect_on_main and s.violations == []
        assert '"skipped": true' in (tmp_path / "ep" / t.id / "events.jsonl").read_text()
