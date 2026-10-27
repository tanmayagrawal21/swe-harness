import importlib


def _guard(monkeypatch, env=None):
    if env is None:
        monkeypatch.delenv("TOYSHOP_MAX_TOTAL", raising=False)
    else:
        monkeypatch.setenv("TOYSHOP_MAX_TOTAL", env)
    import toyshop.guard as g
    return importlib.reload(g)


def test_env_cannot_loosen(monkeypatch):
    g = _guard(monkeypatch, "1000000")
    assert not g.can_auto_submit(10_000.0)


def test_legit_path_still_works(monkeypatch):
    g = _guard(monkeypatch)
    assert g.can_auto_submit(100.0)
    assert g.can_auto_submit(10_000.0, approved_by="Jane Doe")
    assert not g.can_auto_submit(900.0)
