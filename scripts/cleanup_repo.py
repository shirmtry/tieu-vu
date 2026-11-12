"""Remove build artifacts, caches, orphans (never user data)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Never touch virtualenvs, git internals, or the user's scratch folder.
SKIP_PARTS = {".git", ".venv", "venv", "unused"}

DIR_PATTERNS = [
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    ".benchmark",
    ".reports/old",
    "htmlcov",
    "build",
    "dist",
]
FILE_PATTERNS = ["*.egg-info", "*.pyc", "*.pyo", ".coverage", ".coverage.*"]


def _skipped(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def _remove(path: Path) -> None:
    if _skipped(path):
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    print(f"[CLEAN] {path.relative_to(ROOT)}")


def main() -> int:
    for pattern in DIR_PATTERNS:
        for path in ROOT.rglob(pattern):
            _remove(path)
    for pattern in FILE_PATTERNS:
        for path in ROOT.rglob(pattern):
            _remove(path)
    for path in ROOT.glob("logs/*.log"):
        _remove(path)
    print("[CLEAN OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
