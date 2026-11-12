# =====================================================================
# tests/test_nlu_coder.py — Ollama tool-calling NLU (mock HTTP)
# =====================================================================
from __future__ import annotations

import copy
import re
from pathlib import Path

from core.nlu import NLU
from core.nlu_coder import CoderNLU


def _wrap(name, **args):
    return {"message": {"tool_calls": [
        {"function": {"name": name, "arguments": args}}]}}


def fake_ollama(text: str) -> dict:
    """Gia lap Qwen2.5-Coder: chon tool theo tu khoa tieng Viet."""
    t = text.lower()
    if "commit" in t:
        m = re.search(r"message\s+(.+)$", text)
        return _wrap("git_commit", message=(m.group(1).strip() if m else "update"))
    if "refactor" in t or "sửa" in t:
        return _wrap("delegate_to_coder", prompt=text)
    if "giải thích" in t or t.startswith("đọc"):
        m = re.search(r"([\w./\\-]+\.py)", text)
        return _wrap("explain_code", file=(m.group(1) if m else "main.py"))
    if "tìm" in t or "search" in t:
        query = text.split("tìm", 1)[-1].strip()
        query = query.replace("kiếm ", "").replace("hàm ", "").replace("class ", "")
        return _wrap("search_code", query=query.strip() or "x")
    if "tạo file" in t:
        m = re.search(r"([\w./\\-]+\.py)", text)
        content = "print('hello world')" if "hello" in t else "print(1)"
        return _wrap("create_file", path=(m.group(1) if m else "main.py"),
                     content=content)
    if "chạy" in t:
        return _wrap("run_command", cmd=text.split("chạy", 1)[1].strip())
    return {"message": {"content": "toi khong hieu"}}


def make_post(fn=fake_ollama):
    calls = []

    def _post(url, payload, timeout):
        text = payload["messages"][-1]["content"]
        calls.append(text)
        return fn(text)

    _post.calls = calls
    return _post


def make_cfg(base_config, workspace, coder_enabled=True):
    cfg = copy.deepcopy(base_config)
    cfg["coder"] = dict(cfg.get("coder", {}), workspace_root=str(workspace))
    cfg["nlu"] = dict(cfg.get("nlu", {}))
    cfg["nlu"]["coder"] = {
        "enabled": coder_enabled,
        "model": "qwen2.5-coder:7b",
        "ollama_url": "http://localhost:11434",
        "timeout_sec": 5,
    }
    return cfg


def make_coder(base_config, tmp_path, post=None):
    return CoderNLU(make_cfg(base_config, tmp_path), post=post or make_post())


def test_tool_call_becomes_action_event(base_config, tmp_path):
    coder = make_coder(base_config, tmp_path)
    ev = coder.parse("tạo file main.py với hello world")
    assert ev is not None and ev.name == "create_file"
    assert Path(ev.payload["path"]).name == "main.py"
    assert "hello world" in ev.payload["content"]


def test_ten_sample_intents_accuracy(base_config, tmp_path):
    cases = [
        ("tạo file main.py với hello world", "create_file"),
        ("chạy pytest", "run_command"),
        ("commit với message fix auth", "git_commit"),
        ("tìm hàm login", "search_code"),
        ("giải thích file auth.py", "explain_code"),
        ("refactor file auth.py thành async", "delegate_to_coder"),
        ("tạo file utils.py với hàm sum", "create_file"),
        ("chạy git status", "run_command"),
        ("tìm kiếm class User", "search_code"),
        ("đọc và giải thích main.py", "explain_code"),
    ]
    coder = make_coder(base_config, tmp_path)
    correct = 0
    for text, expected in cases:
        ev = coder.parse(text)
        if ev is not None and ev.name == expected:
            correct += 1
    assert correct >= 8


def test_create_file_outside_workspace_rejected(base_config, tmp_path):
    post = make_post(lambda _t: _wrap("create_file", path="../evil.py", content="x"))
    coder = make_coder(base_config, tmp_path, post=post)
    assert coder.parse("tạo file ../evil.py") is None


def test_command_outside_whitelist_rejected(base_config, tmp_path):
    post = make_post(lambda _t: _wrap("run_command", cmd="rm -rf /"))
    coder = make_coder(base_config, tmp_path, post=post)
    assert coder.parse("chạy rm -rf /") is None


def test_curl_command_rejected(base_config, tmp_path):
    post = make_post(lambda _t: _wrap("run_command", cmd="curl http://x"))
    coder = make_coder(base_config, tmp_path, post=post)
    assert coder.parse("chạy curl http://x") is None


def test_empty_git_message_rejected(base_config, tmp_path):
    post = make_post(lambda _t: _wrap("git_commit", message="  "))
    coder = make_coder(base_config, tmp_path, post=post)
    assert coder.parse("commit") is None


def test_ollama_unavailable_returns_none(base_config, tmp_path):
    def _boom(url, payload, timeout):
        raise ConnectionError("ollama down")

    coder = CoderNLU(make_cfg(base_config, tmp_path), post=_boom)
    assert coder.parse("tạo file x.py") is None


def test_disabled_coder_returns_none(base_config, tmp_path):
    coder = CoderNLU(make_cfg(base_config, tmp_path, coder_enabled=False),
                      post=make_post())
    assert coder.parse("tạo file x.py") is None


def test_content_json_fallback(base_config, tmp_path):
    def _content_only(_text):
        return {"message": {"content": (
            '{"name": "search_code", "arguments": {"query": "login"}}')}}

    coder = make_coder(base_config, tmp_path, post=make_post(_content_only))
    ev = coder.parse("tim login")
    assert ev is not None and ev.name == "search_code"


def test_nlu_chain_rules_first_then_coder(base_config, tmp_path):
    cfg = make_cfg(base_config, tmp_path)
    post = make_post()
    nlu = NLU(cfg)
    nlu.coder = CoderNLU(cfg, post=post)

    # Lenh pho bien -> rule, KHONG goi Ollama.
    rule_intents = nlu.parse("ủng hộ tiểu vũ")
    assert rule_intents[0].name == "donate_window"
    assert post.calls == []

    # Lenh coding -> CoderNLU.
    coder_intents = nlu.parse("tạo file x.py với print(1)")
    assert coder_intents and coder_intents[0].name == "create_file"
    assert coder_intents[0].source == "coder"


def test_parse_lines():
    assert CoderNLU.parse_lines("1-50", 200) == (0, 50)
    assert CoderNLU.parse_lines("abc", 200) == (0, 200)
    assert CoderNLU.parse_lines("", 10) == (0, 10)
