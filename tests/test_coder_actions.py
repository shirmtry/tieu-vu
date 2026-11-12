# =====================================================================
# tests/test_coder_actions.py — coding actions + async (khong block worker)
# =====================================================================
from __future__ import annotations

import copy
import queue
import subprocess
from pathlib import Path

import pytest

from actions.coder_actions import CoderActions


def make_cfg(base_config, root):
    cfg = copy.deepcopy(base_config)
    cfg["coder"] = dict(cfg.get("coder", {}), workspace_root=str(root),
                        allowed_commands=["git", "python", "pytest", "pip",
                                          "node", "npm"],
                        command_timeout_sec=60)
    return cfg


@pytest.fixture()
def coder(base_config, tmp_path):
    return CoderActions(make_cfg(base_config, tmp_path), event_queue=queue.Queue())


def _wait_event(q, timeout=5.0):
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


class _FakeNLU:
    def __init__(self, text="Giải thích: file in hello."):
        self.text = text
        self.seen = None

    def explain(self, code, path=""):
        self.seen = (code, path)
        return self.text

    @staticmethod
    def parse_lines(_spec, total):
        return 0, total


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def run(self, prompt, cwd, stream_callback):
        self.calls.append((prompt, cwd))
        stream_callback("dang chay...")
        return "refactor xong"


# ---------------------------------------------------------------------
# create_file
# ---------------------------------------------------------------------
def test_create_file_inside_workspace(coder, tmp_path):
    path = coder.create_file("pkg/hello.py", "print('hi')")
    target = Path(path)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "print('hi')"
    assert tmp_path in target.parents


def test_create_file_outside_workspace(coder):
    with pytest.raises(ValueError):
        coder.create_file("../evil.py", "x")
    with pytest.raises(ValueError):
        coder.create_file(str(Path(coder.root).parent / "evil.py"), "x")


# ---------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------
def test_run_command_outside_whitelist(coder):
    with pytest.raises(PermissionError):
        coder.run_command("curl http://example.com")


def test_run_command_shell_operator_rejected(coder):
    with pytest.raises(PermissionError):
        coder.run_command("git && rm -rf /")


def test_run_command_git_version(coder):
    result = coder.run_command("git --version")
    assert result["exit_code"] == 0
    assert "git" in result["output"].lower()


def test_run_command_async_pushes_speak(coder):
    q = coder.event_queue
    coder.run_command_async("git --version")
    event = _wait_event(q)
    assert event is not None and event.name == "speak"
    assert "exit code 0" in event.payload["text"]


# ---------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------
def test_git_commit_without_changes(coder, tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    assert coder.git_commit("nothing") == ""  # warning, khong raise


def test_git_commit_with_changes(coder, tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"],
                   cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"],
                   cwd=tmp_path, capture_output=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    output = coder.git_commit("add a")
    assert "a.txt" in output or "1 file" in output


# ---------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------
def test_search_code_finds_marker(coder, tmp_path):
    (tmp_path / "mod.py").write_text("def login():\n    return 'SECRET_MARKER'\n",
                                     encoding="utf-8")
    results = coder.search_code("SECRET_MARKER")
    assert len(results) == 1
    assert "mod.py:2" in results[0]
    assert coder.last_search_results == results


def test_search_code_skips_git_dir(coder, tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("SECRET_MARKER", encoding="utf-8")
    assert coder.search_code("SECRET_MARKER") == []


# ---------------------------------------------------------------------
# explain_code / delegate
# ---------------------------------------------------------------------
def test_explain_code_async(coder, tmp_path):
    (tmp_path / "auth.py").write_text("print('auth')", encoding="utf-8")
    coder.coder_nlu = _FakeNLU()
    coder.explain_code_async("auth.py")
    event = _wait_event(coder.event_queue)
    assert event is not None and "Giải thích" in event.payload["text"]


def test_delegate_async_with_backend(coder):
    backend = _FakeBackend()
    coder.backend = backend
    coder.delegate_async("refactor auth")
    event = _wait_event(coder.event_queue)
    assert event is not None and "refactor xong" in event.payload["text"]
    assert backend.calls and backend.calls[0][0] == "refactor auth"


def test_delegate_without_backend_speaks_hint(coder):
    coder.backend = None
    coder.delegate_async("anything")
    event = _wait_event(coder.event_queue)
    assert event is not None and "OpenCode" in event.payload["text"]
