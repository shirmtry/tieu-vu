# =====================================================================
# tests/test_perf_bench.py — latency budgets: find() < 5ms, update() < 0.1ms
# =====================================================================
from __future__ import annotations

import time

from core.finder.hybrid import HybridFinder
from core.finder.uia_finder import FoundElement
from core.state_machine import StateMachine
from core.vision_engine import VisionFrame


class _FastUia:
    def find_by_name(self, name, min_score=70.0):
        return [FoundElement("uia:button:abc", "Login", "button", (1, 2, 3, 4), "uia")]


class _NeverOcr:
    def find_by_text(self, text, min_score=70.0):
        return []


def test_find_under_5ms(benchmark, base_config):
    finder = HybridFinder(base_config)
    finder.uia = _FastUia()
    finder.ocr = _NeverOcr()
    finder.find("login")
    benchmark.pedantic(finder.find, args=("login",), iterations=50, rounds=5)
    assert benchmark.stats["mean"] < 0.005


def test_update_under_0_1ms(benchmark, base_config):
    sm = StateMachine(base_config)
    frame = VisionFrame(timestamp=time.time(), hands=[])
    sm.update(frame)
    benchmark.pedantic(sm.update, args=(frame,), iterations=100, rounds=5)
    assert benchmark.stats["mean"] < 0.0001
