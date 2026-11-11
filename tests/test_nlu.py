# =====================================================================
# tests/test_nlu.py — rule-based intents (donate, search, open)
# =====================================================================
from __future__ import annotations

from core.nlu import NLU, RuleEngine


def make_nlu(base_config):
    cfg = dict(base_config)
    cfg["nlu"] = dict(base_config.get("nlu", {}), llm_fallback=False, rules=[])
    return NLU(cfg)


def test_donate_intent(base_config):
    intents = make_nlu(base_config).parse("ủng hộ tiểu vũ")
    assert intents and intents[0].name == "donate_window"
    assert intents[0].source == "rule"


def test_donate_accentless(base_config):
    intents = make_nlu(base_config).parse("ung ho tieu vu")
    assert intents and intents[0].name == "donate_window"


def test_search_payload(base_config):
    intents = make_nlu(base_config).parse("tìm kiếm thời tiết hà nội")
    assert intents and intents[0].name == "search"
    assert "thoi tiet" in intents[0].payload["query"]


def test_type_text_payload(base_config):
    intents = make_nlu(base_config).parse("gõ xin chào")
    assert intents and intents[0].name == "type_text"
    assert intents[0].payload["text"] == "xin chao"


def test_unknown_returns_empty(base_config):
    assert make_nlu(base_config).parse("xyzabc khong ro") == []


def test_disabled(base_config):
    cfg = dict(base_config)
    cfg["nlu"] = {"enabled": False}
    assert NLU(cfg).parse("ủng hộ tiểu vũ") == []


def test_custom_rules():
    rules = [{"name": "click", "patterns": ["bấm chuột"], "confidence": 0.9}]
    engine = RuleEngine(rules, threshold=90)
    intent = engine.parse("bấm chuột")
    assert intent is not None and intent.name == "click"
