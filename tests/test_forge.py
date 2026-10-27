import pytest

from swe_harness.forge import git, remove_worktree


def test_git_never_reaches_an_enclosing_repo(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    git(outer, "init", "-q", "-b", "main")
    (outer / "keep.txt").write_text("precious\n")
    inner = outer / "runs" / "broken-worktree"
    inner.mkdir(parents=True)
    (inner / ".git").write_text("gitdir: /nonexistent/pruned\n")  # what a pruned worktree looks like
    with pytest.raises(RuntimeError):
        git(inner, "status")
    with pytest.raises(RuntimeError):
        remove_worktree(outer, inner)
    assert (outer / "keep.txt").read_text() == "precious\n"
    assert not (outer / ".git" / "index.lock").exists()


def test_relative_run_dir_works(tmp_path, monkeypatch):
    from swe_harness.bench import BENCH
    from swe_harness.forge import EventLog, LocalForge

    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel").mkdir()
    forge = LocalForge(__import__("pathlib").Path("rel"), EventLog(tmp_path / "rel" / "events.jsonl"))
    forge.init_from(BENCH / "seed")
    sha = forge.commit_overlay("feature", BENCH / "tasks" / "clean-stall" / "pr", "Add with_tax")
    assert forge.head("feature") == sha
