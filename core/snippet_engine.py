# =====================================================================
# core/snippet_engine.py
# Go tat (text expander): bo dem 12 ky tu tu ban phim, khi gap trigger
# (vd ";addr") thi thay bang noi dung trong config.yaml.
# =====================================================================
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

log = logging.getLogger(__name__)


def _expand_dynamic(text: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    return (text.replace("{date}", now.strftime("%Y-%m-%d"))
                .replace("{time}", now.strftime("%H:%M"))
                .replace("{datetime}", now.strftime("%Y-%m-%d %H:%M")))


class SnippetEngine:
    """Logic thuan: nhan tung ky tu, tra ve (trigger, noi dung) khi khop."""

    def __init__(self, config: dict):
        cfg = config.get("snippets", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.buffer_size = int(cfg.get("buffer_size", 12))
        self.triggers: Dict[str, str] = dict(cfg.get("triggers", {}) or {})
        self._buffer = ""

    def reset(self):
        self._buffer = ""

    @property
    def buffer(self) -> str:
        return self._buffer

    def feed(self, char: str) -> Optional[Tuple[str, str]]:
        """Nap 1 ky tu; tra ve (trigger, expanded) neu vua khop trigger."""
        if not self.enabled or not char:
            return None
        if char in ("\n", "\r", "\t") or len(char) > 1:
            # Ky tu dieu khien / paste: khong the khop trigger an toan.
            self._buffer = ""
            return None
        self._buffer = (self._buffer + char)[-self.buffer_size:]
        for trigger, expansion in self.triggers.items():
            if trigger and self._buffer.endswith(trigger):
                self._buffer = ""
                return trigger, _expand_dynamic(str(expansion))
        return None

    def backspaces_for(self, trigger: str) -> int:
        return len(trigger)


class SnippetListener:
    """Hook ban phim (pynput) -> goi callback khi snippet kich hoat.

    Callback nhan (trigger, expanded). Listener tu gui Backspace de xoa
    trigger va dan noi dung (qua clipboard de ho tro Unicode).
    """

    def __init__(self, engine: SnippetEngine,
                 type_text: Optional[Callable[[str], None]] = None,
                 auto_replace: bool = True):
        self.engine = engine
        self.type_text = type_text
        self.auto_replace = auto_replace
        self._listener = None
        self._lock = threading.Lock()

    def _on_press(self, key):
        try:
            char = key.char
        except AttributeError:
            return
        if not char:
            return
        with self._lock:
            hit = self.engine.feed(char)
        if hit is None:
            return
        trigger, expanded = hit
        log.info("Snippet '%s' -> %d ky tu", trigger, len(expanded))
        if not self.auto_replace or self.type_text is None:
            return
        try:
            import pyautogui

            for _ in range(self.engine.backspaces_for(trigger)):
                pyautogui.press("backspace", _pause=False)
            self.type_text(expanded)
        except Exception as exc:
            log.error("Khong thay duoc snippet: %s", exc)

    def start(self) -> bool:
        if not self.engine.enabled:
            return False
        try:
            from pynput import keyboard

            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
            log.info("Snippet listener da bat (%d trigger).", len(self.engine.triggers))
            return True
        except Exception as exc:
            log.warning("Khong bat duoc snippet listener: %s", exc)
            return False

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


def wait_and_flush(engine: SnippetEngine, timeout: float = 0.05):
    """Tien ich test: cho ngan cho buffer on dinh."""
    time.sleep(timeout)
    return engine.buffer
