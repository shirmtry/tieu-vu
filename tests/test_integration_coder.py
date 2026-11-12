# =====================================================================
# tests/test_integration_coder.py — full pipeline (mock external services)
#
# voice transcript -> hybrid STT fallback -> CoderNLU (Ollama mock)
#   -> ActionEvent -> CoderActions -> backend/subprocess mock -> speak
# =====================================================================
from __future__ import annotations

import copy
import queue
import re
from types import SimpleNamespace

from actions.coder_actions import CoderActions
from core.coder_backend import NoopBackend
from core.nlu_coder import CoderNLU
from core.voice_engine import VoiceEngine


def _wrap(name, **args):
    return {"message": {"tool_calls": [{"function": {"name": name, "arguments": args}}]}}


def fake_post(url, payload, timeout):
    text = payload["messages"][-1]["content"]
    if "tạo file" in text.lower():
        match = re.search(r"([\w./\\-]+\.py)", text)
        return _wrap(
            "create_file",
            path=(match.group(1) if match else "main.py"),
            content="print('hello world')",
        )
    return {"message": {"content": "?"}}


def make_cfg(base_config, root):
    cfg = copy.deepcopy(base_config)
    cfg["coder"] = dict(cfg.get("coder", {}), workspace_root=str(root))
    cfg["nlu"] = dict(cfg.get("nlu", {}))
    cfg["nlu"]["coder"] = {
        "enabled": True,
        "model": "qwen2.5-coder:7b",
        "ollama_url": "http://localhost:11434",
        "timeout_sec": 2,
    }
    cfg["voice"] = dict(cfg.get("voice", {}))
    cfg["voice"]["stt"] = {
        "engine": "hybrid",
        "phowhisper_model": str(root / "khong-co-model"),
        "phowhisper_device": "cpu",
        "phowhisper_compute_type": "int8",
    }
    return cfg


class _FakeBackend:
    name = "fake"

    def run(self, prompt, cwd, stream_callback):
        stream_callback("line 1")
        stream_callback("line 2")
        return "đã refactor xong"


def test_voice_to_create_file(base_config, tmp_path):
    cfg = make_cfg(base_config, tmp_path)
    q: queue.Queue = queue.Queue()

    voice = VoiceEngine(cfg, q)
    voice.coder_nlu = CoderNLU(cfg, post=fake_post)
    voice.code_mode = lambda: True
    voice._audio_buffer = bytearray(b"\x00\x00" * 8000)  # PhoWhisper fallback

    voice._flush_command("tạo file hello.py với hello world")
    event = q.get_nowait()
    assert event.name == "create_file"

    actions = CoderActions(cfg, event_queue=q)
    actions.create_file(event.payload["path"], event.payload["content"])
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('hello world')"


def test_run_command_async_pipeline(base_config, tmp_path, monkeypatch):
    cfg = make_cfg(base_config, tmp_path)
    q: queue.Queue = queue.Queue()
    actions = CoderActions(cfg, event_queue=q)

    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr("actions.coder_actions.subprocess.run", fake_run)
    actions.run_command_async("pytest -q")

    event = q.get(timeout=5)
    assert event.name == "speak"
    assert "exit code 0" in event.payload["text"]
    assert seen and seen[0][0] == "pytest"


def test_delegate_pipeline_streams_and_speaks(base_config, tmp_path):
    cfg = make_cfg(base_config, tmp_path)
    q: queue.Queue = queue.Queue()
    actions = CoderActions(cfg, event_queue=q, backend=_FakeBackend())

    actions.delegate_async("refactor auth.py thành async")
    event = q.get(timeout=5)
    assert event.name == "speak"
    assert "refactor xong" in event.payload["text"]


def test_delegate_without_backend_speaks_install_hint(base_config, tmp_path):
    cfg = make_cfg(base_config, tmp_path)
    q: queue.Queue = queue.Queue()
    actions = CoderActions(cfg, event_queue=q, backend=NoopBackend())

    actions.delegate_async("refactor")
    event = q.get(timeout=5)
    assert "OpenCode" in event.payload["text"]
