# =====================================================================
# core/gaze_estimator.py
# Uoc luong diem nhin tren man hinh:
#   MVP  : ti le iris trong mat (geometric) -> px qua da thuc hieu chuan.
#   v1   : L2CS-Net ONNX (~50MB) lam fallback/thay the neu model co mat.
# Khong bat buoc onnxruntime / model de chay MVP.
# =====================================================================
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .calibration import CalibrationModel, CalibrationStore
from .filters import DeadZone, OneEuroFilter2D
from .vision_engine import (
    CHIN,
    LEFT_EYE_TOP,
    NOSE_TIP,
    RIGHT_EYE_TOP,
    EyeObservation,
    EyeTracker,
    FaceLandmarks,
)

log = logging.getLogger(__name__)


def head_pitch_ok(face: Optional[FaceLandmarks],
                  low: float = 0.30, high: float = 0.75) -> bool:
    """Dieu kien pitch dau cho edge-scroll: mui nam giua vung mat/cam.

    Ti le (nose_y - eye_y) / (chin_y - eye_y) ~ 0.5 khi dau thang; qua
    thap/cao la cuoi/ngua dau -> khong cuon de tranh kich hoat nham.
    """
    if face is None:
        return False
    eye_y = (face.pt(LEFT_EYE_TOP)[1] + face.pt(RIGHT_EYE_TOP)[1]) / 2.0
    chin_y = face.pt(CHIN)[1]
    span = chin_y - eye_y
    if span <= 1e-6:
        return False
    frac = (face.pt(NOSE_TIP)[1] - eye_y) / span
    return bool(low <= frac <= high)


@dataclass
class ScreenGaze:
    """Diem nhin da loc, don vi pixel man hinh."""

    x: float
    y: float
    valid: bool = True
    source: str = "geometric"      # "geometric" | "l2cs"


class L2CSOnnxEstimator:
    """Wrapper L2CS-Net ONNX. Chi kich hoat khi co model + onnxruntime."""

    def __init__(self, model_path: str, input_size: int = 448):
        self.model_path = Path(model_path)
        self.input_size = int(input_size)
        self._session = None
        self._tried = False

    @property
    def available(self) -> bool:
        if self._session is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        if not self.model_path.exists():
            log.info("L2CS model khong ton tai (%s) -> dung geometric.", self.model_path)
            return False
        try:
            import onnxruntime as ort

            self._session = ort.InferenceSession(
                str(self.model_path), providers=["CPUExecutionProvider"])
            log.info("L2CS ONNX san sang: %s", self.model_path)
            return True
        except Exception as exc:
            log.warning("Khong nap duoc L2CS ONNX (%s) -> geometric.", exc)
            return False

    def predict_angles(self, face_bgr: np.ndarray) -> Optional[Tuple[float, float]]:
        """Tra ve (yaw, pitch) rad neu chay duoc, nguoc lai None."""
        if not self.available or self._session is None:
            return None
        try:
            import cv2

            img = cv2.resize(face_bgr, (self.input_size, self.input_size))
            img = img[:, :, ::-1].astype(np.float32) / 255.0
            img = (img - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
                [0.229, 0.224, 0.225], np.float32)
            blob = np.transpose(img, (2, 0, 1))[None].astype(np.float32)
            name = self._session.get_inputs()[0].name
            out = self._session.run(None, {name: blob})[0].ravel()
            yaw, pitch = float(out[0]), float(out[1])
            return yaw, pitch
        except Exception as exc:
            log.debug("L2CS inference loi: %s", exc)
            return None


class GazeEstimator:
    """Pipeline gaze: EyeTracker -> filter -> calibration model -> px."""

    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("gaze", {})
        self.config = config or {}
        self.tracker = EyeTracker(config)
        self.screen_w = int(cfg.get("screen_width", 1920))
        self.screen_h = int(cfg.get("screen_height", 1080))
        self.smoothing = bool(cfg.get("smoothing", True))
        oe = cfg.get("one_euro", {})
        self._filter = OneEuroFilter2D(
            f=float(cfg.get("fps", 30)),
            mincut=float(oe.get("min_cutoff", 1.0)),
            beta=float(oe.get("beta", 0.007)),
            dcut=float(oe.get("d_cutoff", 1.0)),
        )
        dz = cfg.get("dead_zone", {})
        self._deadzone = DeadZone(float(dz.get("px", 8.0)),
                                  float(dz.get("hold_sec", 0.1)))
        self.model: Optional[CalibrationModel] = None
        user = str(cfg.get("user", "default"))
        calib_dir = str(cfg.get("calibration_dir", "config"))
        loaded = CalibrationStore.load(
            CalibrationStore(calib_dir).path_for(user))
        if loaded is not None:
            self.model = loaded
            self.screen_w, self.screen_h = loaded.screen_w, loaded.screen_h
            log.info("Nap hieu chuan gaze: %s (RMS %.1f px)", user, loaded.rms_error_px)

        self.l2cs = L2CSOnnxEstimator(
            str((self.config.get("models", {}) or {}).get(
                "l2cs_onnx", "models/l2cs_net.onnx")))
        self._last: Optional[ScreenGaze] = None

    # ------------------------------------------------------------------
    def set_model(self, model: CalibrationModel):
        self.model = model
        self.screen_w, self.screen_h = model.screen_w, model.screen_h
        self.reset()

    def observe(self, face: Optional[FaceLandmarks],
                timestamp: float) -> Optional[EyeObservation]:
        return self.tracker.observe(face, timestamp)

    # ------------------------------------------------------------------
    def geometric_px(self, obs: EyeObservation) -> Tuple[float, float]:
        """Anh xa h/v -> px. Co hieu chuan thi dung da thuc, khong thi linear."""
        if self.model is not None:
            return self.model.predict(obs.h_ratio, obs.v_ratio)
        x = min(max(obs.h_ratio, 0.0), 1.0) * (self.screen_w - 1)
        y = min(max(obs.v_ratio, 0.0), 1.0) * (self.screen_h - 1)
        return x, y

    def estimate(self, face: Optional[FaceLandmarks],
                 timestamp: float) -> Optional[ScreenGaze]:
        """Tra ve diem nhin da loc (hoac None neu mat khong hop le)."""
        obs = self.observe(face, timestamp)
        if obs is None:
            return None
        x, y = self.geometric_px(obs)
        if self.smoothing:
            x, y = self._filter(float(x), float(y))
            out = self._deadzone(float(x), float(y), timestamp)
            if out is None:
                return self._last
            x, y = out
        gaze = ScreenGaze(x, y, valid=True, source="geometric")
        self._last = gaze
        return gaze

    def reset(self):
        self._filter.reset()
        self._deadzone.reset()
        self._last = None
