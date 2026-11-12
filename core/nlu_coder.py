# =====================================================================
# core/nlu_coder.py
# NLU cho che do CODE: Qwen2.5-Coder qua Ollama (tool-calling, local).
#
# Chain trong core/nlu.py: rule-based -> CoderNLU -> LLM nho (neu bat).
# Ollama khong chay -> parse() tra None ngay (khong treo, khong cloud),
# caller fallback rule-based. Tham so tool duoc validate truoc khi tra
# ActionEvent: path trong workspace, command trong whitelist.
# =====================================================================
from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .coder_tools import (
    CODER_TOOLS,
    resolve_workspace_path,
    validate_command,
    workspace_root,
)
from .state_machine import ActionEvent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là Tiểu Vũ, trợ lý AI coder điều khiển bằng giọng nói tiếng Việt. "
    "Người dùng có thể trộn tiếng Anh (commit, merge, refactor, pull request). "
    "Chọn ĐÚNG MỘT tool phù hợp nhất với câu lệnh và trả về tool call. "
    "Nếu câu lệnh không liên quan tới coding, không gọi tool nào."
)


def post_json(url: str, payload: dict, timeout: float) -> dict:
    """POST JSON toi Ollama, tra dict. Khong dung cloud."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class CoderNLU:
    """Ollama tool-calling client (inject `post` de test khong can server)."""

    def __init__(self, config: dict, post: Optional[Callable] = None):
        cfg = (config.get("nlu", {}) or {}).get("coder", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.model = str(cfg.get("model", "qwen2.5-coder:7b"))
        self.url = str(cfg.get("ollama_url", "http://localhost:11434")).rstrip("/")
        self.timeout = float(cfg.get("timeout_sec", 30))
        coder_cfg = config.get("coder", {}) or {}
        self.root = workspace_root(config)
        self.allowed_commands = list(coder_cfg.get("allowed_commands", []))
        self._post = post or post_json

    # ------------------------------------------------------------------
    def parse(self, text: str) -> Optional[ActionEvent]:
        if not self.enabled:
            return None
        text = str(text or "").strip()
        if not text:
            return None
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "tools": CODER_TOOLS,
            "stream": False,
        }
        try:
            data = self._post(f"{self.url}/api/chat", payload, self.timeout)
        except Exception as exc:
            log.warning("Ollama khong san sang (%s) -> fallback rule-based.", exc)
            return None
        if not isinstance(data, dict):
            return None
        name, args = self._extract_tool_call(data)
        if not name:
            log.info("CoderNLU: model khong chon tool cho '%s'.", text)
            return None
        return self._validated_event(name, args)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_tool_call(data: dict) -> tuple[str, dict]:
        message = data.get("message") or {}
        calls = message.get("tool_calls") or []
        if calls:
            fn = (calls[0] or {}).get("function") or {}
            name = str(fn.get("name", "")).strip()
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            return name, dict(args or {})
        # Fallback: mot so model tra JSON trong content thay vi tool_calls.
        content = str(message.get("content", "") or "")
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return "", {}
            name = str(obj.get("name") or obj.get("tool") or "").strip()
            args = obj.get("arguments") or obj.get("parameters") or {}
            return name, dict(args or {})
        return "", {}

    # ------------------------------------------------------------------
    def _validated_event(self, name: str, args: dict) -> Optional[ActionEvent]:
        try:
            if name == "create_file":
                path = resolve_workspace_path(self.root, str(args.get("path", "")))
                content = str(args.get("content", ""))
                return ActionEvent("create_file",
                                   {"path": str(path), "content": content},
                                   source="voice")
            if name == "run_command":
                cmd = str(args.get("cmd", "")).strip()
                validate_command(cmd, self.allowed_commands)
                cwd = resolve_workspace_path(self.root, str(args.get("cwd") or "."))
                return ActionEvent("run_command",
                                   {"cmd": cmd, "cwd": str(cwd)}, source="voice")
            if name == "git_commit":
                message = str(args.get("message", "")).strip()
                if not message:
                    return None
                return ActionEvent("git_commit", {"message": message}, source="voice")
            if name == "search_code":
                query = str(args.get("query", "")).strip()
                if not query:
                    return None
                return ActionEvent("search_code", {"query": query}, source="voice")
            if name == "explain_code":
                file = resolve_workspace_path(self.root, str(args.get("file", "")))
                payload = {"file": str(file)}
                if args.get("lines"):
                    payload["lines"] = str(args["lines"])
                return ActionEvent("explain_code", payload, source="voice")
            if name == "delegate_to_coder":
                prompt = str(args.get("prompt", "")).strip()
                if not prompt:
                    return None
                return ActionEvent("delegate_to_coder", {"prompt": prompt},
                                   source="voice")
        except (ValueError, PermissionError) as exc:
            log.warning("CoderNLU tu choi tool '%s': %s", name, exc)
            return None
        return None

    # ------------------------------------------------------------------
    def explain(self, code: str, path: str = "") -> str:
        """Hoi model giai thich code (dung cho explain_code action)."""
        if not self.enabled or not code.strip():
            return ""
        prompt = (f"Giải thích ngắn gọn file {path or 'sau đây'} bằng tiếng Việt, "
                  "nêu mục đích và các hàm chính:\n\n"
                  f"```\n{code[:8000]}\n```")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "Bạn là kỹ sư phần mềm, giải thích code tiếng Việt."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        try:
            data = self._post(f"{self.url}/api/chat", payload, self.timeout)
            return str((data.get("message") or {}).get("content", "")).strip()
        except Exception as exc:
            log.warning("CoderNLU explain loi: %s", exc)
            return ""

    # ------------------------------------------------------------------
    @staticmethod
    def parse_lines(spec: str, total: int) -> tuple[int, int]:
        """'1-50' -> (0, 50); spec sai -> toan bo file."""
        match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", str(spec or ""))
        if not match:
            return 0, total
        start = max(0, int(match.group(1)) - 1)
        end = min(total, int(match.group(2)))
        if end <= start:
            return 0, total
        return start, end

    def workspace_file(self, path: str) -> Path:
        return resolve_workspace_path(self.root, path)
