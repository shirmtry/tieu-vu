# =====================================================================
# core/calibration.py
# Hieu chuan 9 diem: thu tin hieu mat (h_ratio, v_ratio) tai 9 vi tri
# tren man hinh, khop da thuc bac 2 (numpy.polyfit/lstsq), luu npz.
# =====================================================================
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_DIR = Path("config")


def grid_points(screen_w: int, screen_h: int, margin: float = 0.08,
                n: int = 3) -> List[Tuple[float, float]]:
    """Sinh luoi n x n diem (mac dinh 9 diem) trong vung an toan man hinh."""
    xs = np.linspace(margin, 1.0 - margin, n) * screen_w
    ys = np.linspace(margin, 1.0 - margin, n) * screen_h
    return [(float(x), float(y)) for y in ys for x in xs]


def poly2_features(h: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vector dac trung bac 2: [1, h, v, h*v, h^2, v^2]."""
    h = np.asarray(h, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    return np.stack([np.ones_like(h), h, v, h * v, h * h, v * v], axis=-1)


@dataclass
class CalibrationModel:
    """He so da thuc anh xa (h, v) -> (screen_x, screen_y)."""

    coeffs_x: np.ndarray
    coeffs_y: np.ndarray
    screen_w: int
    screen_h: int
    rms_error_px: float = 0.0
    n_samples: int = 0

    def predict(self, h: float, v: float) -> Tuple[float, float]:
        feats = poly2_features(np.array([h]), np.array([v]))[0]
        x = float(feats @ self.coeffs_x)
        y = float(feats @ self.coeffs_y)
        x = min(max(x, 0.0), float(self.screen_w - 1))
        y = min(max(y, 0.0), float(self.screen_h - 1))
        return x, y


class CalibrationStore:
    """Thu thap mau 9 diem, fit da thuc bac 2, luu/doc file .npz."""

    def __init__(self, directory: Path | str = DEFAULT_DIR, degree: int = 2):
        self.directory = Path(directory)
        self.degree = int(degree)
        self._h: List[float] = []
        self._v: List[float] = []
        self._x: List[float] = []
        self._y: List[float] = []

    # ------------------------------------------------------------------
    def add(self, h: float, v: float, screen_x: float, screen_y: float):
        self._h.append(float(h))
        self._v.append(float(v))
        self._x.append(float(screen_x))
        self._y.append(float(screen_y))

    def clear(self):
        self._h.clear()
        self._v.clear()
        self._x.clear()
        self._y.clear()

    @property
    def n_samples(self) -> int:
        return len(self._h)

    # ------------------------------------------------------------------
    def fit(self, screen_w: int, screen_h: int) -> CalibrationModel:
        if self.n_samples < 6:
            raise ValueError("Can it nhat 6 mau (khuyen nghi 9 diem x 30 frame).")
        h = np.asarray(self._h)
        v = np.asarray(self._v)
        if self.degree == 1:
            feats = np.stack([np.ones_like(h), h, v], axis=-1)
        else:
            feats = poly2_features(h, v)
        tx = np.asarray(self._x)
        ty = np.asarray(self._y)
        # lstsq on dinh hon polyfit khi mau chua chuan hoa.
        cx, *_ = np.linalg.lstsq(feats, tx, rcond=None)
        cy, *_ = np.linalg.lstsq(feats, ty, rcond=None)
        pred_x = feats @ cx
        pred_y = feats @ cy
        rms = float(np.sqrt(np.mean((pred_x - tx) ** 2 + (pred_y - ty) ** 2)))
        return CalibrationModel(cx, cy, int(screen_w), int(screen_h),
                                rms_error_px=rms, n_samples=self.n_samples)

    # ------------------------------------------------------------------
    def path_for(self, user: str = "default") -> Path:
        return self.directory / f"calibration_{user}.npz"

    def save(self, model: CalibrationModel, user: str = "default") -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(user)
        np.savez_compressed(
            path,
            coeffs_x=model.coeffs_x,
            coeffs_y=model.coeffs_y,
            screen_w=model.screen_w,
            screen_h=model.screen_h,
            rms_error_px=model.rms_error_px,
            n_samples=model.n_samples,
        )
        log.info("Da luu hieu chuan: %s (RMS %.1f px)", path, model.rms_error_px)
        return path

    @staticmethod
    def load(path: Path | str) -> Optional[CalibrationModel]:
        p = Path(path)
        if not p.exists():
            return None
        try:
            with np.load(p) as data:
                return CalibrationModel(
                    coeffs_x=data["coeffs_x"],
                    coeffs_y=data["coeffs_y"],
                    screen_w=int(data["screen_w"]),
                    screen_h=int(data["screen_h"]),
                    rms_error_px=float(data["rms_error_px"]),
                    n_samples=int(data["n_samples"]),
                )
        except Exception as exc:  # file hong / version cu
            log.warning("Khong doc duoc file hieu chuan %s: %s", p, exc)
            return None

    @staticmethod
    def validate(model: CalibrationModel,
                 samples: Sequence[Tuple[float, float, float, float]],
                 max_error_px: float = 80.0) -> Tuple[bool, float]:
        """Kiem tra 5 diem ngau nhien; tra ve (dat?, sai so lon nhat)."""
        worst = 0.0
        for h, v, tx, ty in samples:
            px, py = model.predict(h, v)
            worst = max(worst, float(np.hypot(px - tx, py - ty)))
        return worst <= max_error_px, worst
