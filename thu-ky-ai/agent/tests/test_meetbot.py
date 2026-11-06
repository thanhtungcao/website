"""Bot vào họp: nhận diện link, và thu âm thanh thật trong trình duyệt từ một phòng họp giả."""
import functools
import http.server
import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from app import config, live, meetbot, store


def test_detect_and_zoom_web_link():
    assert meetbot.detect("https://meet.google.com/abc-defg-hij") == "meet"
    assert meetbot.detect("https://us02web.zoom.us/j/81234567890?pwd=XyZ") == "zoom"
    assert meetbot.detect("https://teams.microsoft.com/l/meetup-join/19%3ameeting_x") == "teams"
    assert meetbot.detect("https://teams.live.com/meet/9876") == "teams"
    assert meetbot.detect("https://evil.com/meet.google.com") == ""
    assert meetbot.detect("https://zoom.us.evil.com/j/1") == ""
    assert meetbot.join_url("https://us02web.zoom.us/j/81234567890?pwd=XyZ", "zoom") == "https://app.zoom.us/wc/join/81234567890?pwd=XyZ"
    assert meetbot.join_url("https://zoom.us/j/81234567890", "zoom") == "https://app.zoom.us/wc/join/81234567890"
    assert meetbot.join_url("https://meet.google.com/abc", "meet") == "https://meet.google.com/abc"


BROWSER = os.environ.get("TK_TEST_BROWSER", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")


@pytest.mark.skipif(not Path(BROWSER).exists(), reason="cần Chromium để chạy bot thật")
def test_bot_captures_meeting_audio(tmp_path, monkeypatch):
    pytest.importorskip("playwright")
    fw = pytest.importorskip("faster_whisper")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "BOT_BROWSER_PATH", BROWSER)
    monkeypatch.setattr(config, "BOT_HEADLESS", True)
    monkeypatch.setattr(config, "BOT_CHUNK_SECONDS", 3)

    chunks = []
    def decode(path, offset, speaker, hint=""):
        audio = fw.decode_audio(path)
        spectrum = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1 / 16000)
        band = lambda f: spectrum[(freqs > f - 20) & (freqs < f + 20)].max()
        chunks.append({"offset": offset, "seconds": len(audio) / 16000, "rms": float(np.sqrt((audio ** 2).mean())),
                       "has440": band(440) > 50 * np.median(spectrum), "has880": band(880) > 50 * np.median(spectrum)})
        return []
    monkeypatch.setattr(live, "_transcribe", decode)

    site = Path(__file__).parent / "fake_meeting"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    m = store.create("botlocal", "owner", status="joining", platform="Trang họp")
    done = threading.Event()
    result = {}
    meetbot.start(m["id"], f"http://127.0.0.1:{srv.server_port}/", "generic", "", lambda mid, ok: (result.update(ok=ok), done.set()))
    try:
        for _ in range(60):
            if store.get(m["id"])["status"] == "recording":
                break
            time.sleep(0.5)
        assert store.get(m["id"])["status"] == "recording"
        time.sleep(7.5)
        meetbot.stop(m["id"])
        assert done.wait(30) and result["ok"]
        live.wait_idle()
    finally:
        srv.shutdown()
    assert len(chunks) >= 2, chunks
    assert all(c["rms"] > 0.01 for c in chunks), chunks                      # có tiếng, không phải im lặng
    assert any(c["has440"] for c in chunks), "không thu được âm thanh WebRTC"
    assert any(c["has880"] for c in chunks), "không thu được âm thanh WebAudio"
    assert store.get(m["id"])["status"] == "finishing"


def test_parse_teams_invite_from_user():
    from app.invite import parse
    text = """Microsoft Teams meeting
Join: https://teams.microsoft.com/meet/46303252758087?p=qLkgJjIICYx4MswfyL
Meeting ID: 463 032 527 580 87
Passcode: 723uD9GF"""
    f = parse(text)
    assert f["platform"] == "teams" and f["url"] == "https://teams.microsoft.com/meet/46303252758087?p=qLkgJjIICYx4MswfyL"
    assert f["meeting_id"] == "463 032 527 580 87" and f["passcode"] == "723uD9GF"
    only_id = parse("Microsoft Teams meeting\nMeeting ID: 463 032 527 580 87\nPasscode: 723uD9GF")
    assert only_id["url"] == "https://teams.microsoft.com/meet/46303252758087?p=723uD9GF"
    z = parse("Join Zoom Meeting\nMeeting ID: 812 3456 7890\nPasscode: 123456")
    assert z["url"] == "https://app.zoom.us/wc/join/81234567890" and z["passcode"] == "123456"
    assert parse("meet.google.com/abc-defg-hij")["url"] == "https://meet.google.com/abc-defg-hij"
    assert parse("https://evil.com/?u=meet.google.com") is None and parse("xin chào") is None


def test_join_accepts_full_invite_and_explains_when_bot_off(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import asr, main
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(config, "RECALL_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    c = TestClient(main.app)
    invite_text = "Microsoft Teams meeting\nJoin: https://teams.microsoft.com/meet/46303252758087?p=qLkgJjIICYx4MswfyL\nPasscode: 723uD9GF"
    assert c.post("/api/invite/parse", json={"text": invite_text}).json()["platform_name"] == "Microsoft Teams"
    monkeypatch.setattr(config, "LOCAL_BOT", False)
    cfg = c.get("/api/config").json()
    assert cfg["local_bot_enabled"] is False and "chay-tren-may.bat" in cfg["local_bot_reason"]
    assert "chay-tren-may.bat" in c.post("/api/meetings/join", json={"meeting_url": invite_text}).json()["detail"]
    monkeypatch.setattr(config, "LOCAL_BOT", True)
    monkeypatch.setattr(asr, "available", lambda: True)
    started = {}
    monkeypatch.setattr(meetbot, "start", lambda mid, url, platform, hint, on_done, passcode="": started.update(url=url, platform=platform, passcode=passcode))
    r = c.post("/api/meetings/join", json={"meeting_url": invite_text})
    assert r.status_code == 200 and r.json()["platform"] == "Microsoft Teams"
    assert started == {"url": "https://teams.microsoft.com/meet/46303252758087?p=qLkgJjIICYx4MswfyL", "platform": "teams", "passcode": "723uD9GF"}
