# =====================================================================
# tests/test_tts_vieneu.py — TTS tieng Viet + fallback + code-switching
# =====================================================================
from __future__ import annotations

import copy
import sys
import types

import pytest

from core.nlu import NLU
from core.voice.tts_vieneu import VieNeuTTS


def _tts_cfg(base_config, engine="vieneu"):
    cfg = copy.deepcopy(base_config)
    cfg["voice"] = dict(cfg.get("voice", {}))
    cfg["voice"]["tts"] = {"engine": engine, "vieneu_voice": "models/vieneu-voice", "rate": 1.0}
    return cfg


class _FakeVieNeu:
    calls: list = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def speak(self, text):
        _FakeVieNeu.calls.append(text)

    def stop(self):
        pass


class _FakePyttsx3Engine:
    def __init__(self):
        self.said: list = []
        self.rate = None

    def setProperty(self, name, value):
        if name == "rate":
            self.rate = value

    def say(self, text):
        self.said.append(text)

    def runAndWait(self):
        pass

    def stop(self):
        pass


@pytest.fixture()
def fake_vieneu(monkeypatch):
    _FakeVieNeu.calls = []
    mod = types.ModuleType("vieneu")
    mod.VieNeuTTS = _FakeVieNeu
    monkeypatch.setitem(sys.modules, "vieneu", mod)
    return _FakeVieNeu


def test_vieneu_speak_blocking(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("xin chào, tôi là Tiểu Vũ", blocking=True)
    assert fake_vieneu.calls == ["xin chào, tôi là Tiểu Vũ"]


def test_vieneu_speak_async(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("Đã mở YouTube.")
    tts.wait(2.0)
    assert "Đã mở YouTube." in fake_vieneu.calls


def test_code_switching_does_not_raise(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("commit file auth.py rồi merge pull request", blocking=True)
    assert fake_vieneu.calls[-1] == "commit file auth.py rồi merge pull request"


def test_fallback_pyttsx3(base_config, monkeypatch):
    monkeypatch.setitem(sys.modules, "vieneu", None)
    engine = _FakePyttsx3Engine()
    mod = types.ModuleType("pyttsx3")
    mod.init = lambda: engine
    monkeypatch.setitem(sys.modules, "pyttsx3", mod)

    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("xin chào", blocking=True)
    assert engine.said == ["xin chào"]
    assert engine.rate == 200


def test_no_engine_no_crash(base_config, monkeypatch):
    monkeypatch.setitem(sys.modules, "vieneu", None)
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("hello", blocking=True)  # khong raise
    assert tts._backend == "none"


def test_engine_none_disabled(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config, engine="none"))
    tts.speak("khong duoc noi", blocking=False)
    tts.wait(0.5)
    assert fake_vieneu.calls == []


def test_stop_is_safe(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("một câu dài")
    tts.stop()
    tts.wait(1.0)  # khong raise


def test_empty_text_is_ignored(base_config, fake_vieneu):
    tts = VieNeuTTS(_tts_cfg(base_config))
    tts.speak("", blocking=True)
    tts.speak("   ", blocking=True)
    assert fake_vieneu.calls == []


def test_nlu_appends_speak_response(base_config):
    intents = NLU(base_config).parse("mở youtube")
    names = [i.name for i in intents]
    assert names[0] == "open_url"
    assert "speak" in names
    assert intents[-1].payload["text"].startswith("Đã mở")
