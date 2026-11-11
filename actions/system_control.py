# =====================================================================
# actions/system_control.py
# Dieu khien he thong Windows:
#   - Am thanh master bang Pycaw (fallback: phim volume).
#   - Alt+Tab, dong tab, chuyen desktop ao, Play/Pause media.
#   - App launcher (mo app mac dinh / theo ten).
# =====================================================================
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import urllib.parse
import webbrowser
from typing import Optional

import pyautogui

log = logging.getLogger(__name__)
pyautogui.PAUSE = 0.0


class VolumeController:
    """Dieu khien am thanh master.

    Uu tien Pycaw (COM endpoint volume) de dat muc TUYET DOI chinh xac.
    Tuong thich ca API cu (device.Activate) lan moi (device.EndpointVolume).
    Neu Pycaw loi -> fallback phim volumeup/volumedown, gui TUNG NAC NHO
    theo do lech tuong doi de muot, khong bi giat cuc.

    Pycaw can COM init trong thread su dung no -> khoi tao lazy, va caller
    (Action Worker) phai goi comtypes.CoInitialize() truoc.
    """

    def __init__(self, config: dict):
        sys_cfg = config.get("system", {})
        # Moi lan bam phim volume Windows thay doi ~2% (tuy he thong).
        self.key_step_percent = float(sys_cfg.get("volume_key_step_percent", 2))
        # Nghi giua cac lan bam de tao cam giac muot (khong don phim).
        self.key_delay = float(sys_cfg.get("volume_key_delay_sec", 0.02))
        self._endpoint = None
        self._failed = False
        self._last_target: Optional[float] = None  # muc tieu truoc (fallback)

    def _ensure_endpoint(self):
        if self._endpoint is not None or self._failed:
            return self._endpoint
        try:
            from comtypes import CoInitialize
            try:
                CoInitialize()
            except Exception:
                pass  # COM co the da init trong thread nay
            from pycaw.pycaw import AudioUtilities
            device = AudioUtilities.GetSpeakers()
            # API moi (pycaw >= 2024): EndpointVolume tra thang interface.
            ep = getattr(device, "EndpointVolume", None)
            if ep is None:
                # API cu: device.Activate(...) -> cast sang con tro.
                from ctypes import POINTER, cast

                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import IAudioEndpointVolume
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                ep = cast(interface, POINTER(IAudioEndpointVolume))
            self._endpoint = ep
            log.info("Pycaw san sang (master volume endpoint).")
        except Exception as exc:
            self._failed = True
            log.warning("Pycaw khong kha dung (%s) -> fallback phim volume.", exc)
        return self._endpoint

    def set_level(self, level: float):
        """level trong [0, 1]. Dat tuyet doi neu Pycaw OK, else phim."""
        level = max(0.0, min(1.0, float(level)))
        ep = self._ensure_endpoint()
        if ep is not None:
            try:
                ep.SetMasterVolumeLevelScalar(level, None)
                self._last_target = level
                return
            except Exception as exc:
                log.error("Loi SetMasterVolumeLevelScalar (%s) -> chuyen phim.", exc)
                self._endpoint = None
                self._failed = True
        self._keys_fallback(level)

    def _keys_fallback(self, level: float):
        """Bam phim volume theo DO LECH TUONG DOI so voi muc tieu truoc.

        Khong can biet am luong thuc te (khong doc duoc khi thieu Pycaw):
        chi can delta giua 2 lan lien tiep -> tung nac nho, muot. Lan dau
        chi dong bo muc tieu, khong bam de tranh nhay cuc.
        """
        if self._last_target is None:
            self._last_target = level
            return
        delta = level - self._last_target
        self._last_target = level
        steps = int(round(abs(delta) * 100.0 / max(self.key_step_percent, 0.5)))
        if steps <= 0:
            return
        key = "volumeup" if delta > 0 else "volumedown"
        for _ in range(min(steps, 25)):
            pyautogui.press(key, _pause=False)
            if self.key_delay > 0:
                time.sleep(self.key_delay)


class SystemController:
    def __init__(self, config: dict):
        self.cfg = config
        self.hotkeys = config.get("hotkeys", {})
        sys_cfg = config.get("system", {})
        self.default_app = str(sys_cfg.get("default_app", "chrome"))
        self.app_paths = sys_cfg.get("app_paths", {}) or {}
        self.volume = VolumeController(config)

    # ------------------------------------------------------------------
    def _hotkey(self, name: str, fallback: list):
        keys = self.hotkeys.get(name, fallback)
        try:
            if len(keys) == 1:
                pyautogui.press(keys[0], _pause=False)
            else:
                pyautogui.hotkey(*keys, _pause=False)
        except Exception as exc:
            log.error("Loi hotkey %s: %s", name, exc)

    # ------------------------------------------------------------------
    def alt_tab(self):
        self._hotkey("alt_tab", ["alt", "tab"])

    def close_tab(self):
        self._hotkey("close_tab", ["ctrl", "w"])

    def play_pause(self):
        self._hotkey("play_pause", ["playpause"])

    def switch_desktop(self, direction: str):
        name = "switch_desktop_left" if direction == "left" else "switch_desktop_right"
        fallback = ["win", "ctrl", "left" if direction == "left" else "right"]
        self._hotkey(name, fallback)

    def set_volume(self, level: float):
        self.volume.set_level(level)

    # ------------------------------------------------------------------
    def open_app(self, name: Optional[str] = None):
        """Mo app theo ten (alias trong config, PATH, thu muc Windows)."""
        name = (name or self.default_app).strip().lower()
        candidate = self.app_paths.get(name)
        try:
            if candidate and os.path.exists(candidate):
                subprocess.Popen([candidate], shell=False)
                log.info("Da mo app: %s", candidate)
                return
            found = shutil.which(name) or shutil.which(name + ".exe")
            if found:
                subprocess.Popen([found], shell=False)
                log.info("Da mo app: %s", found)
                return
            # Thu mo bang lien ket Windows (shell).
            os.startfile(name)  # type: ignore[attr-defined]
            log.info("Da mo app qua shell: %s", name)
        except Exception as exc:
            log.error("Khong mo duoc app '%s': %s", name, exc)

    def open_url(self, url: str):
        try:
            webbrowser.open(url)
            log.info("Mo URL: %s", url)
        except Exception as exc:
            log.error("Loi mo URL: %s", exc)

    def search(self, query: str):
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        self.open_url(url)
