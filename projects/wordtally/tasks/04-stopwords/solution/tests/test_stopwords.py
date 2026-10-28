from wordtally import load_stopwords


def test_load_stopwords(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("A\n\nb\n", encoding="utf-8")
    assert load_stopwords(p) == {"a", "b"}
