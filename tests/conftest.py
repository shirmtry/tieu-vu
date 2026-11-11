# =====================================================================
# tests/conftest.py — duong dan import + fixture dung chung
# =====================================================================
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def base_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture()
def face_factory():
    """Tao FaceLandmarks 478 diem voi iris/mat tong hop."""
    from core.vision_engine import (
        CHIN,
        LEFT_EAR_POINTS,
        LEFT_EYE_BOTTOM,
        LEFT_EYE_INNER,
        LEFT_EYE_OUTER,
        LEFT_EYE_TOP,
        LEFT_IRIS,
        NOSE_TIP,
        RIGHT_EAR_POINTS,
        RIGHT_EYE_BOTTOM,
        RIGHT_EYE_INNER,
        RIGHT_EYE_OUTER,
        RIGHT_EYE_TOP,
        RIGHT_IRIS,
        FaceLandmarks,
    )

    def make(h: float = 0.5, v: float = 0.5, ear: float = 0.30, ear_l=None,
             ear_r=None):
        pts = np.zeros((478, 3), dtype=np.float32)
        # Mat trai: goc 0.30/0.40, iris theo h.
        pts[LEFT_EYE_OUTER] = (0.30, 0.42, 0)
        pts[LEFT_EYE_INNER] = (0.40, 0.42, 0)
        pts[LEFT_IRIS] = (0.30 + 0.10 * h, 0.42 + 0.02 * (v - 0.5) / 0.5, 0)
        pts[LEFT_EYE_TOP] = (0.35, 0.40, 0)
        pts[LEFT_EYE_BOTTOM] = (0.35, 0.44, 0)
        pts[LEFT_IRIS][1] = 0.40 + 0.04 * v
        # Mat phai.
        pts[RIGHT_EYE_INNER] = (0.60, 0.42, 0)
        pts[RIGHT_EYE_OUTER] = (0.70, 0.42, 0)
        pts[RIGHT_IRIS] = (0.60 + 0.10 * h, 0.40 + 0.04 * v, 0)
        pts[RIGHT_EYE_TOP] = (0.65, 0.40, 0)
        pts[RIGHT_EYE_BOTTOM] = (0.65, 0.44, 0)

        # EAR: 6 diem moi mat.
        def set_ear(idx, frac, x0):
            p1, p2, p3, p4, p5, p6 = idx
            x1 = x0 + 0.10
            pts[p1] = (x0, 0.42, 0)
            pts[p4] = (x1, 0.42, 0)
            vert = frac * 0.10 / 2.0
            pts[p2] = (x0 + 0.03, 0.42 - vert, 0)
            pts[p6] = (x0 + 0.03, 0.42 + vert, 0)
            pts[p3] = (x0 + 0.07, 0.42 - vert, 0)
            pts[p5] = (x0 + 0.07, 0.42 + vert, 0)

        set_ear(LEFT_EAR_POINTS, ear if ear_l is None else ear_l, 0.30)
        set_ear(RIGHT_EAR_POINTS, ear if ear_r is None else ear_r, 0.60)
        # Pitch: eye_y ~0.42, chin 0.80, nose 0.60 -> frac 0.47 (hop le).
        pts[NOSE_TIP] = (0.50, 0.60, 0)
        pts[CHIN] = (0.50, 0.80, 0)
        return FaceLandmarks(points=pts)

    return make
