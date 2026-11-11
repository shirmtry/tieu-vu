# =====================================================================
# ui/virtual_keyboard.py
# Ban phim ao Tkinter: overlay toi, nhan phim bang chuot/gaze dwell.
# Logic layout + nearest_key tach rieng de test khong can Tkinter.
# =====================================================================
from __future__ import annotations

import logging
import math
import threading
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

ROWS: List[str] = [
    "1234567890",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    " ,.-",
]
SPECIAL: List[str] = ["BSP", "SPACE", "ENTER"]


def layout_keys(key_size: int = 52, gap: int = 6, origin: Tuple[int, int] = (20, 70)
                ) -> Dict[str, Tuple[int, int, int, int]]:
    """Tra ve dict phim -> (x1, y1, x2, y2) theo bo cuc QWERTY don gian."""
    x0, y0 = origin
    out: Dict[str, Tuple[int, int, int, int]] = {}
    for r, row in enumerate(ROWS):
        for c, ch in enumerate(row):
            x = x0 + c * (key_size + gap)
            y = y0 + r * (key_size + gap)
            out[ch] = (x, y, x + key_size, y + key_size)
    y = y0 + len(ROWS) * (key_size + gap)
    x = x0
    widths = {"BSP": 2, "SPACE": 4, "ENTER": 2}
    for name in SPECIAL:
        w = widths[name] * (key_size + gap) - gap
        out[name] = (x, y, x + w, y + key_size)
        x += w + gap
    return out


def nearest_key(x: float, y: float,
                keys: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
                max_dist: float = 120.0) -> Optional[str]:
    """Tim phim gan diem gaze nhat (dung cho dwell selection)."""
    keys = keys or layout_keys()
    best, best_d = None, float("inf")
    for name, (x1, y1, x2, y2) in keys.items():
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        d = math.hypot(x - cx, y - cy)
        if d < best_d:
            best, best_d = name, d
    return best if best_d <= max_dist else None


class VirtualKeyboard:
    """Overlay ban phim ao. on_key(nhan) duoc goi cho moi phim."""

    def __init__(self, on_key: Callable[[str], None], enabled: bool = True):
        self.on_key = on_key
        self.enabled = enabled
        self._tk = None
        self._thread: Optional[threading.Thread] = None
        self._keys = layout_keys()

    # ------------------------------------------------------------------
    def _hit(self, x: int, y: int) -> Optional[str]:
        for name, (x1, y1, x2, y2) in self._keys.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None

    def _build(self):
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", 0.92)
        except Exception:
            pass
        width, height = 640, 420
        root.geometry(f"{width}x{height}+60+500")
        root.configure(bg="#111111")
        canvas = tk.Canvas(root, width=width, height=height, bg="#111111",
                           highlightthickness=0)
        canvas.pack()

        def tap(event):
            name = self._hit(event.x, event.y)
            if name:
                self.on_key(name)

        canvas.bind("<Button-1>", tap)
        for name, (x1, y1, x2, y2) in self._keys.items():
            label = {"BSP": "⌫", "SPACE": "space", "ENTER": "⏎"}.get(name, name.upper())
            canvas.create_rectangle(x1, y1, x2, y2, fill="#1E1E1E",
                                    outline="#00FF88", width=1)
            canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label,
                               fill="#DDDDDD", font=("Consolas", 11))
        canvas.create_text(20, 24, anchor="w", fill="#00FF88",
                           font=("Consolas", 13, "bold"), text="Tiểu Vũ — Virtual Keyboard")
        self._tk = root

    def _run(self):
        try:
            self._build()
            self._tk.mainloop()
        except Exception as exc:
            log.warning("Virtual keyboard khong chay duoc: %s", exc)

    def start(self) -> bool:
        if not self.enabled:
            return False
        self._thread = threading.Thread(target=self._run, name="VK", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._tk is not None:
            try:
                self._tk.after(0, self._tk.destroy)
            except Exception:
                pass
            self._tk = None
