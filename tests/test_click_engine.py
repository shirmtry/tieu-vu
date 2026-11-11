# =====================================================================
# tests/test_click_engine.py — dwell + blink
# =====================================================================
from __future__ import annotations

from core.click_engine import BlinkDetector, DwellClicker
from core.vision_engine import EyeObservation


def obs(ear, ts=0.0):
    return EyeObservation(ts, 0.5, 0.5, ear, ear)


def test_dwell_fires_after_650ms():
    d = DwellClicker(radius_px=40, dwell_sec=0.65, cooldown_sec=0.3)
    assert not d.update(100, 100, 0.0).clicked
    assert not d.update(105, 102, 0.3).clicked
    state = d.update(101, 99, 0.66)
    assert state.clicked
    assert state.progress >= 1.0


def test_dwell_resets_when_leaving_radius():
    d = DwellClicker(40, 0.65, 0.3)
    d.update(100, 100, 0.0)
    d.update(100, 100, 0.5)
    state = d.update(200, 200, 0.6)
    assert not state.clicked
    assert state.progress == 0.0


def test_dwell_cooldown():
    d = DwellClicker(40, 0.1, 0.5)
    d.update(10, 10, 0.0)
    assert d.update(10, 10, 0.12).clicked
    # Ngay sau click -> khong click lai truoc cooldown.
    d.update(10, 10, 0.15)
    assert not d.update(10, 10, 0.30).clicked


def test_blink_single_click():
    b = BlinkDetector(ear_threshold=0.2, min_closed_sec=0.35)
    assert b.update(obs(0.3, 0.0), 0.0) is None       # mo
    assert b.update(obs(0.1, 0.1), 0.1) is None       # bat dau nham
    assert b.update(obs(0.1, 0.5), 0.5) is None       # van nham
    assert b.update(obs(0.3, 0.6), 0.6) == "left_click"


def test_blink_short_is_ignored():
    b = BlinkDetector(ear_threshold=0.2, min_closed_sec=0.35)
    b.update(obs(0.1, 0.0), 0.0)
    assert b.update(obs(0.3, 0.1), 0.1) is None


def test_double_blink():
    b = BlinkDetector(ear_threshold=0.2, min_closed_sec=0.35, double_gap_sec=0.6)
    b.update(obs(0.1, 0.0), 0.0)
    assert b.update(obs(0.3, 0.4), 0.4) == "left_click"
    b.update(obs(0.1, 0.6), 0.6)
    assert b.update(obs(0.3, 0.95), 0.95) == "double_click"
