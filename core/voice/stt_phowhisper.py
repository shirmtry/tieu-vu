# =====================================================================
# core/voice/stt_phowhisper.py
# PhoWhisper-small offline STT (faster-whisper / CTranslate2).
#
# Vosk van lo wake-word streaming (do tre thap); sau khi wake, PhoWhisper
# transcribe lai toan bo buffer audio de co transcript chinh xac hon.
# Moi dependency deu lazy-import: thieu faster-whisper hay model thi
# class van ton tai, `available` = False, caller fallback ve Vosk.
# =====================================================================
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """PCM int16 little-endian -> float32 [-1, 1] (dinh dang faster-whisper)."""
    if not data:
        return np.zeros(0, dtype=np.float32)
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def _resample(audio: np.ndarray, sr: int, target: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    if sr == target or audio.size < 2:
        return audio
    duration = audio.size / float(sr)
    n_new = max(1, int(round(duration * target)))
    x_old = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_new, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class PhoWhisperSTT:
    """Wrapper faster-whisper cho model PhoWhisper-small (tieng Viet)."""

    def __init__(
        self, model_path: str, device: str = "cpu", compute_type: str = "int8", language: str = "vi"
    ):
        self.model_path = str(model_path)
        self.device = str(device)
        self.compute_type = str(compute_type)
        self.language = str(language)
        self._model = None
        self._tried = False

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._ensure_model() is not None

    def _ensure_model(self):
        """Lazy-load model + faster-whisper; tra None neu khong kha dung."""
        if self._model is not None:
            return self._model
        if self._tried:
            return None
        self._tried = True
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.warning("faster-whisper chua cai (pip install faster-whisper) " "-> fallback Vosk.")
            return None
        if not os.path.isdir(self.model_path):
            log.warning(
                "Khong tim thay model PhoWhisper tai '%s' -> fallback Vosk. "
                "Tai model: xem SOLUTION.md muc cai dat.",
                self.model_path,
            )
            return None
        try:
            self._model = WhisperModel(
                self.model_path, device=self.device, compute_type=self.compute_type
            )
            log.info(
                "PhoWhisper san sang: %s (%s/%s)", self.model_path, self.device, self.compute_type
            )
        except Exception as exc:
            log.warning("Khong load duoc PhoWhisper (%s) -> fallback Vosk.", exc)
            return None
        return self._model

    # ------------------------------------------------------------------
    def transcribe(self, audio_np: np.ndarray, sr: int) -> str:
        """Transcribe buffer audio (int16 hoac float32) -> text tieng Viet.

        Tra '' neu model khong kha dung hoac co loi -> caller giu transcript
        Vosk cu, khong bao gio crash luong voice.
        """
        model = self._ensure_model()
        if model is None:
            return ""
        try:
            arr = np.asarray(audio_np)
            if arr.dtype.kind in ("i", "u"):
                audio = arr.astype(np.float32) / 32768.0
            else:
                audio = arr.astype(np.float32)
            audio = audio.reshape(-1)
            if audio.size == 0:
                return ""
            audio = _resample(audio, int(sr))
            segments, _info = model.transcribe(
                audio, language=self.language, beam_size=5, vad_filter=True
            )
            text = " ".join(str(seg.text).strip() for seg in segments).strip()
            return text
        except Exception as exc:
            log.warning("PhoWhisper transcribe loi: %s", exc)
            return ""

    # ------------------------------------------------------------------
    def warm_up(self) -> bool:
        """Load model truoc (tranh do tre lan dau trong luc dang noi)."""
        return self.available
