"""Tests cho core/telemetry.py (SQLite action logger)."""
from __future__ import annotations

from core.telemetry import Telemetry


def test_log_and_stats(tmp_path):
    t = Telemetry(tmp_path / "telemetry.db")
    t.log_action("left_click", source="gesture")
    t.log_action("left_click", source="gesture")
    t.log_action("search", source="voice", payload={"query": "thoi tiet"})
    s = t.stats()
    assert s["total"] == 3
    assert s["by_source"]["gesture"] == 2
    assert s["by_source"]["voice"] == 1
    assert s["session_actions"] == 3
    t.close()


def test_recent_returns_latest_first(tmp_path):
    t = Telemetry(tmp_path / "telemetry.db")
    t.log_action("a", source="gesture")
    t.log_action("b", source="voice")
    rows = t.recent(limit=5)
    assert [r["name"] for r in rows][0] == "b"
    t.close()
