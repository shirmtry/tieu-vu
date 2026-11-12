# =====================================================================
# tests/test_coder_backend.py — OpenCode / Aider / Noop backend
# =====================================================================
from __future__ import annotations

import pytest

from core import coder_backend
from core.coder_backend import (
    AiderBackend,
    NoopBackend,
    OpenCodeBackend,
    from_config,
)


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeProc:
    argv = None

    def __init__(self, argv, cwd=None, **kwargs):
        _FakeProc.argv = argv
        self.stdout = _FakeStdout(["dang refactor...\n", "xong.\n"])
        self._code = 0

    def wait(self):
        return self._code


def _patch_popen(monkeypatch, proc_cls=_FakeProc):
    monkeypatch.setattr(coder_backend.subprocess, "Popen", proc_cls)


def test_opencode_argv(monkeypatch):
    _patch_popen(monkeypatch)
    streamed = []
    out = OpenCodeBackend("opencode").run("fix auth", ".", streamed.append)
    assert _FakeProc.argv == ["opencode", "run", "fix auth"]
    assert "xong." in out
    assert "dang refactor..." in streamed


def test_aider_argv(monkeypatch):
    _patch_popen(monkeypatch)
    AiderBackend("aider").run("refactor auth", ".", lambda _l: None)
    assert _FakeProc.argv == ["aider", "--message", "refactor auth", "--yes"]


def test_stream_callback_called(monkeypatch):
    _patch_popen(monkeypatch)
    streamed = []
    AiderBackend().run("p", ".", streamed.append)
    assert len(streamed) >= 1


def test_noop_backend_raises():
    with pytest.raises(RuntimeError):
        NoopBackend().run("p", ".", lambda _l: None)


def test_missing_binary_raises(monkeypatch):
    class _Missing:
        def __init__(self, *a, **k):
            raise FileNotFoundError("no binary")

    _patch_popen(monkeypatch, _Missing)
    with pytest.raises(RuntimeError):
        OpenCodeBackend("khong-ton-tai").run("p", ".", lambda _l: None)


def test_from_config():
    assert isinstance(from_config({"coder": {"backend": "opencode"}}), OpenCodeBackend)
    assert isinstance(from_config({"coder": {"backend": "aider"}}), AiderBackend)
    assert isinstance(from_config({"coder": {"backend": "none"}}), NoopBackend)
    assert isinstance(from_config({}), NoopBackend)
