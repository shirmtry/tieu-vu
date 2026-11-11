# =====================================================================
# ui/hud.py
# HUD (heads-up display):
#   - Vong dwell do -> xanh khi giu mat de click (ve bang OpenCV tren preview).
#   - Overlay Tkinter trong suot: trang thai mode, goi y autocomplete.
# Moi thu deu fail-safe: thieu tkinter / loi hien thi chi log warning.
# =====================================================================
from __future__ import annotations

import logging
import threading
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Ve vong dwell tren anh BGR (dung trong preview, khong can Tkinter)
# ---------------------------------------------------------------------
def ring_color(progress: float) -> Tuple[int, int, int]:
    """Do (0) -> vang -> xanh la (1) theo tien do dwell."""
    p = max(0.0, min(1.0, float(progress)))
    if p < 0.5:
        r, g = 255, int(255 * (p / 0.5))
    else:
        r, g = int(255 * (1.0 - (p - 0.5) / 0.5)), 255
    return (0, g, r)  # BGR


def draw_dwell_ring(img: np.ndarray, center: Tuple[int, int], radius: int,
                    progress: float, thickness: int = 4) -> np.ndarray:
    """Ve vong tron tien do dwell len anh (in-place) va tra ve anh."""
    p = max(0.0, min(1.0, float(progress)))
    cv2.circle(img, center, radius, (60, 60, 60), thickness)
    if p > 0:
        cv2.ellipse(img, center, (radius, radius), -90, 0,
                    int(360 * p), ring_color(p), thickness)
    return img


def draw_autocomplete(img: np.ndarray, suggestions: Sequence[str],
                      origin: Tuple[int, int] = (10, 90)) -> np.ndarray:
    x0, y0 = origin
    for i, text in enumerate(suggestions[:3]):
        y = y0 + i * 26
        cv2.rectangle(img, (x0 - 4, y - 18), (x0 + 360, y + 6), (30, 30, 30), -1)
        prefix = "Tab> " if i == 0 else "     "
        cv2.putText(img, prefix + text[:48], (x0, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1)
    return img


# ---------------------------------------------------------------------
# Overlay Tkinter (tuy chon)
# ---------------------------------------------------------------------
class HUDOverlay:
    """Cua so HUD trong suot, luon noi tren cung.

    Cac cap nhat den tu thread khac duoc dua vao Tk qua `after` an toan.
    """

    def __init__(self, width: int = 520, height: int = 140,
                 x: int = 40, y: int = 40, enabled: bool = True):
        self.enabled = bool(enabled)
        self.width, self.height = width, height
        self.x, self.y = x, y
        self._tk = None
        self._canvas = None
        self._thread: Optional[threading.Thread] = None
        self._status = "IDLE"
        self._suggestions: List[str] = []
        self._dwell = 0.0

    # ------------------------------------------------------------------
    def _build(self):
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-transparentcolor", "#010101")
        except Exception:
            pass
        root.configure(bg="#010101")
        root.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")
        canvas = tk.Canvas(root, width=self.width, height=self.height,
                           bg="#010101", highlightthickness=0)
        canvas.pack()
        canvas.create_text(12, 16, anchor="w", fill="#00FF88",
                           font=("Consolas", 13, "bold"), text="Tiểu Vũ  •  IDLE",
                           tags="status")
        canvas.create_text(12, 44, anchor="w", fill="#BBBBBB",
                           font=("Consolas", 10), text="", tags="sugg")
        canvas.create_oval(460, 30, 500, 70, outline="#333", width=4, tags="ring")
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        self._tk, self._canvas = root, canvas

    def _apply(self):
        if self._canvas is None:
            return
        self._canvas.itemconfigure("status", text=f"Tiểu Vũ  •  {self._status}")
        text = "\n".join(f"Tab> {s}" if i == 0 else f"     {s}"
                         for i, s in enumerate(self._suggestions[:3]))
        self._canvas.itemconfigure("sugg", text=text)
        color = "#%02x%02x%02x" % (ring_color(self._dwell)[2],
                                   ring_color(self._dwell)[1],
                                   ring_color(self._dwell)[0])
        self._canvas.itemconfigure("ring", outline=color)

    def _run(self):
        try:
            self._build()
            self._tk.mainloop()
        except Exception as exc:
            log.warning("HUD overlay khong chay duoc: %s", exc)

    # ------------------------------------------------------------------
    def start(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._thread = threading.Thread(target=self._run, name="HUD", daemon=True)
            self._thread.start()
            return True
        except Exception as exc:
            log.warning("Khong tao duoc HUD: %s", exc)
            return False

    def _post(self, fn):
        if self._tk is None:
            return
        try:
            self._tk.after(0, fn)
        except Exception:
            pass

    def set_status(self, status: str):
        self._status = status
        self._post(self._apply)

    def set_dwell(self, progress: float, suggestions: Optional[List[str]] = None):
        self._dwell = float(progress)
        if suggestions is not None:
            self._suggestions = list(suggestions)
        self._post(self._apply)

    def stop(self):
        if self._tk is not None:
            try:
                self._tk.after(0, self._tk.destroy)
            except Exception:
                pass
            self._tk = None
            self._canvas = None
