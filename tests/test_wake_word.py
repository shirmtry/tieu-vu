# =====================================================================
# tests/test_wake_word.py — phrase matcher "hey tieu vu"
# =====================================================================
from __future__ import annotations

from core.wake_word import OpenWakeWordDetector, PhraseMatcher


def test_variants_with_diacritics():
    m = PhraseMatcher("hey tieu vu")
    assert m.matches("hey tiểu vũ")
    assert m.matches("Hey Tiểu Vũ ơi")
    assert m.matches("hey tieu vu")
    assert m.matches("tiểu vũ")


def test_negative():
    m = PhraseMatcher("hey tieu vu")
    assert not m.matches("mở youtube")
    assert not m.matches("")


def test_detector_matches_text(base_config):
    d = OpenWakeWordDetector(base_config)
    assert d.matches_text("hey tieu vu oi")
    assert not d.matches_text("xin chao")
