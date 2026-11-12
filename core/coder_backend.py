# =====================================================================
# core/coder_backend.py
# Backend cho task coding phuc tap (refactor nhieu file, sua bug):
#   - OpenCodeBackend: opencode run "<prompt>"
#   - AiderBackend:    aider --message "<prompt>" --yes
#   - NoopBackend:     bao loi ro rang khi user chua cai gi
#
# Output duoc stream tung dong qua stream_callback de Tiểu Vũ log/speak
# dan, khong doi backend chay xong moi hien thi.
# =====================================================================
from __future__ import annotations

import logging
import subprocess
from typing import Callable, List

log = logging.getLogger(__name__)

StreamCallback = Callable[[str], None]


class CoderBackend:
    name = "none"

    def run(self, prompt: str, cwd: str, stream_callback: StreamCallback) -> str:
        raise NotImplementedError


class NoopBackend(CoderBackend):
    name = "none"

    def run(self, prompt: str, cwd: str, stream_callback: StreamCallback) -> str:
        raise RuntimeError(
            "Chua cai coder backend. Cai OpenCode (npm i -g opencode-ai) "
            "hoac Aider (pip install aider-chat), roi dat coder.backend "
            "trong config.yaml. Xem SOLUTION.md.")


class SubprocessBackend(CoderBackend):
    """Base cho CLI backend: stream stdout tung dong."""

    default_path = ""

    def __init__(self, path: str | None = None):
        self.path = str(path or self.default_path)

    def _argv(self, prompt: str) -> List[str]:
        raise NotImplementedError

    def run(self, prompt: str, cwd: str, stream_callback: StreamCallback) -> str:
        argv = self._argv(prompt)
        log.info("Chay %s backend: %s ...", self.name, argv[0])
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Khong tim thay '{argv[0]}'. Xem SOLUTION.md de cai "
                f"{self.name}.") from exc
        lines: List[str] = []
        if proc.stdout is not None:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                lines.append(line)
                try:
                    stream_callback(line)
                except Exception:
                    log.debug("stream_callback loi", exc_info=True)
        code = proc.wait()
        if code != 0:
            log.warning("%s backend thoat voi exit code %d", self.name, code)
        return "\n".join(lines)


class OpenCodeBackend(SubprocessBackend):
    name = "opencode"
    default_path = "opencode"

    def _argv(self, prompt: str) -> List[str]:
        return [self.path, "run", prompt]


class AiderBackend(SubprocessBackend):
    name = "aider"
    default_path = "aider"

    def _argv(self, prompt: str) -> List[str]:
        return [self.path, "--message", prompt, "--yes"]


def from_config(config: dict) -> CoderBackend:
    cfg = config.get("coder", {}) or {}
    name = str(cfg.get("backend", "none")).lower()
    if name == "opencode":
        return OpenCodeBackend(cfg.get("opencode_path", "opencode"))
    if name == "aider":
        return AiderBackend(cfg.get("aider_path", "aider"))
    return NoopBackend()
