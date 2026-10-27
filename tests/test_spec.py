import pytest
from conftest import ROOT

from swe_harness import spec


def test_reference_loads(reference):
    assert reference.gates == ["reviewer", "privacy", "control"]
    assert reference.merge.merger == "reviewer"
    assert reference.merge.squash and "#{pr}" in reference.merge.squash.subject
    assert reference.author.name == "author"
    assert "independent code reviewer" in reference.roles["reviewer"].prompt
    assert reference.whip_for("privacy").silent_seconds == 300


@pytest.mark.parametrize("name,gates,merger", [
    ("no-privacy", ["reviewer", "control"], "reviewer"),
    ("author-merges", [], "author"),
])
def test_variants_extend_reference(name, gates, merger):
    wf = spec.load(ROOT / "workflows" / "variants" / f"{name}.yaml")
    assert wf.gates == gates and wf.merge.merger == merger
    assert wf.round_cap == 3  # inherited


def test_default_squash_variant_has_no_explicit_message():
    assert spec.load(ROOT / "workflows" / "variants" / "default-squash.yaml").merge.squash is None


def test_control_scope(reference):
    control = reference.roles["control"]
    assert control.in_scope(["toyshop/guard.py"])
    assert not control.in_scope(["toyshop/fmt.py", "tests/test_fmt.py"])
    assert reference.roles["reviewer"].in_scope(["anything.py"])


def _base():
    return {"roles": {"a": {"kind": "author"}, "r": {"kind": "gate"}}, "gates": ["r"],
            "merge": {"merger": "r", "requires": ["r"]}}


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["roles"].update(b={"kind": "author"}), "exactly one author"),
    (lambda d: d["roles"]["r"].update(kind="robot"), "kind must be"),
    (lambda d: d["merge"].update(merger="ghost"), "merger"),
    (lambda d: d["merge"].update(requires=["a"]), "not an active gate"),
    (lambda d: d.update(gates=["a"]), "not a role of kind 'gate'"),
    (lambda d: d.update(round_cap=0), "round_cap"),
])
def test_invalid_specs_fail(tmp_path, mutate, msg):
    d = _base()
    mutate(d)
    with pytest.raises(spec.SpecError, match=msg):
        spec.parse(d, tmp_path)
