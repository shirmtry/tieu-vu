# =====================================================================
# core/click_engine.py
# Chuyen tin hieu mat thanh cu click:
#   - Dwell: giu con tro trong ban kinh R=40px du T=650ms, cooldown 300ms.
#   - Blink: EAR < 0.2 giu > 350ms -> left click; 2 blink lien tiep trong
#     <= 600ms -> double click.
# Logic thuan (khong phu thuoc OS) de test de dang.
# =====================================================================
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .vision_engine import EyeObservation

log = logging.getLogger(__name__)


@dataclass
class DwellState:
    active: bool = False
    progress: float = 0.0          # 0..1 (ve vong HUD)
    clicked: bool = False


class DwellClicker:
    """Theo doi con tro dung yen trong ban kinh R de phat click."""

    def __init__(self, radius_px: float = 40.0, dwell_sec: float = 0.65,
                 cooldown_sec: float = 0.30):
        self.radius = float(radius_px)
        self.dwell = float(dwell_sec)
        self.cooldown = float(cooldown_sec)
        self._anchor: Optional[Tuple[float, float]] = None
        self._start = 0.0
        self._last_click = -1e9
        self.state = DwellState()

    def update(self, x: float, y: float, now: float) -> DwellState:
        if self._anchor is None or math.hypot(
                x - self._anchor[0], y - self._anchor[1]) > self.radius:
            self._anchor = (x, y)
            self._start = now
            self.state = DwellState(active=False, progress=0.0)
            return self.state

        elapsed = now - self._start
        progress = min(1.0, elapsed / self.dwell) if self.dwell > 0 else 1.0
        clicked = False
        if progress >= 1.0 and now - self._last_click >= self.cooldown:
            clicked = True
            self._last_click = now
            # Reset anchor de lan dwell tiep theo phai giu lai tu dau.
            self._anchor = None
            self._start = now
        self.state = DwellState(active=True, progress=progress, clicked=clicked)
        return self.state

    def reset(self):
        self._anchor = None
        self._start = 0.0
        self.state = DwellState()


class BlinkDetector:
    """Nhan dien blink (EAR thap) va phan biet 1 / 2 blink."""

    def __init__(self, ear_threshold: float = 0.20, min_closed_sec: float = 0.35,
                 double_gap_sec: float = 0.60):
        self.ear_threshold = float(ear_threshold)
        self.min_closed = float(min_closed_sec)
        self.double_gap = float(double_gap_sec)
        self._closed_since: Optional[float] = None
        self._last_blink: Optional[float] = None

    def update(self, obs: Optional[EyeObservation],
               now: Optional[float] = None) -> Optional[str]:
        """Tra ve "left_click" | "double_click" | None khi mat mo lai."""
        if obs is None:
            if self._closed_since is not None:
                self._closed_since = None
            return None
        t = obs.timestamp if now is None else now
        closed = obs.ear < self.ear_threshold

        if closed:
            if self._closed_since is None:
                self._closed_since = t
            return None

        if self._closed_since is None:
            return None

        duration = t - self._closed_since
        self._closed_since = None
        if duration < self.min_closed:
            return None

        if self._last_blink is not None and t - self._last_blink <= self.double_gap:
            self._last_blink = None
            return "double_click"
        self._last_blink = t
        return "left_click"

    def reset(self):
        self._closed_since = None
        self._last_blink = None
