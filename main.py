# =====================================================================
# main.py — Tiểu Vũ (GazeFlow)
#
# Kiến trúc đa luồng:
#   [Vision]      camera + MediaPipe        -> VisionFrame
#   [Main]        mode + state machine      -> ActionEvent -> action_queue
#   [Gaze]        (trong main loop) iris    -> mouse/click/scroll
#   [Voice]       Vosk streaming            -> NLU -> ActionEvent
#   [ActionWorker] tiêu thụ queue           -> controllers (không block vision)
#   [Snippet]     pynput buffer 12 ký tự    -> text expander
#   [Tray/HUD]    UI phụ trợ (fail-safe)
#
# Modes (độc quyền): IDLE → GAZE → VOICE → VK → FOCUS
# Hotkeys: Ctrl+Alt+G/V/K/F chuyển mode, Ctrl+Alt+P tạm dừng, Ctrl+Alt+Q thoát.
# =====================================================================
from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional

import cv2
import yaml

from actions.mouse_control import MouseController
from actions.system_control import SystemController
from actions.text_control import TextController
from actions.web_agent import WebAgent
from core.autocomplete import AutocompleteEngine
from core.click_engine import BlinkDetector, DwellClicker
from core.gaze_estimator import GazeEstimator, head_pitch_ok
from core.nlu import NLU
from core.scroll_engine import EdgeScrollEngine
from core.snippet_engine import SnippetEngine, SnippetListener
from core.state_machine import ActionEvent, Mode, StateMachine
from core.telemetry import Telemetry
from core.vision_engine import LEFT_IRIS, RIGHT_IRIS, VisionEngine
from core.voice.tts_vieneu import VieNeuTTS
from core.voice_engine import VoiceEngine
from ui.hud import HUDOverlay, draw_dwell_ring
from ui.tray import TrayIcon
from ui.virtual_keyboard import VirtualKeyboard

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("main")


