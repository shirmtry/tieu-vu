# =====================================================================
# server/webhook.py
# FastAPI receiver cho SePay webhook (MB Bank 0374756847).
#   - Xac thuc header "Authorization: Apikey <SEPAY_WEBHOOK_KEY>".
#   - Chi ghi giao dich "in"; dedup theo sepay_id.
#   - GET /stats/donations tra badge JSON cho shields.io.
# Chay: uvicorn server.webhook:app --host 0.0.0.0 --port 8000
# =====================================================================
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="Tieu Vu — SePay Webhook")


def db_path() -> Path:
    path = Path(os.getenv("TIEU_VU_DONATIONS_DB", "logs/donations.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


SCHEMA = """
CREATE TABLE IF NOT EXISTS donations (
    sepay_id INTEGER PRIMARY KEY,
    amount INTEGER NOT NULL,
    content TEXT,
    gateway TEXT,
    ts TEXT
);
"""


class SepayPayload(BaseModel):
    id: int
    gateway: str
    transactionDate: str
    accountNumber: str
    code: Optional[str] = None
    content: Optional[str] = None
    transferType: str
    transferAmount: int
    referenceCode: Optional[str] = None


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/sepay")
async def sepay_webhook(payload: SepayPayload, request: Request):
    expected = os.getenv("SEPAY_WEBHOOK_KEY", "")
    if expected:
        auth = request.headers.get("Authorization", "")
        if auth != f"Apikey {expected}":
            raise HTTPException(401, "Invalid API key")
    else:
        log.warning("SEPAY_WEBHOOK_KEY chua duoc dat — chap nhan request khong xac thuc (chi dung dev).")

    if payload.transferType != "in":
        return {"success": True}

    with closing(sqlite3.connect(db_path())) as con:
        _ensure_schema(con)
        cur = con.cursor()
        cur.execute("SELECT 1 FROM donations WHERE sepay_id=?", (payload.id,))
        if cur.fetchone():
            return {"success": True}
        cur.execute(
            "INSERT INTO donations(sepay_id, amount, content, gateway, ts) "
            "VALUES (?,?,?,?,?)",
            (payload.id, payload.transferAmount, payload.content,
             payload.gateway, payload.transactionDate),
        )
        con.commit()
    log.info("Donation #%s +%s VND", payload.id, payload.transferAmount)
    return {"success": True}


@app.get("/stats/donations")
def donations_stats():
    with closing(sqlite3.connect(db_path())) as con:
        _ensure_schema(con)
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM donations").fetchone()
    count, total = int(row[0]), int(row[1])
    return {
        "schemaVersion": 1,
        "label": "donations",
        "message": f"{count} donations • {total:,} VND".replace(",", "."),
        "color": "green",
    }
