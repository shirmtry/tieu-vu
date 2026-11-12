# =====================================================================
# tests/test_stt_phowhisper.py — hybrid STT (PhoWhisper + Vosk fallback)
# =====================================================================
from __future__ import annotations

import copy
import queue
import sys
import time
import types

import numpy as np

from core.voice.stt_phowhisper import PhoWhisperSTT, pcm16_to_float32
from core.voice_engine import VoiceEngine


class _Segment:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    """Gia lap WhisperModel: tra ve 2 segment, ghi lai tham so."""

    instances: list = []

    def __init__(self, model_path, device="cpu", compute_type="int8"):
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type
        self.calls: list = []
        _FakeModel.instances.append(self)

    def transcribe(self, audio, **kwargs):
        self.calls.append((np.asarray(audio), kwargs))
        return [_Segment("xin chào"), _Segment("tiểu vũ")], {"language": "vi"}


def _install_fake_faster_whisper(monkeypatch, model_cls=_FakeModel):
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = model_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)


def _voice_cfg(base_config, engine="hybrid", model_path="models/phowhisper-small"):
    cfg = copy.deepcopy(base_config)
    cfg["voice"] = dict(cfg.get("voice", {}))
    cfg["voice"]["stt"] = {
        "engine": engine,
        "phowhisper_model": str(model_path),
        "phowhisper_device": "cpu",
        "phowhisper_compute_type": "int8",
    }
    return cfg


# ---------------------------------------------------------------------
# PhoWhisperSTT
# ---------------------------------------------------------------------
def test_pcm16_conversion():
    audio = pcm16_to_float32(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    assert audio.dtype == np.float32
    assert audio[0] == 0.0
    assert abs(audio[1] - 0.5) < 1e-3
    assert audio[2] == -1.0


def test_transcribe_returns_text(monkeypatch, tmp_path):
    _install_fake_faster_whisper(monkeypatch)
    stt = PhoWhisperSTT(str(tmp_path))
    audio = np.zeros(16000, dtype=np.int16)
    text = stt.transcribe(audio, 16000)
    assert isinstance(text, str) and text
    assert text == "xin chào tiểu vũ"
    # Audio int16 duoc chuan hoa ve float32 truoc khi vao model.
    sent, kwargs = _FakeModel.instances[-1].calls[-1]
    assert sent.dtype == np.float32
    assert kwargs["language"] == "vi"


def test_transcribe_empty_audio(monkeypatch, tmp_path):
    _install_fake_faster_whisper(monkeypatch)
    stt = PhoWhisperSTT(str(tmp_path))
    assert stt.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""


def test_missing_faster_whisper_degrades(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import -> ImportError
    stt = PhoWhisperSTT(str(tmp_path))
    assert stt.available is False
    assert stt.transcribe(np.zeros(16000, dtype=np.int16), 16000) == ""


def test_missing_model_dir_degrades(monkeypatch, tmp_path):
    _install_fake_faster_whisper(monkeypatch)
    stt = PhoWhisperSTT(str(tmp_path / "khong-ton-tai"))
    assert stt.available is False


def test_latency_5s_audio(monkeypatch, tmp_path):
    class _SlowModel(_FakeModel):
        def transcribe(self, audio, **kwargs):
            time.sleep(0.05)
            return super().transcribe(audio, **kwargs)

    _install_fake_faster_whisper(monkeypatch, _SlowModel)
    stt = PhoWhisperSTT(str(tmp_path))
    audio = np.zeros(5 * 16000, dtype=np.int16)
    t0 = time.perf_counter()
    text = stt.transcribe(audio, 16000)
    elapsed = time.perf_counter() - t0
    assert text
    assert elapsed < 3.0


# ---------------------------------------------------------------------
# VoiceEngine integration
# ---------------------------------------------------------------------
def test_voice_engine_falls_back_to_vosk(monkeypatch, base_config, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    ve = VoiceEngine(_voice_cfg(base_config, model_path=tmp_path), queue.Queue())
    ve._audio_buffer = bytearray(b"\x00\x00" * 8000)  # > 0.3s
    assert ve._finalize_transcript("mở youtube") == "mở youtube"
    # Parser cu (Vosk path) van hieu lenh.
    events = ve._to_events("mở youtube")
    assert any(e.name == "open_url" for e in events)


def test_voice_engine_prefers_phowhisper(monkeypatch, base_config, tmp_path):
    _install_fake_faster_whisper(monkeypatch)
    ve = VoiceEngine(_voice_cfg(base_config, model_path=tmp_path), queue.Queue())
    ve._audio_buffer = bytearray(b"\x00\x00" * 8000)
    assert ve._finalize_transcript("mo youtube") == "xin chào tiểu vũ"


def test_voice_engine_short_buffer_keeps_vosk(monkeypatch, base_config, tmp_path):
    _install_fake_faster_whisper(monkeypatch)
    ve = VoiceEngine(_voice_cfg(base_config, model_path=tmp_path), queue.Queue())
    ve._audio_buffer = bytearray(b"\x00\x00" * 100)  # 0.006s
    assert ve._finalize_transcript("xin chao") == "xin chao"


def test_engine_vosk_disables_phowhisper(base_config):
    ve = VoiceEngine(_voice_cfg(base_config, engine="vosk"), queue.Queue())
    assert ve.phowhisper is None


def test_flush_command_emits_events(monkeypatch, base_config, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    q: queue.Queue = queue.Queue()
    ve = VoiceEngine(_voice_cfg(base_config, model_path=tmp_path), q)
    ve._audio_buffer = bytearray(b"\x00\x00" * 8000)
    ve._flush_command("mở youtube")
    assert ve.last_transcript == "mở youtube"
    assert not q.empty() and q.get_nowait().name == "open_url"
