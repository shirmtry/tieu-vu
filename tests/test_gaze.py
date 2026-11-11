# =====================================================================
# tests/test_gaze.py — EyeTracker, One Euro, GazeEstimator
# =====================================================================
from __future__ import annotations

import math

import numpy as np

from core.filters import DeadZone, OneEuroFilter
from core.gaze_estimator import GazeEstimator, head_pitch_ok
from core.vision_engine import EyeTracker


def test_eye_tracker_reads_iris_ratio(face_factory):
    tracker = EyeTracker({})
    face = face_factory(h=0.5, v=0.5, ear=0.3)
    obs = tracker.observe(face, timestamp=1.0)
    assert obs is not None
    assert obs.valid
    assert abs(obs.h_ratio - 0.5) < 0.05
    assert abs(obs.v_ratio - 0.5) < 0.05
    assert abs(obs.ear - 0.3) < 0.05


def test_eye_tracker_horizontal_shift(face_factory):
    tracker = EyeTracker({})
    left = tracker.observe(face_factory(h=0.2), 1.0)
    right = tracker.observe(face_factory(h=0.8), 2.0)
    assert left is not None and right is not None
    assert right.h_ratio > left.h_ratio + 0.4


def test_no_face_returns_none():
    assert EyeTracker({}).observe(None, 0.0) is None


def test_one_euro_constant_signal():
    filt = OneEuroFilter(f=30.0, mincut=1.0, beta=0.007, dcut=1.0)
    out = [filt(10.0) for _ in range(10)]
    assert out[0] == 10.0
    assert all(abs(v - 10.0) < 1e-6 for v in out)


def test_one_euro_smooths_noise():
    rng = np.random.default_rng(0)
    filt = OneEuroFilter(f=30.0, mincut=1.0, beta=0.0, dcut=1.0)
    signal = 100.0 + rng.normal(0, 5, 200)
    out = [filt(float(x)) for x in signal]
    assert np.std(out[50:]) < np.std(signal)


def test_dead_zone_holds_small_moves():
    dz = DeadZone(min_px=8.0, hold_sec=0.1)
    assert dz(100, 100, now=0.0) == (100, 100)
    assert dz(102, 101, now=0.02) is None
    assert dz(103, 102, now=0.05) is None
    # Sau hold_sec van emit de khong bi ket.
    assert dz(104, 103, now=0.2) == (104, 103)


def test_gaze_estimator_linear_default(base_config):
    cfg = dict(base_config)
    cfg["gaze"] = dict(base_config["gaze"], calibration_dir="/nonexistent",
                       smoothing=False, screen_width=1920, screen_height=1080)
    est = GazeEstimator(cfg)
    obs = est.observe(None, 0.0)
    assert obs is None
    from core.vision_engine import EyeObservation

    x, y = est.geometric_px(EyeObservation(0.0, 0.5, 0.5, 0.3, 0.3))
    assert abs(x - 959.5) < 1.0
    assert abs(y - 539.5) < 1.0


def test_head_pitch_ok(face_factory):
    assert head_pitch_ok(face_factory()) is True
    face = face_factory()
    from core.vision_engine import NOSE_TIP

    face.points[NOSE_TIP] = (0.5, 0.43, 0)   # mui sat mat -> pitch bat thuong
    assert head_pitch_ok(face) is False
    assert head_pitch_ok(None) is False


def test_gaze_estimate_filters(face_factory, base_config):
    cfg = dict(base_config)
    cfg["gaze"] = dict(base_config["gaze"], calibration_dir="/nonexistent",
                       smoothing=True)
    est = GazeEstimator(cfg)
    g1 = est.estimate(face_factory(h=0.5, v=0.5), 1.0)
    g2 = est.estimate(face_factory(h=0.55, v=0.5), 1.03)
    assert g1 is not None and g2 is not None
    assert math.isfinite(g1.x) and math.isfinite(g2.x)
    assert g2.source == "geometric"
