# =====================================================================
# core/coder_tools.py
# JSON schema tool-calling cho CoderNLU + guard dung chung cho action layer.
#
# Guard dat o day de NLU (Phase 3) va CoderActions (Phase 4) dung CUNG
# mot quy tac: path phai nam trong workspace, command phai trong whitelist.
# =====================================================================
from __future__ import annotations

import shlex
from pathlib import Path
from typing import Iterable, List

CODER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Tạo file mới trong workspace với nội dung cho trước.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Đường dẫn tương đối trong workspace."},
                    "content": {"type": "string",
                                "description": "Nội dung file."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Chạy lệnh shell trong whitelist (pytest, git, pip, python...).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Lệnh cần chạy."},
                    "cwd": {"type": "string",
                            "description": "Thư mục chạy, mặc định workspace."},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Stage toàn bộ thay đổi và tạo git commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Tìm chuỗi trong mã nguồn workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Chuỗi cần tìm."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_code",
            "description": "Giải thích một file mã nguồn bằng tiếng Việt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "File cần giải thích."},
                    "lines": {"type": "string",
                              "description": "Khoảng dòng, vd '1-50' (tùy chọn)."},
                },
                "required": ["file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_coder",
            "description": "Giao task coding phức tạp cho OpenCode/Aider.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string",
                               "description": "Yêu cầu coding đầy đủ cho agent."},
                },
                "required": ["prompt"],
            },
        },
    },
]

_SHELL_OPERATORS = {"&&", "||", "|", ";", ">", ">>", "<", "&"}


def workspace_root(config: dict) -> Path:
    coder = config.get("coder", {}) or {}
    return Path(str(coder.get("workspace_root") or ".")).expanduser().resolve()


def resolve_workspace_path(root: str | Path, candidate: str) -> Path:
    """Tra ve path tuyet doi trong workspace; raise ValueError neu ra ngoai."""
    root_p = Path(root).resolve()
    raw = str(candidate or "").strip()
    if not raw:
        raise ValueError("Duong dan rong")
    p = Path(raw)
    if not p.is_absolute():
        p = root_p / p
    resolved = p.resolve()
    if resolved != root_p and root_p not in resolved.parents:
        raise ValueError(f"Duong dan ngoai workspace: {candidate}")
    return resolved


def validate_command(cmd: str, allowed: Iterable[str]) -> List[str]:
    """Tach lenh va kiem tra executable thuoc whitelist.

    Raise PermissionError khi rong, co toan tu shell, hoac executable la.
    """
    text = str(cmd or "").strip()
    if not text:
        raise PermissionError("Lenh rong")
    try:
        argv = shlex.split(text, posix=True)
    except ValueError as exc:
        raise PermissionError(f"Lenh khong hop le: {exc}") from exc
    if not argv:
        raise PermissionError("Lenh rong")
    if any(tok in _SHELL_OPERATORS for tok in argv):
        raise PermissionError("Khong cho phep toan tu shell trong lenh")
    exe = Path(argv[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    allowed_norm = set()
    for item in allowed:
        name = Path(str(item)).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        allowed_norm.add(name)
    if exe not in allowed_norm:
        raise PermissionError(f"Lenh '{exe}' khong nam trong whitelist")
    return argv
