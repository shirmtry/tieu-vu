"""Daily loop: cleanup -> test -> lint-fix -> TODO[auto] scan.

Runs from the Windows Scheduled Task registered by
``scripts/install_auto_dev_windows.ps1``.
"""

from __future__ import annotations

import datetime
import logging
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    today = datetime.date.today().isoformat()
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        filename=ROOT / f"logs/auto_dev_{today}.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    run([sys.executable, "scripts/cleanup_repo.py"])

    result = run([sys.executable, "-m", "pytest", "-q"])
    if result.returncode != 0:
        logging.error("pytest red")
        run([
            "gh", "issue", "create",
            "--title", f"[auto] main is red {today}",
            "--body", "Auto-dev: pytest failed. See Actions logs.",
            "--label", "auto-red",
        ])
        return 1

    result = run([sys.executable, "-m", "ruff", "check", "."])
    if result.returncode != 0:
        run([sys.executable, "-m", "ruff", "check", "--fix", "."])
        branch = f"chore/auto-lint-{today}"
        run(["git", "checkout", "-B", branch])
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", f"chore: auto-fix lint {today}"])
        pushed = run(["git", "push", "-u", "origin", branch])
        if pushed.returncode == 0:
            run([
                "gh", "pr", "create",
                "--title", f"chore: auto-fix lint {today}",
                "--label", "auto-merge",
                "--body", "Automated lint fix.",
            ])

    claude = shutil.which("claude-code")
    if claude:
        for folder in ("core", "actions", "ui"):
            for path in (ROOT / folder).rglob("*.py"):
                for line_no, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if "TODO[auto]" in line:
                        run([
                            claude,
                            "--task-file", "scripts/task_template.md",
                            "--target", f"{path.relative_to(ROOT)}:{line_no}",
                        ])
    logging.info("auto-dev done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
