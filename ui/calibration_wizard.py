# =====================================================================
# ui/calibration_wizard.py
# Wizard 9 diem: hien tung cham tren toan man hinh, thu 30 frame moi diem,
# fit da thuc bac 2, luu config/calibration_<user>.npz.
# Kiem chung: 5 diem ngau nhien, sai so <= 80px tren 1080p.
# =====================================================================
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from core.calibration import CalibrationStore, grid_points
from core.vision_engine import FaceLandmarks

log = logging.getLogger(__name__)


@dataclass
class CalibrationSession:
    """Thu mau logic (khong mo cua so) de test va tai su dung."""

    store: CalibrationStore
    frames_per_point: int = 30
    points: List[Tuple[float, float]] = field(default_factory=list)
    index: int = 0
    collected: int = 0

    def __post_init__(self):
        if not self.points:
            raise ValueError("Can danh sach diem hieu chuan.")

    @property
    def current_point(self) -> Tuple[float, float]:
        return self.points[min(self.index, len(self.points) - 1)]

    @property
    def done(self) -> bool:
        return self.index >= len(self.points)

    def add_observation(self, h: float, v: float) -> bool:
        """Nap 1 mau cho diem hien tai; True khi diem nay du frame."""
        if self.done:
            return False
        x, y = self.current_point
        self.store.add(h, v, x, y)
        self.collected += 1
        if self.collected >= self.frames_per_point:
            self.index += 1
            self.collected = 0
            return True
        return False


class CalibrationWizard:
    """Mo cua so fullscreen va thu mau tu camera."""

    def __init__(self, tracker, frames_per_point: int = 30,
                 margin: float = 0.08):
        self.tracker = tracker
        self.frames_per_point = int(frames_per_point)
        self.margin = float(margin)
        self.last_error_px: Optional[float] = None

    # ------------------------------------------------------------------
    def run(self, face_provider: Callable[[], Optional[FaceLandmarks]],
            screen_w: int = 1920, screen_h: int = 1080,
            user: str = "default", window: str = "Tiểu Vũ — Calibration") -> bool:
        points = grid_points(screen_w, screen_h, self.margin, n=3)
        store = CalibrationStore()
        session = CalibrationSession(store, self.frames_per_point, points)

        try:
            cv2.namedWindow(window, cv2.WND_PROP_FULLSCREEN)
            cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN)
        except Exception as exc:
            log.warning("Khong mo duoc cua so fullscreen: %s", exc)
            return False

        try:
            while not session.done:
                canvas = np.zeros((screen_h, screen_w, 3), dtype=np.uint8)
                px, py = session.current_point
                cv2.circle(canvas, (int(px), int(py)), 22, (0, 255, 136), -1)
                cv2.circle(canvas, (int(px), int(py)), 34, (0, 120, 60), 2)
                cv2.putText(canvas,
                            f"Nhin vao cham  ({session.collected}/{session.frames_per_point})",
                            (screen_w // 2 - 220, screen_h - 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (220, 220, 220), 2)
                cv2.imshow(window, canvas)
                if (cv2.waitKey(1) & 0xFF) == 27:
                    log.info("Huy hieu chuan bang ESC.")
                    return False

                face = face_provider()
                obs = self.tracker.observe(face, time.time())
                if obs is not None:
                    session.add_observation(obs.h_ratio, obs.v_ratio)
                else:
                    time.sleep(0.02)
        finally:
            cv2.destroyWindow(window)

        model = store.fit(screen_w, screen_h)
        ok, worst = self._validate(store, model, screen_w, screen_h)
        self.last_error_px = worst
        log.info("Hieu chuan xong: RMS %.1f px, sai so xac minh %.1f px (%s)",
                 model.rms_error_px, worst, "OK" if ok else "CAN CALIB LAI")
        store.save(model, user)
        return ok

    # ------------------------------------------------------------------
    @staticmethod
    def _validate(store: CalibrationStore, model, screen_w: int, screen_h: int,
                  n: int = 5) -> Tuple[bool, float]:
        """Lay ngau nhien 5 mau da thu va kiem tra sai so tai diem."""
        samples = list(zip(store._h, store._v, store._x, store._y, strict=False))
        if len(samples) < n:
            return False, float("inf")
        picks = random.sample(samples, n)
        from core.calibration import CalibrationStore as CS

        return CS.validate(model, picks, max_error_px=80.0)
