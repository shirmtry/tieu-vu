# =====================================================================
# tests/test_scroll_engine.py — edge scroll ramp 3 -> 15 lines/s
# =====================================================================
from __future__ import annotations

from core.scroll_engine import EdgeScrollEngine


def test_no_scroll_in_middle():
    e = EdgeScrollEngine()
    assert e.update(500, 1000, True, 0.0) == 0
    assert e.update(500, 1000, True, 1.0) == 0


def test_no_scroll_when_pitch_bad():
    e = EdgeScrollEngine()
    assert e.update(10, 1000, False, 0.0) == 0


def test_scroll_up_accumulates():
    e = EdgeScrollEngine(zone_ratio=0.10, min_rate=3, max_rate=15, ramp_sec=1.0)
    total = 0
    t = 0.0
    for _ in range(20):
        t += 0.05
        total += e.update(5, 1000, True, t)
    assert total > 0
    assert e.state.direction == "up"


def test_scroll_down_negative():
    e = EdgeScrollEngine()
    total = 0
    t = 0.0
    for _ in range(20):
        t += 0.05
        total += e.update(995, 1000, True, t)
    assert total < 0
    assert e.state.direction == "down"


def test_rate_ramps_within_bounds():
    e = EdgeScrollEngine(min_rate=3, max_rate=15, ramp_sec=1.0)
    e.update(5, 1000, True, 0.0)
    e.update(5, 1000, True, 0.2)
    early = e.state.rate_lps
    e.update(5, 1000, True, 2.0)
    late = e.state.rate_lps
    assert 3.0 <= early <= 15.0
    assert 3.0 <= late <= 15.0
    assert late > early
