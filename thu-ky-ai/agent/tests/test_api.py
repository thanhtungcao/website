"""Kiểm thử luồng web với bước gọi Claude được giả lập (không cần khóa API)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main
from tests.test_core import _minutes

SAMPLE = Path(__file__).parent.parent / "samples" / "hop-an-phat.vtt"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(main, "generate_minutes", lambda segs, **kw: _minutes())
    return TestClient(main.app)


def test_upload_to_minutes_and_exports(client):
    r = client.post("/api/meetings/upload", files={"file": ("hop.vtt", SAMPLE.read_bytes())})
    assert r.status_code == 200
    mid = r.json()["id"]
    m = client.get(f"/api/meetings/{mid}").json()  # tác vụ nền đã chạy xong trong TestClient
    assert m["status"] == "ready" and m["minutes"]["title"] == "Chốt hợp đồng An Phát"
    assert m["transcript"][0]["speaker"] == "Nguyễn Văn Hùng"
    assert client.get("/api/meetings").json()[0]["action_count"] == 1
    assert "## Quyết định" in client.get(f"/api/meetings/{mid}/minutes.md").text
    d = client.get(f"/api/meetings/{mid}/minutes.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"


def test_upload_empty_file_rejected(client):
    r = client.post("/api/meetings/upload", files={"file": ("x.txt", b"   ")})
    assert r.status_code == 400


def test_join_without_recall_key_explains(client, monkeypatch):
    monkeypatch.setattr(config, "RECALL_API_KEY", "")
    r = client.post("/api/meetings/join", json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert r.status_code == 400 and "RECALL_API_KEY" in r.json()["detail"]


def test_join_rejects_unknown_platform(client, monkeypatch):
    monkeypatch.setattr(config, "RECALL_API_KEY", "k")
    r = client.post("/api/meetings/join", json={"meeting_url": "https://example.com/x"})
    assert r.status_code == 400
