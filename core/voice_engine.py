# =====================================================================
# core/voice_engine.py
# Tro ly giong noi OFFLINE dung Vosk. Chay trong thread rieng:
#   1. Cho wake word ("Jarvis") - recognizer gioi han grammar de nhanh.
#   2. Sau khi wake: nghe lenh tu do trong command_timeout_sec.
#   3. Phan tich lenh (Viet + Anh) -> day ActionEvent vao hang doi chung.
# =====================================================================
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Callable, List, Optional, Tuple

from .state_machine import ActionEvent
from .text_utils import fold as _fold
from .text_utils import normalize as _normalize

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Fuzzy matching: uu tien rapidfuzz (nhanh, C++), fallback difflib.
# Chi dung ratio (nhay do dai), KHONG partial_ratio: partial cho diem
# ao 100 khi trigger ngan nam trong chuoi dai ("tra" trong "tra cuu"...).
# ---------------------------------------------------------------------
try:
    from rapidfuzz import fuzz

    def _sim(a: str, b: str) -> float:
        """Do tuong dong 0..100 (Indel/LCS, phat nang do dai lech)."""
        return fuzz.ratio(a, b)
except ImportError:  # pragma: no cover - fallback khi thieu rapidfuzz
    import difflib

    def _sim(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio() * 100.0



# ---------------------------------------------------------------------
# Khoi phuc dau cau don gian cho van ban STT (Vosk khong tra dau cau).
# Rule-based, khong can model: viet hoa dau cau, them dau cham cuoi.
# ---------------------------------------------------------------------
def restore_punctuation(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


# Aliases trang web cho lenh "mo ...".
WEB_ALIASES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "facebook": "https://www.facebook.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "deepseek": "https://chat.deepseek.com",
    "chatgpt": "https://chat.openai.com",
}

# ---------------------------------------------------------------------
# Bang intent: moi intent co nhieu bien the trigger. Parser so khop mo
# trigger voi PREFIX cua cau noi, phan con lai la payload.
# Thu tu: intent cu the hon dat truoc (uu tien khi diem bang nhau).
# ---------------------------------------------------------------------
INTENTS: List[Tuple[str, List[str]]] = [
    ("web_prompt", ["hỏi ai", "ask ai", "hỏi trợ lý", "hỏi deepseek"]),
    ("search", ["tìm kiếm", "tra cứu", "tìm giúp", "search", "tìm", "kiếm", "tra"]),
    ("type_text", ["gõ", "nhập", "viết", "type"]),
    ("open", ["mở", "chạy", "khởi động", "mở giúp", "open"]),
]

# Lenh ngan: so khop mo TOAN BO cau (khong co payload).
SHORT_COMMANDS = {
    "dán": "paste_plain", "paste": "paste_plain",
    "sao chép": "copy_plain", "copy": "copy_plain",
    "hoàn tác": "undo", "undo": "undo",
    "làm lại": "redo", "redo": "redo",
    "tạm dừng": "play_pause", "tạm ngưng": "play_pause",
    "phát": "play_pause", "dừng": "play_pause",
    "play": "play_pause", "pause": "play_pause",
    # Xu ly clipboard bang AI (Web Agent / DeepSeek).
    "xử lý email": "process_email", "xử lý mail": "process_email",
    "trả lời email": "process_email", "hỏi deepseek": "process_email",
    "deepseek": "process_email",
    # Donate (SePay VietQR).
    "ủng hộ tiểu vũ": "donate_window", "mở donate": "donate_window",
    "donate": "donate_window", "ủng hộ": "donate_window",
}

# Bang trigger da gop am (tinh 1 lan khi import, do diem dung bang nay).
_INTENTS_FOLDED = [(intent, [_fold(t) for t in triggers]) for intent, triggers in INTENTS]
_SHORT_FOLDED = {_fold(p): a for p, a in SHORT_COMMANDS.items()}


class VoiceEngine(threading.Thread):
    """Thread lang nghe micro lien tuc, khong block vision hay actions."""

    def __init__(self, config: dict, event_queue: "queue.Queue[ActionEvent]"):
        super().__init__(name="VoiceEngine", daemon=True)
        self.cfg = config.get("voice", {})
        self.event_queue = event_queue
        self.stop_event = threading.Event()
        self.enabled = bool(self.cfg.get("enabled", True))
        # Ho tro nhieu wake word, phan cach bang dau phay.
        self.wake_words = [w.strip().lower() for w in
                           str(self.cfg.get("wake_word", "jarvis")).split(",") if w.strip()]
        self.wake_word = self.wake_words[0] if self.wake_words else "jarvis"
        self.command_timeout = float(self.cfg.get("command_timeout_sec", 6.0))
        self.sample_rate = int(self.cfg.get("sample_rate", 16000))
        self.model_path = str(self.cfg.get("model_path", "models/vosk-model-vn-0.4"))
        # Nguong so khop mo (0..100). Thap = de nhan lenh nhung de nham.
        self.fuzzy_threshold = float(self.cfg.get("fuzzy_threshold", 70))
        self.short_threshold = float(self.cfg.get("short_threshold", 72))
        self.app_paths = (config.get("system", {}).get("app_paths", {}) or {})
        self.last_transcript: str = ""       # phuc vu HUD
        self.listening_for_command = False
        # Callback/Hook (main.py gan vao):
        self.nlu = None                      # core.nlu.NLU | None
        self.gate: Optional[Callable[[], bool]] = None
        self.on_wake: Optional[Callable[[], bool]] = None
        self.on_command_done: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    def stop(self):
        self.stop_event.set()

    # ------------------------------------------------------------------
    def run(self):
        if not self.enabled:
            log.info("VoiceEngine bi tat trong config.")
            return
        try:
            import sounddevice as sd
            import vosk
        except ImportError as exc:
            log.error("Thieu thu vien voice (%s). Cai: pip install vosk sounddevice", exc)
            return

        if not os.path.isdir(self.model_path):
            log.error("Khong tim thay model Vosk tai '%s'. Xem README muc 4 "
                      "de tai model (giai nen vao thu muc models/).", self.model_path)
            return

        try:
            vosk.SetLogLevel(-1)
            model = vosk.Model(self.model_path)
            # Grammar chi chua wake word + [unk]: nhan dien wake nhanh, it CPU.
            wake_rec = vosk.KaldiRecognizer(
                model, self.sample_rate,
                json.dumps(self.wake_words + ["[unk]"], ensure_ascii=False))
            # Recognizer tu do cho lenh sau khi wake.
            cmd_rec = vosk.KaldiRecognizer(model, self.sample_rate)
        except Exception as exc:
            log.exception("Loi khoi tao Vosk: %s", exc)
            return

        audio_q: "queue.Queue[bytes]" = queue.Queue()

        def _callback(indata, frames, time_info, status):
            if status:
                log.debug("sounddevice status: %s", status)
            audio_q.put(bytes(indata))

        device = self.cfg.get("device_index", -1)
        device = None if device is None or int(device) < 0 else int(device)
        try:
            stream = sd.RawInputStream(
                samplerate=self.sample_rate, blocksize=8000, device=device,
                dtype="int16", channels=1, callback=_callback)
        except Exception as exc:
            log.exception("Khong mo duoc micro: %s", exc)
            return

        log.info("VoiceEngine san sang. Wake word: %s", ", ".join(self.wake_words))
        deadline = 0.0
        with stream:
            while not self.stop_event.is_set():
                try:
                    data = audio_q.get(timeout=0.3)
                except queue.Empty:
                    # Het thoi gian cho lenh -> quay ve che do wake.
                    if self.listening_for_command and time.time() > deadline:
                        log.info("Het gio cho lenh, quay ve wake word.")
                        self._end_command_mode(cmd_rec)
                    continue

                try:
                    if not self.listening_for_command:
                        if self._detect_wake(wake_rec, data):
                            if self.on_wake is not None and not self.on_wake():
                                wake_rec.Reset()
                                continue
                            self._enter_command_mode(cmd_rec)
                            deadline = time.time() + self.command_timeout
                    else:
                        if time.time() > deadline:
                            self._end_command_mode(cmd_rec)
                            continue
                        if cmd_rec.AcceptWaveform(data):
                            text = json.loads(cmd_rec.Result()).get("text", "").strip()
                            if text:
                                self.last_transcript = text
                                log.info("Lenh giong noi: '%s'", text)
                                allowed = self.gate is None or self.gate()
                                if allowed:
                                    for ev in self._to_events(text):
                                        self.event_queue.put(ev)
                                else:
                                    log.info("Bo qua lenh: mode hien tai khong nhan voice.")
                            # Nghe xong mot lenh -> quay ve wake (kem beep).
                            self._end_command_mode(cmd_rec)
                except Exception as exc:
                    log.exception("Loi xu ly audio: %s", exc)
        log.info("VoiceEngine da dung.")

    # ------------------------------------------------------------------
    def _detect_wake(self, rec, data: bytes) -> bool:
        """Kiem tra wake word trong ca partial lan final result."""
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "").lower()
            return any(w in text for w in self.wake_words)
        partial = json.loads(rec.PartialResult()).get("partial", "").lower()
        return any(w in partial for w in self.wake_words)

    def _enter_command_mode(self, cmd_rec):
        self.listening_for_command = True
        cmd_rec.Reset()
        log.info("Da wake! Dang nghe lenh...")
        # Beep di len: bao hieu BAT DAU ghi am lenh.
        self._beep(660, 90)
        self._beep(880, 90)

    def _end_command_mode(self, cmd_rec):
        """Ket thuc phien nghe lenh: reset recognizer + beep di xuong."""
        self.listening_for_command = False
        cmd_rec.Reset()
        # Beep tram: bao hieu DA NGHE XONG (thuc thi hoac het gio).
        self._beep(440, 130)
        if self.on_command_done is not None:
            try:
                self.on_command_done()
            except Exception:
                log.debug("on_command_done loi", exc_info=True)

    # ------------------------------------------------------------------
    def _to_events(self, text: str) -> List[ActionEvent]:
        """NLU rule/LLM truoc; neu khong hieu thi dung parser cu."""
        if self.nlu is not None:
            try:
                intents = self.nlu.parse(text)
            except Exception:
                log.debug("NLU loi", exc_info=True)
                intents = []
            if intents:
                return [ActionEvent(i.name, dict(i.payload), source="voice")
                        for i in intents]
        return self.parse_command(text)

    @staticmethod
    def _beep(freq: int, ms: int):
        """Am bao hieu chi tren Windows; loi thi bo qua, khong crash."""
        try:
            import winsound
            winsound.Beep(freq, ms)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Phan tich lenh -> ActionEvent. So khop MO (fuzzy) de chiu loi
    # Vosk nghe nham 1-2 ky tu / sai dau ("tính thời tiết" van ra search).
    # ------------------------------------------------------------------
    def parse_command(self, text: str) -> List[ActionEvent]:
        words = _normalize(text).split()      # payload giu nguyen (bo dau)
        folded = _fold(text).split()          # cham diem tren chuoi da gop am
        events: List[ActionEvent] = []

        def emit(action: str, **payload):
            events.append(ActionEvent(action, payload, source="voice"))

        if not words:
            return events

        norm = " ".join(folded)
        # --- Buoc 0: lenh ngan khop CHINH XAC toan cau -> uu tien tuyet doi.
        # Tranh "tra loi email" bi nuot boi trigger "tra" (search).
        if norm in _SHORT_FOLDED:
            action = _SHORT_FOLDED[norm]
            log.info("Lenh: '%s' -> %s (exact)", text, action)
            emit(action)
            return events

        # --- Buoc 1: khop trigger voi PREFIX cua cau (cua so k-1..k+1 tu).
        # Diem = do tuong dong trigger vs prefix; payload = phan con lai.
        best = None  # (score, so_tu_trigger, -n, intent, payload_words)
        for intent, triggers in _INTENTS_FOLDED:
            for trigger_norm in triggers:
                k = len(trigger_norm.split())
                for n in {max(1, k - 1), k, min(len(folded), k + 1)}:
                    if n > len(folded):
                        continue
                    payload = words[n:]
                    if not payload:
                        continue  # trigger phai co phan du lieu theo sau
                    prefix = " ".join(folded[:n])
                    score = 100.0 if prefix == trigger_norm else _sim(trigger_norm, prefix)
                    if score < self.fuzzy_threshold:
                        continue
                    key = (score, k, -n, intent, payload)
                    if best is None or key[:3] > best[:3]:
                        best = key
        prefix_score = best[0] if best else 0.0

        # --- Buoc 2: lenh ngan, so khop mo TOAN BO cau.
        best_short, short_score = None, 0.0
        for phrase, action in _SHORT_FOLDED.items():
            score = _sim(phrase, norm)
            if score > short_score:
                best_short, short_score = action, score

        # Lenh ngan thang khi diem cao hon prefix (vd "tam dung" 100
        # phai thang "tim"~"tam" 66 -> play_pause, khong phai search).
        if best_short and short_score >= self.short_threshold and short_score > prefix_score:
            log.info("Fuzzy: '%s' -> %s (%.0f)", text, best_short, short_score)
            emit(best_short)
            return events

        if best is not None:
            _, _, _, intent, payload = best
            payload_text = " ".join(payload)
            if intent == "open":
                self._emit_open(payload_text, emit)
            elif intent == "search":
                emit("search", query=payload_text)
            elif intent == "type_text":
                emit("type_text", text=restore_punctuation(payload_text))
            elif intent == "web_prompt":
                emit("web_prompt", prompt=payload_text)
            log.info("Fuzzy: '%s' -> %s (%s)", text, intent, payload_text)
            return events

        log.warning("Khong hieu lenh: '%s'", text)
        return events

    def _emit_open(self, target: str, emit):
        """'mo/chay X': khop mo X voi alias web + ten app trong config."""
        candidates = list(WEB_ALIASES.keys()) + [str(k) for k in self.app_paths.keys()]
        target_folded = _fold(target)
        best_name, best_score = None, 0.0
        for name in candidates:
            score = _sim(_fold(name), target_folded)
            if score > best_score:
                best_name, best_score = name, score
        if best_name is not None and best_score >= 70.0:
            if best_name in WEB_ALIASES:
                emit("open_url", url=WEB_ALIASES[best_name])
            else:
                emit("open_app", name=best_name)
        else:
            # Khong ro dich -> van mo app theo ten tho (he dieu hanh tu tim).
            emit("open_app", name=target)
