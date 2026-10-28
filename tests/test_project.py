import shutil
from pathlib import Path

import pytest
import yaml

from swe_harness.forge import git
from swe_harness.project import build, load_project

WORDTALLY = Path(__file__).resolve().parents[1] / "projects" / "wordtally"


def test_dry_build_delivers_every_step_from_a_readme_only_seed(tmp_path):
    r = build(WORDTALLY, tmp_path / "out")
    assert (r["delivered"], r["steps"], r["gate_bypass_merges"], r["leaks"]) == (4, 4, 0, 0)
    assert all(r["final_acceptance"].values()) and r["regressions"] == []
    repo = Path(r["final_repo"])
    log = git(repo, "log", "--format=%s", "main").splitlines()
    assert log == ["Add --stopwords (#1)", "Add a command line (#1)", "Add top_words (#1)", "Add count_words (#1)",
                   "Initial commit"]  # each step continued from the previous step's main


def _project(tmp_path, drop_solution: str | None = None) -> Path:
    d = tmp_path / "proj"
    shutil.copytree(WORDTALLY, d)
    if drop_solution:
        shutil.rmtree(d / "tasks" / drop_solution / "solution")
    return d


def test_a_step_the_author_cannot_write_stops_the_build(tmp_path):
    r = build(_project(tmp_path, "02-top"), tmp_path / "out")
    assert (r["attempted"], r["delivered"]) == (2, 1)
    assert r["final_acceptance"] == {"01-count": True, "02-top": False, "03-cli": False, "04-stopwords": False}
    assert not r["episodes"][1]["merged"]


def test_keep_going_attempts_every_step(tmp_path):
    r = build(_project(tmp_path, "02-top"), tmp_path / "out", keep_going=True)
    merged = [e["merged"] for e in r["episodes"]]
    assert r["attempted"] == 4 and merged == [True, False, False, True]  # 03 needs top_words: its CI is red;
    assert r["final_acceptance"]["02-top"]  # 04's solution also brings top_words, so the gap closes


def test_project_steps_must_be_author_written_features(tmp_path):
    d = _project(tmp_path)
    y = d / "tasks" / "01-count" / "task.yaml"
    y.write_text(yaml.safe_dump({**yaml.safe_load(y.read_text()), "kind": "clean"}))
    with pytest.raises(ValueError):
        load_project(d)


def test_a_leak_in_a_chained_step_is_counted_once(tmp_path):
    d = _project(tmp_path)
    terms = Path(__file__).resolve().parents[1] / "bench" / "private_profile" / "terms.txt"
    term = next(t.strip() for t in terms.read_text().splitlines() if t.strip() and not t.startswith("#"))
    (d / "tasks" / "02-top" / "solution" / "NOTES.md").write_text(f"contact: {term}\n")
    wf = Path(__file__).resolve().parents[1] / "workflows" / "variants" / "no-privacy.yaml"
    r = build(d, tmp_path / "out", workflow=wf)
    leaked = [sum(e["leaks"].values()) > 0 for e in r["episodes"]]
    assert leaked == [False, True, False, False]  # later steps start from a main that already holds it


def test_chained_repos_have_no_remote(tmp_path):
    r = build(WORDTALLY, tmp_path / "out")
    assert git(Path(r["final_repo"]), "remote") == ""


def test_live_build_refuses_an_out_dir_inside_the_checkout():
    from swe_harness.cli import main

    assert main(["build", str(WORDTALLY), "--executor", "claude", "--confirm-live", "--out",
                 str(WORDTALLY.parents[1] / "runs" / "x")]) == 2
