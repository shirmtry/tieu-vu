# =====================================================================
# core/voice/tts_vieneu.py
# TTS tieng Viet: VieNeu-TTS (uu tien), fallback pyttsx3 voice he thong.
#
# - speak() mac dinh KHONG block: day text vao queue, worker thread tu noi.
# - stop() ngat giua chung (barge-in khi user noi chen).
# - Code-switching: text giu nguyen token tieng Anh ("commit", "merge"...).
# - Moi dependency lazy-import; thieu het thi no-op, khong crash.
# =====================================================================
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)


class VieNeuTTS:
    """Adapter thong nhat cho VieNeu-TTS / pyttsx3."""

    def __init__(self, config: dict):
        cfg = config.get("voice", {}).get("tts", {}) or {}
        self.engine_name = str(cfg.get("engine", "vieneu")).lower()
        self.voice_dir = str(cfg.get("vieneu_voice", "models/vieneu-voice"))
        self.rate = float(cfg.get("rate", 1.0))
        self._backend: Optional[str] = None  # "vieneu" | "pyttsx3" | "none"
        self._engine = None
        self._init_lock = threading.Lock()
        self._say_lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Khoi tao engine (lazy, lan dau speak)
    # ------------------------------------------------------------------
    def _ensure_engine(self):
        if self._backend is not None:
            return self._backend
        with self._init_lock:
            if self._backend is not None:
                return self._backend
            self._backend = "none"
            if self.engine_name == "none":
                log.info("TTS bi tat trong config.")
                return self._backend
            if self.engine_name == "vieneu" and self._try_vieneu():
                self._backend = "vieneu"
                return self._backend
            if self._try_pyttsx3():
                self._backend = "pyttsx3"
                return self._backend
            log.warning("Khong co TTS engine kha dung -> chi hien text.")
            return self._backend

    def _try_vieneu(self) -> bool:
        try:
            import vieneu

            cls = getattr(vieneu, "VieNeuTTS", None)
            if cls is None:
                raise ImportError("vieneu.VieNeuTTS khong ton tai")
            try:
                self._engine = cls(voice_dir=self.voice_dir)
            except TypeError:
                try:
                    self._engine = cls(self.voice_dir)
                except TypeError:
                    self._engine = cls()
            log.info("VieNeu-TTS san sang (%s).", self.voice_dir)
            return True
        except Exception as exc:
            log.info("VieNeu khong kha dung (%s).", exc)
            return False

    def _try_pyttsx3(self) -> bool:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", int(200 * self.rate))
            except Exception:
                pass
            self._engine = engine
            log.info("TTS fallback pyttsx3 san sang.")
            return True
        except Exception as exc:
            log.info("pyttsx3 khong kha dung (%s).", exc)
            return False

    # ------------------------------------------------------------------
    # API cong khai
    # ------------------------------------------------------------------
    def speak(self, text: str, blocking: bool = False) -> None:
        """Noi text. Mac dinh queue vao worker thread (khong block caller)."""
        text = str(text or "").strip()
        if not text:
            return
        if self._ensure_engine() == "none":
            return
        if blocking:
            self._say(text)
            return
        self._ensure_worker()
        self._queue.put(text)

    def stop(self) -> None:
        """Ngat cau dang noi + xoa queue (barge-in)."""
        self._stop_event.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        if self._backend == "pyttsx3" and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
        elif self._backend == "vieneu" and self._engine is not None:
            stop_fn = getattr(self._engine, "stop", None)
            if callable(stop_fn):
                try:
                    stop_fn()
                except Exception:
                    pass

    def wait(self, timeout: Optional[float] = None) -> None:
        """Cho den khi queue noi xong (chu yeu cho test/shutdown)."""
        if self._worker is None:
            return
        start = time.monotonic()
        while self._queue.unfinished_tasks:
            if timeout is not None and time.monotonic() - start >= timeout:
                return
            time.sleep(0.01)

    # ------------------------------------------------------------------
    # Noi that
    # ------------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, name="VieNeuTTS", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._stop_event.is_set():
                self._queue.task_done()
                break
            try:
                self._say(text)
            finally:
                self._queue.task_done()

    def _say(self, text: str) -> None:
        backend = self._ensure_engine()
        if backend == "none" or self._engine is None:
            return
        with self._say_lock:
            try:
                if backend == "vieneu":
                    fn = getattr(self._engine, "speak", None)
                    if not callable(fn):
                        fn = getattr(self._engine, "infer", None)
                    if callable(fn):
                        fn(text)
                else:
                    self._engine.say(text)
                    self._engine.runAndWait()
            except Exception as exc:
                log.warning("TTS loi khi noi: %s", exc)
