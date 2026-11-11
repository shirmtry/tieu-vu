"""Tests cho server/webhook.py (FastAPI + SQLite)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server import webhook  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TIEU_VU_DONATIONS_DB", str(tmp_path / "donations.db"))
    monkeypatch.setenv("SEPAY_WEBHOOK_KEY", "test-key")
    with TestClient(webhook.app) as c:
        yield c


def _payload(**over):
    base = {
        "id": 1001,
        "gateway": "MB Bank",
        "transactionDate": "2026-11-11 10:00:00",
        "accountNumber": "0374756847",
        "code": None,
        "content": "Ung ho Tieu Vu",
        "transferType": "in",
        "transferAmount": 10000,
        "referenceCode": "REF1001",
    }
    base.update(over)
    return base


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_webhook_requires_auth(client):
    r = client.post("/webhook/sepay", json=_payload())
    assert r.status_code == 401


def test_webhook_accepts_and_dedups(client):
    headers = {"Authorization": "Apikey test-key"}
    p = _payload()
    r = client.post("/webhook/sepay", json=p, headers=headers)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Goi lai cung id -> khong tao them ban ghi.
    r = client.post("/webhook/sepay", json=p, headers=headers)
    assert r.status_code == 200
    assert r.json()["success"] is True

    stats = client.get("/stats/donations")
    assert stats.status_code == 200
    body = stats.json()
    assert body["schemaVersion"] == 1
    assert "1" in body["message"]


def test_webhook_ignores_outgoing(client):
    headers = {"Authorization": "Apikey test-key"}
    r = client.post("/webhook/sepay", json=_payload(id=2002, transferType="out"),
                    headers=headers)
    assert r.status_code == 200
    body = client.get("/stats/donations").json()
    assert "0" in body["message"]


def test_webhook_custom_desc_and_amount(client):
    headers = {"Authorization": "Apikey test-key"}
    r = client.post("/webhook/sepay", json=_payload(id=3003, transferAmount=50000),
                    headers=headers)
    assert r.status_code == 200
    body = client.get("/stats/donations").json()
    assert json.dumps(body)  # JSON serializable
    assert "1" in body["message"]