# ---------------------------------------------------------------------
# Config + logging
# ---------------------------------------------------------------------
def load_config() -> dict:
    cfg_path = ROOT / "config.yaml"
    if not cfg_path.exists():
        print("Khong tim thay config.yaml tai", cfg_path)
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def setup_logging(config: dict, dev: bool = False):
    level_name = "DEBUG" if dev else config.get("app", {}).get("log_level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    log_dir = config.get("app", {}).get("log_dir", "")
    if log_dir:
        d = ROOT / log_dir
        d.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(d / "tieu_vu.log", maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


# ---------------------------------------------------------------------
# Action Dispatcher
# ---------------------------------------------------------------------
class ActionDispatcher:
    def __init__(self, config: dict, mouse: MouseController,
                 system: SystemController, text: TextController,
                 web: WebAgent, telemetry: Optional[Telemetry] = None,
                 ui_hooks: Optional[dict] = None, tts=None):
        self.mouse = mouse
        self.system = system
        self.text = text
        self.web = web
        self.telemetry = telemetry
        self.tts = tts
        hooks = ui_hooks or {}
        self._table = {
            "mouse_move": lambda p: self.mouse.move(p["x"], p["y"]),
            "move_screen": lambda p: self.mouse.move_screen(p["x"], p["y"]),
            "left_click": lambda p: self.mouse.left_click(),
            "double_click": lambda p: self.mouse.double_click(),
            "right_click": lambda p: self.mouse.right_click(),
            "drag_start": lambda p: self.mouse.drag_start(),
            "drag_end": lambda p: self.mouse.drag_end(),
            "scroll": lambda p: self.mouse.scroll(int(p.get("amount", 1))),
            "volume": lambda p: self.system.set_volume(float(p["level"])),
            "alt_tab": lambda p: self.system.alt_tab(),
            "close_tab": lambda p: self.system.close_tab(),
            "open_app": lambda p: self.system.open_app(p.get("name")),
            "play_pause": lambda p: self.system.play_pause(),
            "switch_desktop": lambda p: self.system.switch_desktop(p.get("direction", "right")),
            "undo": lambda p: self.text.undo(),
            "redo": lambda p: self.text.redo(),
            "copy_plain": lambda p: self.text.copy_plain(),
            "paste_plain": lambda p: self.text.paste_plain(),
            "type_text": lambda p: self.text.type_text(p.get("text", "")),
            "open_url": lambda p: self.system.open_url(p.get("url", "")),
            "search": lambda p: self.system.search(p.get("query", "")),
            "web_prompt": lambda p: self.web.submit(p.get("prompt", "")),
            "process_email": lambda p: self.web.submit_email(),
            "web_result": lambda p: log.info("Web AI tra ve %d ky tu -> clipboard.",
                                             p.get("chars", 0)),
            "donate_window": lambda p: hooks.get("donate", lambda: None)(),
            "calibrate": lambda p: hooks.get("calibrate", lambda: None)(),
            "wake_toggle": lambda p: log.info("wake_toggle (khong co hanh dong)."),
            "speak": lambda p: self._speak(p.get("text", ""),
                                           bool(p.get("blocking", False))),
        }

    def _speak(self, text: str, blocking: bool = False):
        if self.tts is None:
            log.warning("TTS chua san sang, bo qua: '%s'", text)
            return
        self.tts.speak(text, blocking)

    def dispatch(self, event: ActionEvent):
        handler = self._table.get(event.name)
        if handler is None:
            log.warning("Hanh dong khong hop le: %s", event.name)
            return
        if self.telemetry is not None:
            self.telemetry.log_action(event.name, event.source, event.payload)
        try:
            handler(event.payload)
        except Exception as exc:
            log.exception("Loi thuc thi hanh dong '%s': %s", event.name, exc)


class ActionWorker(threading.Thread):
    def __init__(self, action_queue: "queue.Queue[ActionEvent]",
                 dispatcher: ActionDispatcher, pause_flag: threading.Event):
        super().__init__(name="ActionWorker", daemon=True)
        self.q = action_queue
        self.dispatcher = dispatcher
        self.pause_flag = pause_flag
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        log.info("Action Worker san sang.")
        while not self.stop_event.is_set():
            try:
                event = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.pause_flag.is_set():
                continue
            self.dispatcher.dispatch(event)

    def drain(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


# ---------------------------------------------------------------------
# Tab acceptor cho autocomplete (chỉ hoạt động khi có gợi ý mới)
# ---------------------------------------------------------------------
class TabAcceptor:
    def __init__(self, get_suggestion, on_accept):
        self._get = get_suggestion
        self._accept = on_accept
        self._listener = None

    def _on_press(self, key):
        try:
            from pynput.keyboard import Key
            is_tab = key is Key.tab
        except Exception:
            is_tab = str(key) == "Key.tab"
        if not is_tab:
            return
        suggestion = self._get()
        if suggestion:
            self._accept(suggestion)

    def start(self):
        try:
            from pynput import keyboard

            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
        except Exception as exc:
            log.debug("TabAcceptor khong bat duoc: %s", exc)

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------
def draw_preview(frame, sm: StateMachine, voice: VoiceEngine, paused: bool,
                 fps: float, dwell: float, gaze_px, suggestions: List[str]):
    img = frame.image
    if img is None:
        return None
    img = img.copy()
    h, w = img.shape[:2]
    for hand in frame.hands:
        for (x, y, _) in hand.points:
            cv2.circle(img, (int(x * w), int(y * h)), 3, (0, 255, 0), -1)
    if frame.face is not None and frame.face.has_iris:
        for idx in (LEFT_IRIS, RIGHT_IRIS):
            p = frame.face.pt(idx)
            cv2.circle(img, (int(p[0] * w), int(p[1] * h)), 3, (255, 0, 255), -1)

    if gaze_px is not None and sm.mode is Mode.GAZE:
        gx = int(max(0, min(w - 1, gaze_px[0] * w)))
        gy = int(max(0, min(h - 1, gaze_px[1] * h)))
        draw_dwell_ring(img, (gx, gy), 20, dwell, 3)

    status = "PAUSED" if paused else sm.mode.value
    color = (0, 0, 255) if paused else (0, 255, 255)
    lines = [
        f"Tiểu Vũ | mode={status} | {sm.state.value}",
        f"Hands: {frame.num_hands} | FPS: {fps:.0f} | Dwell: {dwell * 100:.0f}%",
        f"Last: {sm.last_action or '-'}",
        f"Voice: {'CMD' if voice.listening_for_command else 'wake'} | "
        f"'{voice.last_transcript[-28:]}'",
    ]
    for i, txt in enumerate(lines):
        y = 24 + i * 22
        cv2.putText(img, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 3)
        cv2.putText(img, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 1)
    for i, s in enumerate(suggestions[:3]):
        y = h - 70 + i * 22
        cv2.putText(img, ("Tab> " if i == 0 else "     ") + s[:44], (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 220, 120), 1)
    return img


# ---------------------------------------------------------------------
# App
# ---------------------------------------------------------------------
class App:
    def __init__(self, config: dict, dev: bool = False):
        self.config = config
        self.dev = dev
        self.quit_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.action_queue: "queue.Queue[ActionEvent]" = queue.Queue(maxsize=256)

        self.mouse = MouseController(config)
        self.system = SystemController(config)
        self.text = TextController(config)
        self.web = WebAgent(config, self.text, event_queue=self.action_queue)
        self.tts = VieNeuTTS(config)
        tel_cfg = config.get("telemetry", {})
        self.telemetry = (Telemetry(tel_cfg.get("db_path", "logs/telemetry.db"))
                          if tel_cfg.get("enabled", True) else None)
        self.hooks = {
            "donate": self.open_donate,
            "calibrate": self.open_calibration,
        }
        self.dispatcher = ActionDispatcher(
            config, self.mouse, self.system, self.text, self.web,
            telemetry=self.telemetry, ui_hooks=self.hooks, tts=self.tts)
        self.worker = ActionWorker(self.action_queue, self.dispatcher, self.pause_flag)

        self.vision = VisionEngine(config)
        self.sm = StateMachine(config)
        self.voice = VoiceEngine(config, self.action_queue)
        self.nlu = NLU(config)
        self.voice.nlu = self.nlu
        self.voice.gate = lambda: self.sm.mode.accepts_voice
        self.voice.on_wake = self._on_voice_wake
        self.voice.on_command_done = self._on_voice_done

        # Gaze pipeline
        gcfg = config.get("gaze", {})
        self.gaze_enabled = bool(gcfg.get("enabled", True))
        self.gaze = GazeEstimator(config)
        if self.gaze.model is None:
            self.gaze.screen_w, self.gaze.screen_h = self.mouse.screen_w, self.mouse.screen_h
        dwell_cfg = gcfg.get("dwell", {})
        blink_cfg = gcfg.get("blink", {})
        scroll_cfg = gcfg.get("scroll", {})
        self.dwell = DwellClicker(float(dwell_cfg.get("radius_px", 40)),
                                  float(dwell_cfg.get("dwell_sec", 0.65)),
                                  float(dwell_cfg.get("cooldown_sec", 0.30)))
        self.blink = BlinkDetector(float(blink_cfg.get("ear_threshold", 0.20)),
                                   float(blink_cfg.get("min_closed_sec", 0.35)),
                                   float(blink_cfg.get("double_gap_sec", 0.60)))
        self.scroller = EdgeScrollEngine(float(scroll_cfg.get("zone_ratio", 0.10)),
                                         float(scroll_cfg.get("min_rate", 3)),
                                         float(scroll_cfg.get("max_rate", 15)),
                                         float(scroll_cfg.get("ramp_sec", 1.5)))
        self._dwell_progress = 0.0
        self._gaze_px = None

        # Autocomplete + snippets
        self.autocomplete = AutocompleteEngine(config)
        self.snippet_engine = SnippetEngine(config)
        self.snippet_listener = SnippetListener(self.snippet_engine,
                                                type_text=self.text.type_text)
        self._suggestions: List[str] = []
        self._suggestions_at = 0.0
        self._last_transcript = ""
        self.tab_acceptor = TabAcceptor(self._first_suggestion, self._accept_suggestion)

        # UI
        ui_cfg = config.get("ui", {})
        self.hud = HUDOverlay(enabled=bool(ui_cfg.get("hud", True)))
        self.vk = VirtualKeyboard(self._on_vk_key)
        self.tray = (TrayIcon(self.toggle_pause, self.open_calibration,
                              self.open_donate, self.quit, title="Tiểu Vũ")
                     if ui_cfg.get("tray", True) else None)
        self._prev_mode = Mode.IDLE
        self._hotkey_listener = None
        self._vk_started = False
        self._calibrating = False

    # ------------------------------------------------------------------
    # Mode + UI callbacks
    # ------------------------------------------------------------------
    def set_mode(self, mode: Mode):
        self.sm.set_mode(mode)
        self.hud.set_status(mode.value)
        if mode is Mode.VK:
            if not self._vk_started:
                self.vk.start()
                self._vk_started = True
        elif self._vk_started:
            self.vk.stop()
            self._vk_started = False
        log.info("Mode -> %s", mode.value)

    def toggle_mode(self, mode: Mode):
        target = Mode.IDLE if self.sm.mode is mode else mode
        self.set_mode(target)

    def _on_voice_wake(self) -> bool:
        if self.sm.mode in (Mode.VK, Mode.FOCUS):
            return False
        if self.sm.mode is not Mode.VOICE:
            self._prev_mode = self.sm.mode
        self.set_mode(Mode.VOICE)
        return True

    def _on_voice_done(self):
        if self.sm.mode is Mode.VOICE:
            restore = (self._prev_mode
                       if self._prev_mode not in (Mode.VOICE, Mode.VK) else Mode.GAZE)
            self.set_mode(restore)

    def toggle_pause(self):
        if self.pause_flag.is_set():
            self.pause_flag.clear()
            log.info("DA TIEP TUC lai.")
        else:
            self.pause_flag.set()
            self.worker.drain()
            self.mouse.drag_end()
            log.info("DA TAM DUNG. Ctrl+Alt+P de tiep tuc.")

    def quit(self):
        self.quit_flag.set()

    def _on_vk_key(self, name: str):
        mapping = {"BSP": "backspace", "SPACE": "space", "ENTER": "enter"}
        try:
            import pyautogui

            if name in mapping:
                pyautogui.press(mapping[name], _pause=False)
            else:
                pyautogui.write(name, _pause=False)
            if self.telemetry is not None:
                self.telemetry.log_action("vk_key", "vk", {"key": name})
        except Exception as exc:
            log.debug("VK key loi: %s", exc)

    def _first_suggestion(self) -> Optional[str]:
        if not self._suggestions or time.time() - self._suggestions_at > 5.0:
            return None
        return self._suggestions[0]

    def _accept_suggestion(self, suggestion: str):
        text = suggestion
        transcript = self.voice.last_transcript.strip()
        if transcript:
            last = transcript.split()[-1].lower()
            if suggestion.lower().startswith(last) and last:
                text = suggestion[len(last):] if suggestion.lower() != last else ""
        if text:
            self.text.type_text(text)
            if self.telemetry is not None:
                self.telemetry.log_action("autocomplete", "autocomplete",
                                          {"text": text[:40]})
        self._suggestions = []
        self._suggestions_at = 0.0

    # ------------------------------------------------------------------
    # Donate / calibration (chạy thread riêng)
    # ------------------------------------------------------------------
    def open_donate(self):
        def _run():
            try:
                import tkinter as tk

                from ui.donate_window import show_donate_window

                root = tk.Tk()
                root.withdraw()
                show_donate_window(root)
                root.mainloop()
            except Exception as exc:
                log.warning("Khong mo duoc donate window: %s", exc)

        threading.Thread(target=_run, name="Donate", daemon=True).start()

    def open_calibration(self):
        if self._calibrating:
            log.info("Dang hieu chuan, bo qua yeu cau moi.")
            return

        def _run():
            from ui.calibration_wizard import CalibrationWizard

            self._calibrating = True
            try:
                wizard = CalibrationWizard(self.gaze.tracker)
                ok = wizard.run(self._latest_face, self.gaze.screen_w,
                                self.gaze.screen_h,
                                user=str(self.config.get("gaze", {}).get("user", "default")))
                if ok:
                    from core.calibration import CalibrationStore

                    store = CalibrationStore(self.config.get("gaze", {}).get(
                        "calibration_dir", "config"))
                    model = store.load(store.path_for(
                        str(self.config.get("gaze", {}).get("user", "default"))))
                    if model is not None:
                        self.gaze.set_model(model)
                        log.info("Da ap dung hieu chuan moi (RMS %.1f px)",
                                 model.rms_error_px)
            except Exception as exc:
                log.exception("Hieu chuan loi: %s", exc)
            finally:
                self._calibrating = False

        threading.Thread(target=_run, name="Calibration", daemon=True).start()

    def _latest_face(self):
        frame = self.vision.get_latest_frame()
        return frame.face if frame is not None else None

    # ------------------------------------------------------------------
    # Gaze processing (mỗi frame)
    # ------------------------------------------------------------------
    def _process_gaze(self, frame) -> List[ActionEvent]:
        events: List[ActionEvent] = []
        now = frame.timestamp
        if not self.gaze_enabled or self.sm.mode is not Mode.GAZE:
            self._dwell_progress = 0.0
            self._gaze_px = None
            return events

        obs = self.gaze.observe(frame.face, now)
        sg = self.gaze.estimate(frame.face, now)
        if obs is None or sg is None:
            self.dwell.reset()
            self._dwell_progress = 0.0
            self._gaze_px = None
            return events

        self._gaze_px = (sg.x / max(self.gaze.screen_w, 1),
                         sg.y / max(self.gaze.screen_h, 1))
        state = self.dwell.update(sg.x, sg.y, now)
        self._dwell_progress = state.progress
        if state.clicked:
            events.append(ActionEvent("move_screen", {"x": sg.x, "y": sg.y},
                                      source="gaze", timestamp=now))
            events.append(ActionEvent("left_click", {}, source="gaze", timestamp=now))

        blink = self.blink.update(obs, now)
        if blink:
            events.append(ActionEvent("move_screen", {"x": sg.x, "y": sg.y},
                                      source="gaze", timestamp=now))
            events.append(ActionEvent(blink, {}, source="gaze", timestamp=now))

        pitch_ok = head_pitch_ok(frame.face)
        lines = self.scroller.update(sg.y, self.gaze.screen_h, pitch_ok, now)
        if lines:
            events.append(ActionEvent("scroll", {"amount": lines},
                                      source="gaze", timestamp=now))

        # Di chuyển con trỏ mỗi frame (đã lọc One Euro + dead-zone).
        if not state.clicked and not blink:
            events.insert(0, ActionEvent("move_screen", {"x": sg.x, "y": sg.y},
                                         source="gaze", timestamp=now))
        return events

    # ------------------------------------------------------------------
    def _update_autocomplete(self):
        transcript = self.voice.last_transcript
        if transcript != self._last_transcript:
            self._last_transcript = transcript
            self._suggestions = self.autocomplete.suggest(transcript)
            self._suggestions_at = time.time()
        elif time.time() - self._suggestions_at > 5.0 and self._suggestions:
            self._suggestions = []

    # ------------------------------------------------------------------
    def _setup_hotkeys(self):
        try:
            from pynput import keyboard

            self._hotkey_listener = keyboard.GlobalHotKeys({
                "<ctrl>+<alt>+g": lambda: self.toggle_mode(Mode.GAZE),
                "<ctrl>+<alt>+v": lambda: self.toggle_mode(Mode.VOICE),
                "<ctrl>+<alt>+k": lambda: self.toggle_mode(Mode.VK),
                "<ctrl>+<alt>+f": lambda: self.toggle_mode(Mode.FOCUS),
                "<ctrl>+<alt>+p": self.toggle_pause,
                "<ctrl>+<alt>+q": self.quit,
            })
            self._hotkey_listener.start()
            log.info("Hotkeys: Ctrl+Alt+G/V/K/F mode | P pause | Q quit")
        except Exception as exc:
            log.warning("Khong khoi tao duoc hotkey: %s", exc)

    # ------------------------------------------------------------------
    def run(self) -> int:
        self.hud.start()
        if self.tray is not None:
            self.tray.start()
        self._setup_hotkeys()
        self.snippet_listener.start()
        self.tab_acceptor.start()

        self.vision.start()
        self.worker.start()
        self.voice.start()
        self.web.start()

        log.info("San sang | mode=%s | gaze=%s | voice=%s",
                 self.sm.mode.value, self.gaze_enabled,
                 "on" if self.config.get("voice", {}).get("enabled") else "off")

        show_preview = bool(self.config.get("app", {}).get("show_preview", True))
        fps, frames, t0 = 0.0, 0, time.time()
        last_stats = time.time()
        try:
            while not self.quit_flag.is_set():
                frame = self.vision.get_frame_blocking(timeout=0.5)
                if frame is None:
                    if not self.vision.is_running:
                        log.error("VisionEngine da dung (loi camera?): %s",
                                  self.vision.last_error)
                        break
                    continue

                frames += 1
                now = time.time()
                if now - t0 >= 1.0:
                    fps = frames / (now - t0)
                    frames, t0 = 0, now

                events = self.sm.update(frame)
                events.extend(self._process_gaze(frame))
                if not self.pause_flag.is_set():
                    for ev in events:
                        try:
                            self.action_queue.put_nowait(ev)
                        except queue.Full:
                            if ev.name in ("move_screen", "mouse_move"):
                                try:
                                    self.action_queue.get_nowait()
                                    self.action_queue.put_nowait(ev)
                                except queue.Empty:
                                    pass

                self._update_autocomplete()
                self.hud.set_dwell(self._dwell_progress, self._suggestions)

                if now - last_stats >= 60 and self.telemetry is not None:
                    log.info("Telemetry: %s", self.telemetry.stats())
                    last_stats = now

                if show_preview:
                    img = draw_preview(frame, self.sm, self.voice,
                                       self.pause_flag.is_set(), fps,
                                       self._dwell_progress, self._gaze_px,
                                       self._suggestions)
                    if img is not None:
                        cv2.imshow("Tiểu Vũ — GazeFlow", img)
                        if (cv2.waitKey(1) & 0xFF) == 27:
                            self.quit_flag.set()
                            break
                else:
                    time.sleep(0.005)
        except KeyboardInterrupt:
            log.info("Nhan Ctrl+C, dang dung...")
        finally:
            self.shutdown()
        return 0

    def shutdown(self):
        log.info("Dang tat cac thread...")
        self.quit_flag.set()
        self.mouse.drag_end()
        self.vision.stop()
        self.voice.stop()
        self.tts.stop()
        self.web.stop()
        self.worker.stop()
        self.snippet_listener.stop()
        self.tab_acceptor.stop()
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
        if self.tray is not None:
            self.tray.stop()
        self.vk.stop()
        self.hud.stop()
        self.worker.join(timeout=2.0)
        self.voice.join(timeout=2.0)
        self.web.join(timeout=2.0)
        if self.telemetry is not None:
            log.info("Telemetry phien: %s", self.telemetry.stats())
            self.telemetry.close()
        cv2.destroyAllWindows()
        log.info("Da thoat Tiểu Vũ. Tam biet!")


# ---------------------------------------------------------------------
def run_calibration(config: dict) -> int:
    """python main.py --calibrate: hiệu chuẩn 9 điểm rồi thoát."""
    setup_logging(config, dev=True)
    vision = VisionEngine(config)
    vision.start()
    try:
        from core.gaze_estimator import GazeEstimator
        from ui.calibration_wizard import CalibrationWizard

        gaze = GazeEstimator(config)
        wizard = CalibrationWizard(gaze.tracker)
        ok = wizard.run(lambda: (vision.get_latest_frame() or None)
                        and vision.get_latest_frame().face,
                        gaze.screen_w, gaze.screen_h,
                        user=str(config.get("gaze", {}).get("user", "default")))
        log.info("Hieu chuan %s (sai so %.1f px)", "thanh cong" if ok else "THAT BAI",
                 wizard.last_error_px or -1)
        return 0 if ok else 1
    finally:
        vision.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiểu Vũ — GazeFlow")
    parser.add_argument("--dev", action="store_true", help="preview + log DEBUG")
    parser.add_argument("--calibrate", action="store_true",
                        help="chạy hiệu chuẩn 9 điểm rồi thoát")
    parser.add_argument("--no-preview", action="store_true", help="tắt preview camera")
    args = parser.parse_args()

    config = load_config()
    if args.no_preview:
        config.setdefault("app", {})["show_preview"] = False
    if args.calibrate:
        return run_calibration(config)

    setup_logging(config, dev=args.dev)
    log.info("Khoi dong %s ...", config.get("app", {}).get("name", "Tiểu Vũ"))
    return App(config, dev=args.dev).run()


if __name__ == "__main__":
    raise SystemExit(main())
