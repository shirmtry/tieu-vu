# =====================================================================
# ui/tray.py
# Icon khay he thong (pystray) + menu: Tam dung, Hieu chuan, Donate, Thoat.
# pystray/PIL la tuy chon: thieu thi app van chay (chi log warning).
# =====================================================================
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)


def _make_icon_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (10, 10, 10, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), outline=(0, 255, 136, 255), width=4)
    draw.ellipse((24, 24, 40, 40), fill=(0, 255, 136, 255))
    draw.arc((14, 14, 50, 50), 200, 340, fill=(0, 200, 255, 255), width=3)
    return img


class TrayIcon:
    """Boc pystray; callback chay trong thread tray (pystray lo thread)."""

    def __init__(self, on_pause: Callable[[], None],
                 on_calibrate: Callable[[], None],
                 on_donate: Callable[[], None],
                 on_quit: Callable[[], None],
                 mode_callback: Optional[Callable[[str], None]] = None,
                 get_current_mode: Optional[Callable[[], str]] = None,
                 title: str = "Tiểu Vũ"):
        self.on_pause = on_pause
        self.on_calibrate = on_calibrate
        self.on_donate = on_donate
        self.on_quit = on_quit
        self.mode_callback = mode_callback
        self.get_current_mode = get_current_mode or (lambda: "IDLE")
        self.title = title
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    def _set_mode(self, name: str):
        if self.mode_callback is None:
            return
        try:
            self.mode_callback(name)
        except Exception as exc:
            log.warning("Tray doi mode '%s' loi: %s", name, exc)

    def _build_menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Chế độ: {self.get_current_mode()}",
                None, enabled=False),
            pystray.MenuItem("💤  IDLE (Tắt AI)", lambda: self._set_mode("IDLE")),
            pystray.MenuItem("👁  GAZE (Nhìn bằng mắt)",
                             lambda: self._set_mode("GAZE")),
            pystray.MenuItem("🎯  VOICE_CLICK (Nói để click)",
                             lambda: self._set_mode("VOICE_CLICK")),
            pystray.MenuItem("💻  CODE (Voice Coder)",
                             lambda: self._set_mode("CODE")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏸  Tạm dừng / Tiếp tục", lambda: self.on_pause()),
            pystray.MenuItem("🎯  Hiệu chuẩn gaze", lambda: self.on_calibrate()),
            pystray.MenuItem("❤️  Donate — SePay VietQR", lambda: self.on_donate()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát", lambda: self.on_quit()),
        )

    def _run(self):
        try:
            import pystray

            self._icon = pystray.Icon(
                "tieu_vu", _make_icon_image(), self.title, self._build_menu())
            self._icon.run()
        except Exception as exc:
            log.warning("Tray icon khong chay duoc: %s", exc)

    # ------------------------------------------------------------------
    def start(self) -> bool:
        try:
            import pystray  # noqa: F401
        except Exception as exc:
            log.info("pystray khong kha dung (%s); bo qua tray.", exc)
            return False
        self._thread = threading.Thread(target=self._run, name="Tray", daemon=True)
        self._thread.start()
        return True

    def update_title(self, title: str):
        """Cap nhat tooltip (vi du 'Tiểu Vũ - VOICE_CLICK')."""
        self.title = title
        if self._icon is None:
            return
        try:
            self._icon.title = title
            self._icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: Optional[str] = None):
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title or self.title)
        except Exception:
            pass

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
