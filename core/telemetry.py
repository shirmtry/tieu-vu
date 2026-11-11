# =====================================================================
# core/telemetry.py
# Ghi telemetry xuong SQLite de do "giam su dung ban phim/chuot":
#   - actions: moi hanh dong voi nguon (gaze/voice/snippet/vk) + thoi gian.
#   - sessions: thoi luong phien chay.
# Thread-safe (lock) va khong nem loi ra ngoai.
# =====================================================================
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts);
CREATE INDEX IF NOT EXISTS idx_actions_source ON actions(source);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started REAL NOT NULL,
    ended REAL,
    actions INTEGER DEFAULT 0
);
"""


class Telemetry:
    """SQLite logger don gian, fail-safe (loi ghi chi log warning)."""

    def __init__(self, db_path: str | Path = "logs/telemetry.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            self._con.executescript(_SCHEMA)
            self._con.commit()
        except sqlite3.Error as exc:
            log.warning("Khong tao duoc schema telemetry: %s", exc)
        cur = self._con.execute("INSERT INTO sessions(started) VALUES (?)", (time.time(),))
        self._con.commit()
        self.session_id: Optional[int] = cur.lastrowid
        self._count = 0

    # ------------------------------------------------------------------
    def log_action(self, name: str, source: str, payload: Any = None):
        try:
            with self._lock:
                self._con.execute(
                    "INSERT INTO actions(ts, name, source, payload) VALUES (?,?,?,?)",
                    (time.time(), name, source, None if payload is None else str(payload)),
                )
                self._con.commit()
                self._count += 1
        except sqlite3.Error as exc:
            log.warning("Telemetry ghi loi: %s", exc)

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """Thong ke nhanh: tong action theo nguon + thoi gian phien."""
        try:
            with self._lock:
                rows = self._con.execute(
                    "SELECT source, COUNT(*) FROM actions GROUP BY source").fetchall()
                total = self._con.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        except sqlite3.Error:
            return {"total": 0, "by_source": {}, "session_actions": self._count}
        return {
            "total": int(total),
            "by_source": {str(k): int(v) for k, v in rows},
            "session_actions": self._count,
        }

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                rows = self._con.execute(
                    "SELECT ts, name, source FROM actions ORDER BY id DESC LIMIT ?",
                    (int(limit),)).fetchall()
        except sqlite3.Error:
            return []
        return [{"ts": r[0], "name": r[1], "source": r[2]} for r in rows]

    # ------------------------------------------------------------------
    def close(self):
        try:
            with self._lock:
                if self.session_id is not None:
                    self._con.execute(
                        "UPDATE sessions SET ended=?, actions=? WHERE id=?",
                        (time.time(), self._count, self.session_id))
                    self._con.commit()
                self._con.close()
        except sqlite3.Error as exc:
            log.debug("Telemetry close: %s", exc)
