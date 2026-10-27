from toyshop import guard


def test_env_limit(monkeypatch):
    monkeypatch.setenv("TOYSHOP_MAX_TOTAL", "50")
    assert not guard.can_auto_submit(100.0)
