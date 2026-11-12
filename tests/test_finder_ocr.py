# =====================================================================
# tests/test_finder_ocr.py — OCR fallback (RapidOCR + mss mocked)
# =====================================================================
from __future__ import annotations

import numpy as np

from core.finder.ocr_finder import OcrFinder

BOX = [[10, 20], [90, 20], [90, 40], [10, 40]]


class _Engine:
    def __init__(self, results):
        self.results = results
        self.calls = 0

    def __call__(self, img):
        self.calls += 1
        return self.results, 0.01


def _finder(results):
    finder = OcrFinder(min_conf=0.6)
    finder._engine = _Engine(results)
    finder._capture = lambda: np.zeros((8, 8, 3), dtype=np.uint8)
    return finder


def test_find_fuzzy_match_bbox_only():
    finder = _finder([(BOX, "Đăng nhập", 0.9)])
    results = finder.find_by_text("dang nhap")
    assert len(results) == 1
    assert results[0].name == ""  # privacy: text never stored
    assert results[0].role == "text"
    assert results[0].source == "ocr"
    assert results[0].bbox == (10, 20, 80, 20)


def test_low_confidence_filtered():
    finder = _finder([(BOX, "Đăng nhập", 0.3)])
    assert finder.find_by_text("dang nhap") == []


def test_empty_results():
    assert _finder([]).find_by_text("dang nhap") == []


def test_unavailable_returns_empty():
    finder = OcrFinder()
    finder._tried = True  # gia lap import rapidocr that bai
    assert finder.available is False
    assert finder.find_by_text("login") == []
