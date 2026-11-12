# =====================================================================
# tests/test_finder_hybrid.py — UIA primary, OCR fallback
# =====================================================================
from __future__ import annotations

from core.finder.hybrid import HybridFinder
from core.finder.uia_finder import FoundElement

CFG = {
    "voice_click": {
        "enabled": True,
        "uia": {"min_score": 70},
        "ocr_fallback": {"enabled": True, "min_conf": 0.6, "min_score": 70},
    }
}

UIA_EL = FoundElement("uia:button:aaa", "Login", "button", (10, 10, 80, 30), "uia")
OCR_EL = FoundElement("ocr:text:bbb", "", "text", (20, 20, 60, 20), "ocr")


class _FakeUia:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def find_by_name(self, name, min_score=70.0):
        self.calls.append((name, min_score))
        return list(self.results)


class _FakeOcr:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def find_by_text(self, text, min_score=70.0):
        self.calls.append((text, min_score))
        return list(self.results)


def test_uia_hit_skips_ocr():
    finder = HybridFinder(CFG)
    finder.uia = _FakeUia([UIA_EL])
    finder.ocr = _FakeOcr([OCR_EL])
    assert finder.find("login") == [UIA_EL]
    assert finder.ocr.calls == []


def test_ocr_fallback_when_uia_empty():
    finder = HybridFinder(CFG)
    finder.uia = _FakeUia([])
    finder.ocr = _FakeOcr([OCR_EL])
    assert finder.find("login") == [OCR_EL]
    assert finder.uia.calls and finder.ocr.calls


def test_both_fail_and_blank_target():
    finder = HybridFinder(CFG)
    finder.uia = _FakeUia([])
    finder.ocr = _FakeOcr([])
    assert finder.find("khong co") == []
    assert finder.find("   ") == []
