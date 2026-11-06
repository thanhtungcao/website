"""Đọc lời mời họp mà người dùng dán vào (chỉ link, hoặc cả đoạn lời mời Teams / Zoom / Google Meet)
và rút ra link vào họp, Meeting ID, Passcode."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

PLATFORM_NAMES = {"meet": "Google Meet", "zoom": "Zoom", "teams": "Microsoft Teams"}

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_ID = re.compile(r"(?:meeting\s*id|id\s*cuộc\s*họp|mã\s*cuộc\s*họp|id)\s*[:：]?\s*((?:\d[\s ]?){9,16})", re.I)
_PASS = re.compile(r"(?:passcode|password|mật\s*mã|mật\s*khẩu)\s*[:：]?\s*([A-Za-z0-9@#$%^&*._\-]{3,32})", re.I)
_MEET_CODE = re.compile(r"\b([a-z]{3}-[a-z]{4}-[a-z]{3})\b")


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "meet.google.com":
        return "meet"
    if host == "zoom.us" or host.endswith(".zoom.us"):
        return "zoom"
    if host in {"teams.microsoft.com", "teams.live.com"} or host.endswith(".teams.microsoft.com"):
        return "teams"
    return ""


def parse(text: str) -> dict | None:
    """Trả về {url, platform, platform_name, meeting_id, passcode} hoặc None nếu không nhận ra."""
    text = (text or "").strip()
    if not text:
        return None
    m_id = _ID.search(text)
    meeting_id = re.sub(r"\D", "", m_id.group(1)) if m_id else ""
    m_pass = _PASS.search(text)
    passcode = m_pass.group(1) if m_pass else ""

    url, platform = "", ""
    for raw in _URL.findall(text):
        candidate = raw.rstrip(".,;")
        p = platform_of(candidate)
        if p:
            url, platform = candidate, p
            break

    lower = text.lower()
    if not url:
        if "teams" in lower and meeting_id:
            platform = "teams"
            url = f"https://teams.microsoft.com/meet/{meeting_id}" + (f"?p={passcode}" if passcode else "")
        elif "zoom" in lower and meeting_id:
            platform = "zoom"
            url = f"https://app.zoom.us/wc/join/{meeting_id}"
        elif _MEET_CODE.search(lower):
            platform = "meet"
            url = f"https://meet.google.com/{_MEET_CODE.search(lower).group(1)}"
    if not url:
        return None

    if platform == "teams" and not passcode:
        passcode = parse_qs(urlparse(url).query).get("p", [""])[0]
    if platform == "teams" and not meeting_id:
        mm = re.search(r"/meet/(\d{9,16})", urlparse(url).path)
        meeting_id = mm.group(1) if mm else ""
    if platform == "zoom" and not meeting_id:
        mm = re.search(r"/(?:j|w|s|wc/join|wc)/(\d{9,12})", urlparse(url).path)
        meeting_id = mm.group(1) if mm else ""
    return {
        "url": url,
        "platform": platform,
        "platform_name": PLATFORM_NAMES[platform],
        "meeting_id": _group(meeting_id),
        "passcode": passcode,
    }


def _group(digits: str) -> str:
    """463032527580 87 -> '463 032 527 580 87' cho dễ đọc."""
    return " ".join(digits[i:i + 3] for i in range(0, len(digits), 3)) if digits else ""
