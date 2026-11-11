# =====================================================================
# core/scroll_engine.py
# Cuon o vien man hinh: gaze roi vao 10% tren/duoi + dieu kien pitch dau
# -> cuon voi toc do tang dan 3 -> 15 dong/giay (ramp).
# =====================================================================
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ScrollState:
    active: bool = False
    direction: str = ""            # "up" | "down"
    rate_lps: float = 0.0          # dong/giay hien tai


class EdgeScrollEngine:
    """Bien doi vi tri gaze (px) thanh so dong cuon theo thoi gian."""

    def __init__(self, zone_ratio: float = 0.10, min_rate: float = 3.0,
                 max_rate: float = 15.0, ramp_sec: float = 1.5):
        self.zone = float(zone_ratio)
        self.min_rate = float(min_rate)
        self.max_rate = float(max_rate)
        self.ramp_sec = max(float(ramp_sec), 1e-3)
        self._start: Optional[float] = None
        self._accum = 0.0
        self._last_t: Optional[float] = None
        self._direction = ""
        self.state = ScrollState()

    # ------------------------------------------------------------------
    def reset(self):
        self._start = None
        self._accum = 0.0
        self._last_t = None
        self._direction = ""
        self.state = ScrollState()

    def update(self, gaze_y_px: float, screen_h: int, pitch_ok: bool,
               now: float) -> int:
        """Tra ve so dong cuon (nguyen, am = xuong) trong khoang dt vua qua."""
        if screen_h <= 1 or not pitch_ok:
            self.reset()
            return 0

        top_lim = self.zone * screen_h
        bottom_lim = (1.0 - self.zone) * screen_h
        if gaze_y_px <= top_lim:
            direction = "up"
            depth = 1.0 - max(gaze_y_px, 0.0) / max(top_lim, 1e-6)
        elif gaze_y_px >= bottom_lim:
            direction = "down"
            depth = (gaze_y_px - bottom_lim) / max(screen_h - bottom_lim, 1e-6)
        else:
            self.reset()
            return 0

        if direction != self._direction:
            self._direction = direction
            self._start = now
            self._accum = 0.0
            self._last_t = now

        elapsed = now - (self._start if self._start is not None else now)
        ramp = min(1.0, elapsed / self.ramp_sec)
        depth = max(0.0, min(1.0, depth))
        rate = self.min_rate + (self.max_rate - self.min_rate) * max(ramp, depth * 0.5)

        dt = 0.0 if self._last_t is None else max(now - self._last_t, 0.0)
        self._last_t = now
        self._accum += rate * dt
        lines = int(self._accum)
        if lines:
            self._accum -= lines
        signed = lines if direction == "up" else -lines
        self.state = ScrollState(active=True, direction=direction, rate_lps=rate)
        return signed
