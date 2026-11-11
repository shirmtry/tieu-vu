# =====================================================================
# core/filters.py
# Loc nhieu con tro / tin hieu gaze:
#   - OneEuroFilter (Casiez et al., 2012): cutoff thich nghi theo van toc.
#     Cham -> loc manh; nhanh -> giam do tre. Dung cho gaze cursor.
#   - DeadZone: bo qua rung tay < 8px, nhung van cho phep tich luy de
#     khong bi "ket" khi nguoi dung co y di chuyen cham.
# =====================================================================
from __future__ import annotations

import math
import time
from typing import Optional, Tuple


class OneEuroFilter:
    """One Euro Filter 1 chieu, dung f (Hz) co dinh theo dac ta AGENTS.md."""

    def __init__(self, f: float = 30.0, mincut: float = 1.0,
                 beta: float = 0.007, dcut: float = 1.0):
        self.f = float(f)
        self.mincut = float(mincut)
        self.beta = float(beta)
        self.dcut = float(dcut)
        self.x_prev: Optional[float] = None
        self.dx_prev = 0.0

    def _alpha(self, cut: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cut)
        return 1.0 / (1.0 + tau * self.f)

    def __call__(self, x: float) -> float:
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) * self.f
        a_d = self._alpha(self.dcut)
        dx_hat = a_d * dx + (1.0 - a_d) * self.dx_prev
        cut = self.mincut + self.beta * abs(dx_hat)
        a_x = self._alpha(cut)
        x_hat = a_x * x + (1.0 - a_x) * self.x_prev
        self.x_prev, self.dx_prev = x_hat, dx_hat
        return x_hat

    def reset(self):
        self.x_prev = None
        self.dx_prev = 0.0


class OneEuroFilter2D:
    """Boc 2 filter 1D cho toa do man hinh (x, y)."""

    def __init__(self, f: float = 30.0, mincut: float = 1.0,
                 beta: float = 0.007, dcut: float = 1.0,
                 clock=time.monotonic):
        self._fx = OneEuroFilter(f, mincut, beta, dcut)
        self._fy = OneEuroFilter(f, mincut, beta, dcut)
        self._clock = clock
        self._last_t: Optional[float] = None

    def __call__(self, x: float, y: float) -> Tuple[float, float]:
        now = self._clock()
        if self._last_t is not None:
            dt = max(now - self._last_t, 1e-4)
            # Cap nhat tan so thuc te de filter bam kip FPS thay doi.
            self._fx.f = self._fy.f = 1.0 / dt
        self._last_t = now
        return self._fx(x), self._fy(y)

    def reset(self):
        self._fx.reset()
        self._fy.reset()
        self._last_t = None


class DeadZone:
    """Loc rung con tro: bo qua dich chuyen < min_px trong hold_sec.

    Sau khi giu lai du lau, cho phep "tich luy" di chuyen (emit lai vi tri
    hien tai) de nguoi dung di chuyen cham van khong bi ket.
    """

    def __init__(self, min_px: float = 8.0, hold_sec: float = 0.1):
        self.min_px = float(min_px)
        self.hold_sec = float(hold_sec)
        self._anchor: Optional[Tuple[float, float]] = None
        self._anchor_t = 0.0
        self._last: Optional[Tuple[float, float]] = None

    def __call__(self, x: float, y: float, now: Optional[float] = None
                 ) -> Optional[Tuple[float, float]]:
        """Tra ve toa do nen emit, hoac None neu dang trong dead-zone."""
        now = time.monotonic() if now is None else now
        self._last = (x, y)
        if self._anchor is None:
            self._anchor = (x, y)
            self._anchor_t = now
            return self._anchor

        dist = math.hypot(x - self._anchor[0], y - self._anchor[1])
        if dist >= self.min_px:
            self._anchor = (x, y)
            self._anchor_t = now
            return self._anchor
        if now - self._anchor_t >= self.hold_sec:
            # Di chuyen cham nhung deu: emit vi tri hien tai de khong ket.
            self._anchor = (x, y)
            self._anchor_t = now
            return self._anchor
        return None

    def reset(self):
        self._anchor = None
        self._anchor_t = 0.0
        self._last = None
