# =====================================================================
# actions/mouse_control.py
# Dieu khien chuot nang cao:
#   - Anh xa toa do camera -> man hinh (vung active tru margin o bien).
#   - One Euro Filter: loc nhieu ma khong tre (adaptive low-pass).
#   - Click trai / phai, Drag (giau chuot), Scroll.
# =====================================================================
from __future__ import annotations

import logging
import math
import time

import pyautogui

log = logging.getLogger(__name__)

# Tat do tre cua pyautogui de chuot muot (chung ta tu quan ly an toan).
pyautogui.PAUSE = 0.0


# ---------------------------------------------------------------------
# One Euro Filter (Casiez et al., 2012)
# Nguyen ly: cutoff frequency thap khi tay cham (loc nhieu manh), cao khi
# tay di nhanh (giam do tre). Ket qua: chuot muot ma van bam sat tay.
# ---------------------------------------------------------------------
class _LowPass:
    def __init__(self, alpha: float, initial: float = 0.0):
        self.alpha = alpha
        self.y = initial
        self.initialized = False

    def filter(self, x: float) -> float:
        if not self.initialized:
            self.y = x
            self.initialized = True
        else:
            self.y = self.alpha * x + (1.0 - self.alpha) * self.y
        return self.y


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007,
                 d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass(1.0)
        self._dx = _LowPass(1.0)
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        r = 2.0 * math.pi * cutoff * dt
        return r / (r + 1.0)

    def __call__(self, x: float, t: float) -> float:
        if self._t_prev is None:
            dt = 1.0 / 30.0
        else:
            dt = max(t - self._t_prev, 1e-4)
        self._t_prev = t

        # Dao ham (van toc) va loc nhieu cua dao ham.
        d_x = (x - self._x.y) / dt if self._x.initialized else 0.0
        self._dx.alpha = self._alpha(self.d_cutoff, dt)
        ed_x = self._dx.filter(d_x)

        # Cutoff thich nghi: nhanh -> cutoff cao -> it tre.
        cutoff = self.min_cutoff + self.beta * abs(ed_x)
        self._x.alpha = self._alpha(cutoff, dt)
        return self._x.filter(x)

    def reset(self):
        self._t_prev = None
        self._x.initialized = False
        self._dx.initialized = False


class MouseController:
    def __init__(self, config: dict):
        m = config.get("mouse", {})
        self.margin = float(m.get("margin", 0.12))
        self.speed = float(m.get("speed", 1.4))
        self.scroll_step = int(m.get("scroll_step", 3))
        oe = m.get("one_euro", {})
        self._fx = OneEuroFilter(oe.get("min_cutoff", 1.0),
                                 oe.get("beta", 0.007),
                                 oe.get("d_cutoff", 1.0))
        self._fy = OneEuroFilter(oe.get("min_cutoff", 1.0),
                                 oe.get("beta", 0.007),
                                 oe.get("d_cutoff", 1.0))
        pyautogui.FAILSAFE = bool(m.get("failsafe", True))
        self.screen_w, self.screen_h = pyautogui.size()
        self._dragging = False
        log.info("MouseController: man hinh %dx%d, margin=%.2f",
                 self.screen_w, self.screen_h, self.margin)

    # ------------------------------------------------------------------
    def _map(self, v: float, size: int) -> float:
        """Anh xa [margin, 1-margin] -> [0, size], clamp bien."""
        lo, hi = self.margin, 1.0 - self.margin
        norm = (v - lo) / max(hi - lo, 1e-6)
        norm = max(0.0, min(1.0, norm))
        return norm * (size - 1)

    # ------------------------------------------------------------------
    def move(self, x: float, y: float):
        """Di chuyen con tro theo toa do chuan hoa (0..1) cua ngon tro."""
        t = time.monotonic()
        sx = self._fx(self._map(x, self.screen_w), t)
        sy = self._fy(self._map(y, self.screen_h), t)
        try:
            pyautogui.moveTo(int(sx), int(sy), _pause=False)
        except pyautogui.FailSafeException:
            log.warning("PyAutoGUI fail-safe kich hoat (chuot vao goc man hinh).")
        except Exception as exc:
            log.error("Loi di chuyen chuot: %s", exc)

    def reset_filter(self):
        self._fx.reset()
        self._fy.reset()

    # ------------------------------------------------------------------
    def move_screen(self, x: float, y: float):
        """Di chuyen tuyet doi theo pixel man hinh (gaze da loc san)."""
        try:
            pyautogui.moveTo(int(x), int(y), _pause=False)
        except pyautogui.FailSafeException:
            log.warning("PyAutoGUI fail-safe kich hoat.")
        except Exception as exc:
            log.error("Loi move_screen: %s", exc)

    # ------------------------------------------------------------------
    def left_click(self):
        try:
            pyautogui.click(_pause=False)
        except Exception as exc:
            log.error("Loi left_click: %s", exc)

    def double_click(self):
        try:
            pyautogui.doubleClick(_pause=False)
        except Exception as exc:
            log.error("Loi double_click: %s", exc)

    def right_click(self):
        try:
            pyautogui.rightClick(_pause=False)
        except Exception as exc:
            log.error("Loi right_click: %s", exc)

    # ------------------------------------------------------------------
    def drag_start(self):
        if self._dragging:
            return
        try:
            pyautogui.mouseDown(_pause=False)
            self._dragging = True
            log.debug("Drag start (mouse down).")
        except Exception as exc:
            log.error("Loi drag_start: %s", exc)

    def drag_end(self):
        if not self._dragging:
            return
        try:
            pyautogui.mouseUp(_pause=False)
            log.debug("Drag end (mouse up).")
        except Exception as exc:
            log.error("Loi drag_end: %s", exc)
        finally:
            self._dragging = False

    # ------------------------------------------------------------------
    def scroll(self, amount: int):
        """amount > 0: cuon len; amount < 0: cuon xuong."""
        if amount == 0:
            return
        clicks = max(1, abs(amount)) * self.scroll_step
        try:
            pyautogui.scroll(clicks if amount > 0 else -clicks, _pause=False)
        except Exception as exc:
            log.error("Loi scroll: %s", exc)
