# =====================================================================
# tests/test_code_mode.py — Mode.CODE + routing voice -> CoderNLU
# =====================================================================
from __future__ import annotations

import copy
import queue

from core.nlu import Intent
from core.state_machine import (
    ActionEvent,
    Mode,
    StateMachine,
    done_transition,
    wake_transition,
)
from core.voice_engine import VoiceEngine


def _voice_cfg(base_config):
    cfg = copy.deepcopy(base_config)
    cfg["voice"] = dict(cfg.get("voice", {}))
    cfg["voice"]["stt"] = dict(cfg["voice"].get("stt", {}), engine="vosk")
    return cfg


class _RuleNLU:
    def __init__(self):
        self.calls = []

    def parse(self, text):
        self.calls.append(text)
        return [Intent("open_url", {"url": "https://x"}, 0.9, "rule")]


class _CoderNLU:
    def __init__(self, event=None):
        self.calls = []
        self.event = event if event is not None else ActionEvent(
            "create_file", {"path": "x.py", "content": "print(1)"}, source="voice")

    def parse(self, text):
        self.calls.append(text)
        return self.event


# ---------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------
def test_code_mode_accepts_voice_only(base_config):
    assert Mode.CODE.accepts_voice is True
    assert Mode.CODE.accepts_gestures is False
    assert Mode.CODE.accepts_gaze is False


def test_state_machine_set_code_mode(base_config):
    sm = StateMachine(copy.deepcopy(base_config))
    assert sm.set_mode(Mode.CODE) is Mode.CODE
    assert sm.set_mode("code") is Mode.CODE
    assert sm.mode.accepts_voice


def test_wake_transition():
    assert wake_transition(Mode.GAZE) is Mode.VOICE
    assert wake_transition(Mode.IDLE) is Mode.VOICE
    assert wake_transition(Mode.VOICE) is None
    assert wake_transition(Mode.CODE) is None   # giu CODE khi dang noi
    assert wake_transition(Mode.FOCUS) is None  # FOCUS van block
    assert wake_transition(Mode.VK) is None


def test_done_transition():
    assert done_transition(Mode.VOICE, Mode.GAZE) is Mode.GAZE
    assert done_transition(Mode.VOICE, Mode.VK) is Mode.GAZE
    assert done_transition(Mode.VOICE, Mode.IDLE) is Mode.IDLE
    assert done_transition(Mode.CODE, Mode.GAZE) is None
    assert done_transition(Mode.GAZE, Mode.GAZE) is None


# ---------------------------------------------------------------------
# Voice routing
# ---------------------------------------------------------------------
def test_code_mode_routes_to_coder_nlu(base_config):
    ve = VoiceEngine(_voice_cfg(base_config), queue.Queue())
    rule, coder = _RuleNLU(), _CoderNLU()
    ve.nlu, ve.coder_nlu = rule, coder
    ve.code_mode = lambda: True
    events = ve._to_events("tạo file x.py")
    assert [e.name for e in events] == ["create_file"]
    assert coder.calls == ["tạo file x.py"]
    assert rule.calls == []


def test_non_code_mode_uses_rule_nlu(base_config):
    ve = VoiceEngine(_voice_cfg(base_config), queue.Queue())
    rule, coder = _RuleNLU(), _CoderNLU()
    ve.nlu, ve.coder_nlu = rule, coder
    ve.code_mode = lambda: False
    events = ve._to_events("mở youtube")
    assert events[0].name == "open_url"
    assert coder.calls == []
    assert rule.calls == ["mở youtube"]


def test_coder_failure_falls_back_to_rules(base_config):
    ve = VoiceEngine(_voice_cfg(base_config), queue.Queue())
    rule = _RuleNLU()
    ve.nlu = rule
    ve.coder_nlu = _CoderNLU(event=None)
    ve.coder_nlu.parse = lambda _t: None
    ve.code_mode = lambda: True
    events = ve._to_events("mở youtube")
    assert events[0].name == "open_url"
    assert rule.calls == ["mở youtube"]


def test_code_mode_gate_accepts_voice(base_config):
    sm = StateMachine(copy.deepcopy(base_config))
    ve = VoiceEngine(_voice_cfg(base_config), queue.Queue())
    ve.gate = lambda: sm.mode.accepts_voice
    assert ve.gate() is False  # IDLE
    sm.set_mode(Mode.CODE)
    assert ve.gate() is True
    sm.set_mode(Mode.FOCUS)
    assert ve.gate() is False
