import yaml

from swe_harness.gen_privacy import generate
from swe_harness.privacy import load_terms, match_terms
from swe_harness.tasks import load_tasks


def _texts(d, sub="pr"):
    return "\n".join(f.read_text() for f in sorted((d / sub).rglob("*")) if f.is_file())


def test_generated_traps_have_ground_truth_by_construction(tmp_path):
    out = generate(tmp_path / "gen", n=6, seed=3)
    terms = load_terms(out / "private_profile" / "terms.txt")
    tasks = load_tasks(out / "tasks")
    assert len(tasks) == 12 and {t.kind for t in tasks} == {"leak", "clean"}
    surfaces = set()
    for t in tasks:
        meta = yaml.safe_load((t.dir / "task.yaml").read_text())
        in_diff, in_msg = bool(match_terms(_texts(t.dir), terms)), bool(match_terms(t.pr_message, terms))
        if t.kind == "clean":
            assert not in_diff and not in_msg
        else:
            surfaces.add((t.id.split("-")[2], meta["surface"]))
            assert (in_diff, in_msg) == (meta["surface"] == "diff", meta["surface"] == "commit_message")
            if meta["surface"] == "diff":
                assert t.fix_dir and not match_terms(_texts(t.dir, "fix"), terms)
    assert len(surfaces) == 6  # each feature appears with both surfaces


def test_generation_is_deterministic(tmp_path):
    a = generate(tmp_path / "a", n=4, seed=7)
    b = generate(tmp_path / "b", n=4, seed=7)
    assert (a / "private_profile" / "terms.txt").read_text() == (b / "private_profile" / "terms.txt").read_text()
