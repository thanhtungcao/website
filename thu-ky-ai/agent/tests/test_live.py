"""Luồng ghi trực tiếp với bộ chép lời giả lập; và kiểm tra giải mã âm thanh thật bằng PyAV."""
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import asr, config, live, main
from app.transcript import Segment
from tests.test_core import _minutes

heard = []


def fake_transcribe(path, offset, speaker, hint=""):
    heard.append((offset, speaker, hint, open(path, "rb").read()))
    return [Segment(offset + 1.0, speaker, f"câu nói ở giây {int(offset)}")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(config, "FREE_DAILY_LIMIT", 5)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")
    monkeypatch.setattr(asr, "available", lambda: True)
    monkeypatch.setattr(live, "_transcribe", fake_transcribe)
    got = {}
    def fake_generate(segs, **kw):
        got["segs"], got["kw"] = segs, kw
        return _minutes()
    monkeypatch.setattr(main, "generate_minutes", fake_generate)
    heard.clear()
    c = TestClient(main.app)
    c.got = got
    return c


def chunk(c, mid, offset, source, data=b"audio-bytes"):
    return c.post(f"/api/live/{mid}/chunk", files={"file": ("chunk.webm", data)}, data={"offset": str(offset), "source": source})


def wait_ready(c, mid):
    import time
    for _ in range(100):
        m = c.get(f"/api/meetings/{mid}").json()
        if m["status"] in {"ready", "error"}:
            return m
        time.sleep(0.05)
    raise AssertionError(m["status"])


def test_live_flow_to_minutes(client):
    c = client
    m = c.post("/api/live/start", json={"glossary": "An Phát, anh Quân"}).json()
    assert m["status"] == "recording" and m["source"] == "live"
    mid = m["id"]
    assert chunk(c, mid, 20.0, "system").status_code == 200
    assert chunk(c, mid, 0.0, "system").status_code == 200
    assert chunk(c, mid, 0.5, "mic").status_code == 200
    live.wait_idle()
    t = c.get(f"/api/meetings/{mid}").json()
    assert [s["start"] for s in t["transcript"]] == [1.0, 1.5, 21.0]          # sắp theo thời gian
    assert {s["speaker"] for s in t["transcript"]} == {"Người tham dự", "Tôi"}
    assert t["hint"] == "An Phát, anh Quân" and heard[0][2] == "An Phát, anh Quân"   # gợi ý tên riêng tới bộ chép lời
    assert c.post(f"/api/live/{mid}/stop").status_code == 200
    done = wait_ready(c, mid)
    assert done["status"] == "ready" and len(c.got["segs"]) == 3
    assert "Người tham dự" in c.got["kw"]["context"]
    assert c.get("/api/config").json()["used_today"] == 1
    assert chunk(c, mid, 40.0, "system").status_code == 409                   # hết ghi thì không nhận thêm


def test_stop_waits_for_pending_chunks(client, monkeypatch):
    import threading
    gate = threading.Event()
    def slow(path, offset, speaker, hint=""):
        gate.wait(5)
        return [Segment(offset, speaker, "xin chào")]
    monkeypatch.setattr(live, "_transcribe", slow)
    c = client
    mid = c.post("/api/live/start", json={}).json()["id"]
    chunk(c, mid, 0, "mic")
    c.post(f"/api/live/{mid}/stop")
    assert c.get(f"/api/meetings/{mid}").json()["status"] == "finishing"
    gate.set()
    assert wait_ready(c, mid)["status"] == "ready" and c.got["segs"][0].text == "xin chào"


def test_silence_gives_clear_error_and_refund(client, monkeypatch):
    monkeypatch.setattr(live, "_transcribe", lambda *a, **k: [])
    c = client
    mid = c.post("/api/live/start", json={}).json()["id"]
    chunk(c, mid, 0, "system")
    c.post(f"/api/live/{mid}/stop")
    m = wait_ready(c, mid)
    assert m["status"] == "error" and "Không nghe được" in m["error"]
    assert c.get("/api/config").json()["used_today"] == 0


def test_live_isolation_and_validation(client):
    c, other = client, TestClient(main.app)
    mid = c.post("/api/live/start", json={}).json()["id"]
    assert chunk(other, mid, 0, "system").status_code == 404
    assert other.post(f"/api/live/{mid}/stop").status_code == 404
    assert chunk(c, mid, 0, "speaker").status_code == 400
    assert chunk(c, mid, -5, "mic").status_code == 400


def test_live_disabled_without_asr(client, monkeypatch):
    monkeypatch.setattr(asr, "available", lambda: False)
    r = client.post("/api/live/start", json={})
    assert r.status_code == 400 and "faster-whisper" in r.json()["detail"]
    assert client.get("/api/config").json()["live_enabled"] is False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="cần ffmpeg để tạo file thử")
def test_browser_audio_formats_decode(tmp_path):
    """Trình duyệt gửi webm/opus (Chrome, Edge, Firefox) hoặc mp4/aac (Safari): faster-whisper phải đọc được."""
    fw = pytest.importorskip("faster_whisper")
    for name, args in [("a.webm", ["-c:a", "libopus"]), ("a.mp4", ["-c:a", "aac"])]:
        out = tmp_path / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", *args, str(out)], check=True)
        audio = fw.decode_audio(str(out))
        assert 2.8 * 16000 < len(audio) < 3.2 * 16000   # 16 kHz mono, đúng độ dài
