"""Đưa bot vào Zoom / Google Meet / Microsoft Teams qua Recall.ai (API v1).

Recall.ai lo phần khó: bot tham gia cuộc họp, ghi âm, nhận dạng giọng nói và
phân biệt người nói. Module này chỉ gọi REST API của họ.

Lưu ý: các đường dẫn và tên trường theo Recall.ai API v1. Hãy đối chiếu với
https://docs.recall.ai trước khi chạy thật, vì nhà cung cấp có thể thay đổi.
"""
from __future__ import annotations

import httpx

from . import config


class RecallError(RuntimeError):
    pass


def _base() -> str:
    return f"https://{config.RECALL_REGION}.recall.ai/api/v1"


def _headers() -> dict:
    if not config.RECALL_API_KEY:
        raise RecallError("Chưa đặt RECALL_API_KEY nên chưa thể đưa bot vào cuộc họp. Bạn vẫn có thể tải lên file transcript.")
    return {"Authorization": f"Token {config.RECALL_API_KEY}", "Content-Type": "application/json"}


def detect_platform(url: str) -> str:
    u = url.lower()
    if "zoom.us" in u:
        return "Zoom"
    if "meet.google.com" in u:
        return "Google Meet"
    if "teams.microsoft.com" in u or "teams.live.com" in u:
        return "Microsoft Teams"
    return ""


def create_bot(meeting_url: str, join_at: str | None = None) -> dict:
    if not detect_platform(meeting_url):
        raise RecallError("Link họp không hợp lệ. Hỗ trợ Zoom, Google Meet và Microsoft Teams.")
    body = {
        "meeting_url": meeting_url,
        "bot_name": config.BOT_NAME,
        "recording_config": {
            "transcript": {"provider": {"recallai_streaming": {"language_code": config.RECALL_LANGUAGE}}},
        },
        "chat": {
            "on_bot_join": {
                "send_to": "everyone",
                "message": f"{config.BOT_NAME} đang ghi lại cuộc họp này để lập biên bản. "
                           "Nếu bạn không đồng ý, hãy báo người chủ trì để dừng ghi.",
            }
        },
    }
    if join_at:
        body["join_at"] = join_at
    r = httpx.post(f"{_base()}/bot/", headers=_headers(), json=body, timeout=30)
    if r.status_code >= 400:
        raise RecallError(f"Recall.ai trả lỗi {r.status_code}: {r.text[:300]}")
    return r.json()


def get_bot(bot_id: str) -> dict:
    r = httpx.get(f"{_base()}/bot/{bot_id}/", headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise RecallError(f"Recall.ai trả lỗi {r.status_code}: {r.text[:300]}")
    return r.json()


def bot_status(bot: dict) -> str:
    changes = bot.get("status_changes") or []
    return changes[-1].get("code", "unknown") if changes else "queued"


def transcript_url(bot: dict) -> str | None:
    for rec in bot.get("recordings") or []:
        t = ((rec.get("media_shortcuts") or {}).get("transcript") or {})
        url = (t.get("data") or {}).get("download_url")
        if url:
            return url
    return None


def download_transcript(url: str) -> list:
    r = httpx.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def bot_id_from_webhook(payload: dict) -> str | None:
    """Payload webhook của Recall có dạng {event, data: {bot: {id}, ...}}."""
    data = payload.get("data") or {}
    bot = data.get("bot") or {}
    return bot.get("id") or data.get("bot_id")
