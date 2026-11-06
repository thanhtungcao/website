"""Kiểm thử luồng web với bước gọi Claude được giả lập (không cần khóa API)."""
import base64
import hashlib
import hmac
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main, webhook
from app.minutes import MinutesError
from tests.test_core import _minutes

SAMPLE = Path(__file__).parent.parent / "samples" / "hop-an-phat.vtt"
calls = []


def fake_generate(segs, **kw):
    calls.append(kw.get("api_key"))
    return _minutes()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(config, "FREE_DAILY_LIMIT", 2)
    monkeypatch.setattr(config, "RECALL_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")
    monkeypatch.setattr(main, "generate_minutes", fake_generate)
    calls.clear()
    return lambda: TestClient(main.app)


def up(c, headers=None):
    return c.post("/api/meetings/upload", files={"file": ("hop.vtt", SAMPLE.read_bytes())}, headers=headers or {})


def test_upload_to_minutes_and_exports(make_client):
    c = make_client()
    r = up(c)
    assert r.status_code == 200
    mid = r.json()["id"]
    m = c.get(f"/api/meetings/{mid}").json()
    assert m["status"] == "ready" and m["minutes"]["title"] == "Chốt hợp đồng An Phát"
    assert c.get("/api/meetings").json()[0]["action_count"] == 1
    assert "## Quyết định" in c.get(f"/api/meetings/{mid}/minutes.md").text
    d = c.get(f"/api/meetings/{mid}/minutes.docx?org=ABC")
    assert d.status_code == 200 and d.content[:2] == b"PK"


def test_workspaces_are_isolated(make_client):
    a, b = make_client(), make_client()
    mid = up(a).json()["id"]
    assert b.get("/api/meetings").json() == []
    assert b.get(f"/api/meetings/{mid}").status_code == 404
    assert b.get(f"/api/meetings/{mid}/minutes.docx").status_code == 404
    assert b.delete(f"/api/meetings/{mid}").status_code == 404
    assert a.delete(f"/api/meetings/{mid}").status_code == 200
    assert a.get("/api/meetings").json() == []


def test_free_quota_and_own_key(make_client):
    c = make_client()
    assert up(c).status_code == 200 and up(c).status_code == 200
    r = up(c)
    assert r.status_code == 429 and "khóa Claude API" in r.json()["detail"]
    assert c.get("/api/config").json()["used_today"] == 2
    assert up(c, {"X-Anthropic-Key": "sk-ant-own"}).status_code == 200  # khóa riêng: không giới hạn
    assert calls[-1] == "sk-ant-own" and calls[0] is None


def test_quota_refunded_on_failure(make_client, monkeypatch):
    c = make_client()
    def boom(segs, **kw):
        raise MinutesError("lỗi thử")
    monkeypatch.setattr(main, "generate_minutes", boom)
    mid = up(c).json()["id"]
    assert c.get(f"/api/meetings/{mid}").json()["status"] == "error"
    assert c.get("/api/config").json()["used_today"] == 0


def test_no_server_key_requires_own_key(make_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    c = make_client()
    assert up(c).status_code == 400
    assert up(c, {"X-Anthropic-Key": "sk-ant-own"}).status_code == 200


def test_upload_limits(make_client, monkeypatch):
    c = make_client()
    assert c.post("/api/meetings/upload", files={"file": ("x.txt", b"   ")}).status_code == 400
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    assert up(c).status_code == 413


def test_join_disabled_without_recall(make_client):
    c = make_client()
    r = c.post("/api/meetings/join", json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert r.status_code == 400 and not c.get("/api/config").json()["bot_enabled"]


def test_privacy_and_health(make_client):
    c = make_client()
    assert "Quyền riêng tư" in c.get("/privacy").text
    assert 'href="/app"' in c.get("/").text and "Mời Thư Ký AI vào cuộc họp" in c.get("/app").text
    assert c.get("/healthz").json() == {"ok": True}


def _sign(secret_b64, msg_id, ts, body):
    sig = base64.b64encode(hmac.new(base64.b64decode(secret_b64), f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": str(ts), "svix-signature": f"v1,{sig}"}


def test_webhook_signature(make_client, monkeypatch):
    secret = base64.b64encode(b"super-secret-key").decode()
    body = b'{"event":"bot.status_change","data":{"bot":{"id":"nope"}}}'
    h = _sign(secret, "msg_1", int(time.time()), body)
    assert webhook.verify("whsec_" + secret, h, body)
    assert not webhook.verify("whsec_" + secret, h, body + b" ")
    assert not webhook.verify("whsec_" + secret, _sign(secret, "m", int(time.time()) - 3600, body), body)
    monkeypatch.setattr(config, "RECALL_WEBHOOK_SECRET", "whsec_" + secret)
    c = make_client()
    assert c.post("/api/webhooks/recall", content=body).status_code == 401
    assert c.post("/api/webhooks/recall", content=body, headers=h).status_code == 200
