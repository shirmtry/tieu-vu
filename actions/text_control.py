# =====================================================================
# actions/text_control.py
# Xu ly van ban & clipboard - giai quyet triet de loi "dan vao bi den thui":
#   Khi copy tu web/Word, clipboard chua nhieu format (HTML, RTF...) kem
#   mau nen. Cach xu ly: doc CF_UNICODETEXT roi GHI LAI clipboard chi voi
#   duy nhat format plain text -> moi dinh dang bi xoa sach.
#
# Dung Win32 API qua ctypes (khong can thu vien ngoai Windows).
# =====================================================================
from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

import pyautogui

log = logging.getLogger(__name__)
pyautogui.PAUSE = 0.0

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    # Khai bao dung kieu 64-bit de tranh truncate handle.
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL


class TextController:
    def __init__(self, config: dict):
        t = config.get("text", {})
        self.settle_sec = float(t.get("clipboard_settle_sec", 0.15))
        self.auto_plain = bool(t.get("auto_plain_on_copy", True))
        self.hotkeys = config.get("hotkeys", {})

    # ------------------------------------------------------------------
    # Clipboard Win32: doc / ghi plain text
    # ------------------------------------------------------------------
    def get_clipboard_text(self) -> str:
        """Doc text thuan tu clipboard (tra ve '' neu khong co text)."""
        if not _IS_WIN:
            return self._pyperclip_get()
        if not _user32.OpenClipboard(None):
            return ""
        try:
            if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return ""
            handle = _user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = _kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                _kernel32.GlobalUnlock(handle)
        finally:
            _user32.CloseClipboard()

    def set_clipboard_text(self, text: str) -> bool:
        """Ghi clipboard CHI voi format plain text (xoa moi format khac)."""
        if not _IS_WIN:
            return self._pyperclip_set(text)
        data = text.encode("utf-16-le") + b"\x00\x00"
        if not _user32.OpenClipboard(None):
            log.warning("Khong mo duoc clipboard (ung dung khac dang giu?).")
            return False
        try:
            _user32.EmptyClipboard()
            handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            ptr = _kernel32.GlobalLock(handle)
            if not ptr:
                return False
            ctypes.memmove(ptr, data, len(data))
            _kernel32.GlobalUnlock(handle)
            # Sau SetClipboardData, he thong so huu bo nho -> khong free.
            if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
                return False
            return True
        finally:
            _user32.CloseClipboard()

    # Fallback da nen tang (pyperclip) neu Win32 loi.
    @staticmethod
    def _pyperclip_get() -> str:
        try:
            import pyperclip
            return pyperclip.paste() or ""
        except Exception:
            return ""

    @staticmethod
    def _pyperclip_set(text: str) -> bool:
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception as exc:
            log.error("pyperclip fallback that bai: %s", exc)
            return False

    def sanitize_clipboard(self) -> bool:
        """Chuyen clipboard hien tai thanh plain text (xoa dinh dang)."""
        text = self.get_clipboard_text()
        if not text:
            return False
        return self.set_clipboard_text(text)

    # ------------------------------------------------------------------
    # Hanh dong cap cao
    # ------------------------------------------------------------------
    def _hotkey(self, name: str, fallback: list):
        keys = self.hotkeys.get(name, fallback)
        try:
            pyautogui.hotkey(*keys, _pause=False)
        except Exception as exc:
            log.error("Loi hotkey %s: %s", name, exc)

    def copy_plain(self):
        """Ctrl+C -> doi clipboard on dinh -> ghi lai plain text."""
        self._hotkey("copy", ["ctrl", "c"])
        time.sleep(self.settle_sec)
        if self.auto_plain:
            if self.sanitize_clipboard():
                log.info("Copy plain text thanh cong (da xoa dinh dang).")
            else:
                log.debug("Khong co text trong clipboard de sanitize.")

    def paste_plain(self):
        """Dam bao clipboard la plain text roi Ctrl+V."""
        self.sanitize_clipboard()
        self._hotkey("paste", ["ctrl", "v"])

    def undo(self):
        self._hotkey("undo", ["ctrl", "z"])

    def redo(self):
        self._hotkey("redo", ["ctrl", "y"])

    def type_text(self, text: str):
        """Dan van ban (ke ca tieng Viet Unicode) vao o dang focus.

        Khong dung pyautogui.write vi no khong go duoc Unicode; thay vao do
        ghi clipboard plain text roi Ctrl+V.
        """
        if not text:
            return
        if self.set_clipboard_text(text):
            time.sleep(0.05)
            self._hotkey("paste", ["ctrl", "v"])
            log.info("Da go %d ky tu qua clipboard.", len(text))
        else:
            log.error("Khong ghi duoc clipboard de go van ban.")
