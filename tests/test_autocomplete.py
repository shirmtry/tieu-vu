# =====================================================================
# tests/test_autocomplete.py — n-gram suggestions
# =====================================================================
from __future__ import annotations

from core.autocomplete import AutocompleteEngine, NgramModel


def test_ngram_next_token():
    m = NgramModel(order=2)
    m.train(["mở youtube và phát nhạc", "mở youtube và phát video"])
    assert "youtube" in m.suggest("mở", k=3)
    assert "phát" in m.suggest("mở youtube và", k=3)


def test_engine_returns_three(base_config):
    engine = AutocompleteEngine(base_config)
    out = engine.suggest("tìm")
    assert 0 < len(out) <= 3


def test_empty_text(base_config):
    assert AutocompleteEngine(base_config).suggest("") == []


def test_disabled(base_config):
    cfg = dict(base_config)
    cfg["autocomplete"] = {"enabled": False}
    assert AutocompleteEngine(cfg).suggest("tìm") == []


def test_prefix_filtering():
    m = NgramModel(order=1)
    m.train(["app apple application banana"])
    out = m.suggest("app", k=3)
    assert out and all(t.startswith("app") for t in out)
