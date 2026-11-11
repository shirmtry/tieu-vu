# =====================================================================
# tests/test_calibration.py — fit poly2, save/load, validation
# =====================================================================
from __future__ import annotations

import numpy as np

from core.calibration import CalibrationStore, grid_points, poly2_features


def build_store(hs, vs, tx, ty):
    store = CalibrationStore(directory="unused")
    for h, v, x, y in zip(hs, vs, tx, ty, strict=False):
        store.add(h, v, x, y)
    return store


def test_grid_points_nine():
    pts = grid_points(1920, 1080, margin=0.08, n=3)
    assert len(pts) == 9
    assert all(0 <= x <= 1920 and 0 <= y <= 1080 for x, y in pts)


def test_poly2_features_shape():
    feats = poly2_features(np.array([0.2, 0.5]), np.array([0.3, 0.6]))
    assert feats.shape == (2, 6)
    assert np.allclose(feats[:, 0], 1.0)


def test_fit_linear_mapping():
    hs, vs, xs, ys = [], [], [], []
    for h in np.linspace(0.2, 0.8, 5):
        for v in np.linspace(0.2, 0.8, 5):
            hs.append(h)
            vs.append(v)
            xs.append(100 + 800 * h)
            ys.append(50 + 600 * v)
    store = build_store(hs, vs, xs, ys)
    model = store.fit(1920, 1080)
    assert model.rms_error_px < 1.0
    px, py = model.predict(0.5, 0.5)
    assert abs(px - 500) < 5 and abs(py - 350) < 5


def test_validate_within_threshold():
    hs, vs, xs, ys = [], [], [], []
    for h in np.linspace(0.2, 0.8, 9):
        for v in np.linspace(0.2, 0.8, 9):
            hs.append(h)
            vs.append(v)
            xs.append(1000 * h)
            ys.append(1000 * v)
    store = build_store(hs, vs, xs, ys)
    model = store.fit(1920, 1080)
    samples = list(zip(hs[:5], vs[:5], xs[:5], ys[:5], strict=False))
    ok, worst = CalibrationStore.validate(model, samples, max_error_px=80)
    assert ok
    assert worst < 80


def test_save_and_load(tmp_path):
    hs = np.linspace(0.2, 0.8, 9)
    vs = np.linspace(0.2, 0.8, 9)
    store = build_store(hs, vs, 1000 * hs, 800 * vs)
    model = store.fit(1920, 1080)
    path = store.save(model, user="tester")
    assert path.exists()
    loaded = CalibrationStore.load(path)
    assert loaded is not None
    assert abs(loaded.screen_w - 1920) < 1
    px, py = loaded.predict(0.5, 0.5)
    assert abs(px - 500) < 10


def test_load_missing_returns_none(tmp_path):
    assert CalibrationStore.load(tmp_path / "nope.npz") is None


def test_fit_requires_samples():
    import pytest

    store = CalibrationStore(directory="unused")
    with pytest.raises(ValueError):
        store.fit(1920, 1080)
