# =====================================================================
# actions/coder_actions.py
# Action layer cho AI coder mode: tao file, chay lenh, git commit,
# search code, giai thich code, delegate cho OpenCode/Aider.
#
# Nguyen tac:
#   - Path luon validate trong workspace (core/coder_tools).
#   - run_command chi chay executable trong whitelist.
#   - Action dai (run_command / explain / delegate) chay thread rieng,
#     ket qua day nguoc vao action_queue duoi dang ActionEvent("speak").
#     ActionWorker khong bao gio bi block.
# =====================================================================
from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import List, Optional

from core.coder_tools import (
    resolve_workspace_path,
    validate_command,
    workspace_root,
)
from core.state_machine import ActionEvent

log = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "models",
    "browser_profile",
    "logs",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".bat",
    ".ps1",
    ".sh",
    ".gitignore",
    ".env.example",
}
MAX_SEARCH_RESULTS = 100


class CoderActions:
    def __init__(self, config: dict, event_queue=None, tts=None, coder_nlu=None, backend=None):
        cfg = config.get("coder", {}) or {}
        self.root = workspace_root(config)
        self.allowed_commands = list(cfg.get("allowed_commands", []))
        self.command_timeout = int(cfg.get("command_timeout_sec", 300))
        self.event_queue = event_queue
        self.tts = tts
        self.coder_nlu = coder_nlu
        self.backend = backend
        self.last_search_results: List[str] = []
        self._threads: List[threading.Thread] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit_speak(self, text: str):
        text = str(text or "").strip()
        if not text:
            return
        if self.event_queue is not None:
            try:
                self.event_queue.put_nowait(ActionEvent("speak", {"text": text}, source="coder"))
                return
            except queue.Full:
                log.warning("action_queue day, khong the speak ket qua.")
        if self.tts is not None:
            self.tts.speak(text)

    def _spawn(self, job, name: str) -> threading.Thread:
        def _wrap():
            try:
                job()
            except Exception as exc:
                log.exception("%s loi: %s", name, exc)
                self._emit_speak(f"Lỗi khi chạy {name}: {exc}")

        thread = threading.Thread(target=_wrap, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)
        self._threads = [t for t in self._threads if t.is_alive()]
        return thread

    def join(self, timeout: Optional[float] = None):
        for thread in list(self._threads):
            thread.join(timeout)

    # ------------------------------------------------------------------
    # create_file
    # ------------------------------------------------------------------
    def create_file(self, path: str, content: str = "") -> str:
        target = resolve_workspace_path(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        log.info("Da tao file %s (%d ky tu).", target, len(str(content)))
        return str(target)

    # ------------------------------------------------------------------
    # run_command (sync) + async wrapper
    # ------------------------------------------------------------------
    def run_command(self, cmd: str, cwd: str = ".") -> dict:
        argv = validate_command(cmd, self.allowed_commands)
        workdir = resolve_workspace_path(self.root, cwd or ".")
        if not workdir.is_dir():
            raise ValueError(f"cwd khong ton tai: {workdir}")
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "output": f"Timeout sau {self.command_timeout}s: {cmd}"}
        except FileNotFoundError as exc:
            return {"exit_code": -1, "output": str(exc)}
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        log.info("run_command '%s' -> exit %d", cmd, proc.returncode)
        return {"exit_code": proc.returncode, "output": output}

    def run_command_async(self, cmd: str, cwd: str = ".") -> threading.Thread:
        def _job():
            result = self.run_command(cmd, cwd)
            tail = result["output"][-400:] if result["output"] else "(không có output)"
            self._emit_speak(f"Lệnh {cmd} xong, exit code {result['exit_code']}. {tail}")

        return self._spawn(_job, "CoderCommand")

    # ------------------------------------------------------------------
    # git_commit
    # ------------------------------------------------------------------
    def git_commit(self, message: str) -> str:
        message = str(message or "").strip()
        if not message:
            log.warning("git_commit: message rong, bo qua.")
            return ""
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if status.returncode != 0:
            log.warning(
                "git_commit: khong phai git repo hoac git loi: %s", (status.stderr or "").strip()
            )
            return ""
        if not status.stdout.strip():
            log.warning("git_commit: khong co thay doi nao de commit.")
            return ""
        subprocess.run(["git", "add", "-A"], cwd=str(self.root), capture_output=True, text=True)
        proc = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        log.info("git_commit '%s' -> exit %d", message, proc.returncode)
        return output

    # ------------------------------------------------------------------
    # search_code
    # ------------------------------------------------------------------
    def search_code(self, query: str) -> List[str]:
        needle = str(query or "").strip().lower()
        if not needle:
            return []
        results: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                for lineno, line in enumerate(lines, 1):
                    if needle in line.lower():
                        try:
                            rel = path.relative_to(self.root)
                        except ValueError:
                            rel = path
                        results.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                        if len(results) >= MAX_SEARCH_RESULTS:
                            self.last_search_results = results
                            return results
        self.last_search_results = results
        log.info("search_code '%s' -> %d ket qua.", query, len(results))
        return results

    # ------------------------------------------------------------------
    # explain_code
    # ------------------------------------------------------------------
    def explain_code(self, file: str, lines: Optional[str] = None) -> str:
        target = resolve_workspace_path(self.root, file)
        text = target.read_text(encoding="utf-8", errors="ignore")
        if lines:
            all_lines = text.splitlines()
            start, end = 0, len(all_lines)
            parse = getattr(self.coder_nlu, "parse_lines", None)
            if callable(parse):
                start, end = parse(str(lines), len(all_lines))
            text = "\n".join(all_lines[start:end])
        if self.coder_nlu is None:
            log.warning("explain_code: CoderNLU chua san sang.")
            return ""
        return self.coder_nlu.explain(text, path=str(target))

    def explain_code_async(self, file: str, lines: Optional[str] = None):
        def _job():
            explanation = self.explain_code(file, lines)
            self._emit_speak(explanation or "Không giải thích được file này.")

        return self._spawn(_job, "CoderExplain")

    # ------------------------------------------------------------------
    # delegate_to_coder (OpenCode / Aider — Phase 6)
    # ------------------------------------------------------------------
    def _backend_available(self) -> bool:
        return self.backend is not None and getattr(self.backend, "name", "none") != "none"

    def _on_backend_line(self, line: str):
        log.info("[coder-backend] %s", line)

    def delegate_to_coder(self, prompt: str) -> str:
        if not self._backend_available():
            log.warning("delegate_to_coder: chua cau hinh backend.")
            return ""
        return self.backend.run(str(prompt), str(self.root), self._on_backend_line)

    def delegate_async(self, prompt: str):
        def _job():
            if not self._backend_available():
                self._emit_speak("Chưa cài OpenCode hoặc Aider. " "Xem SOLUTION.md để cài đặt.")
                return
            output = self.delegate_to_coder(prompt)
            self._emit_speak((output or "")[-600:] or "Backend không trả về nội dung.")

        return self._spawn(_job, "CoderDelegate")
