# =====================================================================
# core/voice — cac engine giong noi moi (STT / TTS)
#
# Tach khoi core/voice_engine.py (Vosk streaming) de moi engine co the
# lazy-import dependency rieng va degrade doc lap khi thieu model.
# =====================================================================
from __future__ import annotations

from .stt_phowhisper import PhoWhisperSTT, pcm16_to_float32

__all__ = ["PhoWhisperSTT", "pcm16_to_float32"]
