# =====================================================================
# tests/test_snippet.py — text expander (buffer 12 ky tu, trigger config)
# =====================================================================
from __future__ import annotations

import pytest

from core.snippet_engine import SnippetEngine


@pytest.fixture()
def engine(base_config):
    cfg = dict(base_config)
    cfg["snippets"] = {
        "enabled": True,
        "buffer_size": 12,
        "triggers": {
            ";addr": "123 Nguyen Trai",
            ";mail": "a@b.c",
            ";date": "{date}",
        },
    }
    return SnippetEngine(cfg)


def type_text(engine, text):
    result = None
    for ch in text:
        hit = engine.feed(ch)
        if hit:
            result = hit
    return result


def test_expand_trigger(engine):
    assert type_text(engine, ";addr") == (";addr", "123 Nguyen Trai")


def test_expand_mid_sentence(engine):
    hit = type_text(engine, "hello ;mail")
    assert hit is not None
    assert hit[1] == "a@b.c"


def test_buffer_limited_to_12(engine):
    for ch in "abcdefghijklmnop":
        engine.feed(ch)
    assert len(engine.buffer) == 12


def test_dynamic_date(engine):
    hit = type_text(engine, ";date")
    assert hit is not None
    assert len(hit[1]) == 10 and hit[1][4] == "-"


def test_no_trigger(engine):
    assert type_text(engine, ";xyz") is None


def test_control_char_resets(engine):
    engine.feed(";")
    engine.feed("a")
    engine.feed("\n")
    assert engine.buffer == ""
    hit = type_text(engine, ";mail")
    assert hit is not None
