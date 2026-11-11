# =====================================================================
# core/wake_word.py
# Wake word "hey tieu vu".
#   - Uu tien openWakeWord (mo hinh .tflite/.onnx) neu duoc cai.
#   - Fallback: khop van ban Vosk (dung chung micro stream voi VoiceEngine).
# Phan PhraseMatcher la logic thuan, test duoc khong can audio.
# =====================================================================
from __future__ import annotations

import logging
from typing import List

import numpy as np

from .text_utils import fold, normalize

log = logging.getLogger(__name__)


class PhraseMatcher:
    """Khop cum wake word voi van ban STT (chịu lỗi dấu / viết sai)."""

    def __init__(self, phrase: str = "hey tieu vu"):
        self.phrase = phrase
        self.variants = self._build_variants(phrase)

    @staticmethod
    def _build_variants(phrase: str) -> List[str]:
        base = fold(phrase)
        variants = {base}
        variants.add(base.replace("hey ", ""))
        variants.add(base.replace("hey tieu vu", "hey tieu vu oi"))
        variants.add(base.replace("tieu vu", "tieu vu oi"))
        return [v for v in variants if v]

    def matches(self, text: str) -> bool:
        norm = fold(text)
        return any(v in norm for v in self.variants)


class OpenWakeWordDetector:
    """Wrapper openWakeWord (tuy chon). Fallback sang Vosk khi thieu model."""

    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("wake_word", {})
        self.matcher = PhraseMatcher(str(cfg.get("phrase", "hey tieu vu")))
        self.model_paths: List[str] = list(cfg.get("model_paths", []) or [])
        self.threshold = float(cfg.get("threshold", 0.5))
        self._model = None
        self._tried = False

    @property
    def available(self) -> bool:
        if self._model is not None:
            return True
        if self._tried:
            return False
        self._tried = True
        try:
            from openwakeword.model import Model

            kwargs = {}
            if self.model_paths:
                kwargs["wakeword_models"] = self.model_paths
            self._model = Model(**kwargs)
            log.info("openWakeWord san sang (%s)", self.model_paths or "pretrained")
            return True
        except Exception as exc:
            log.info("openWakeWord khong kha dung (%s); dung Vosk fallback.", exc)
            return False

    def process_pcm(self, pcm16: np.ndarray) -> bool:
        """Nhan chunk int16 16kHz; tra ve True neu vuot nguong wake."""
        if not self.available or self._model is None:
            return False
        try:
            scores = self._model.predict(pcm16)
            return any(float(v) >= self.threshold for v in scores.values())
        except Exception as exc:
            log.debug("openWakeWord predict loi: %s", exc)
            return False

    def matches_text(self, text: str) -> bool:
        return self.matcher.matches(text)


def normalize_wake_text(text: str) -> str:
    """Tien ich public: chuan hoa van ban truoc khi so khop."""
    return normalize(text)
