"""Thư Ký AI: máy chủ web.

Chạy:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import asr, config, live, recall, store, webhook
from .minutes import Minutes, MinutesError, generate_minutes
from .render import to_docx, to_markdown
from .transcript import Segment, parse_recall_json, parse_transcript

log = logging.getLogger("thukyai")
app = FastAPI(title="Thư Ký AI", docs_url=None, redoc_url=None)
STATIC = Path(__file__).parent / "static"
COOKIE = "tk_ws"

ACTIVE_BOT_STATES = {"ready", "joining_call", "in_waiting_room", "in_call_not_recording",
                     "in_call_recording", "recording_permission_allowed", "queued"}


def server_has_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---------- Không gian làm việc ẩn danh theo trình duyệt ----------

_last_purge = 0.0


@app.middleware("http")
async def workspace_cookie(request: Request, call_next):
    global _last_purge
    if time.time() - _last_purge > 3600:
        _last_purge = time.time()
        store.purge_old()
    ws = request.cookies.get(COOKIE)
    fresh = not ws or len(ws) != 32
    if fresh:
        ws = secrets.token_hex(16)
    request.state.ws = ws
    response = await call_next(request)
    if fresh:
        response.set_cookie(COOKIE, ws, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=config.SECURE_COOKIES)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


def owner(request: Request) -> str:
    return request.state.ws


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def take_quota(request: Request, own_key: str | None) -> list[str] | None:
    """Trả về danh sách subject đã trừ lượt (để hoàn lại khi lỗi), hoặc None nếu dùng khóa riêng."""
    if own_key:
        return None
    if not server_has_key():
        raise HTTPException(400, "Bản cài đặt này chưa có khóa Claude API chung. Hãy nhập khóa của bạn trong phần Cài đặt.")
    subjects = [f"ws:{owner(request)}", f"ip:{client_ip(request)}"]
    if not store.try_consume(subjects, config.FREE_DAILY_LIMIT, config.GLOBAL_DAILY_LIMIT):
        raise HTTPException(429, f"Bạn đã dùng hết {config.FREE_DAILY_LIMIT} biên bản miễn phí hôm nay. "
                                 "Quay lại vào ngày mai, hoặc nhập khóa Claude API của riêng bạn để dùng không giới hạn.")
    return subjects


def _process(mid: str, segments: list[Segment], context: str = "", api_key: str | None = None,
             charged: list[str] | None = None) -> None:
    """Chạy nền: tạo biên bản từ transcript và lưu lại. Khóa riêng của người dùng chỉ nằm trong bộ nhớ."""
    store.update(mid, status="processing", transcript=[s.to_dict() for s in segments])
    try:
        minutes = generate_minutes(segments, context=context, api_key=api_key)
        store.update(mid, status="ready", minutes=minutes.model_dump(), error=None)
        return
    except MinutesError as e:
        store.update(mid, status="error", error=str(e))
    except Exception:
        log.exception("Tạo biên bản thất bại cho %s", mid)
        store.update(mid, status="error", error="Có lỗi khi tạo biên bản. Vui lòng thử lại.")
    if charged:
        store.refund(charged)  # lỗi thì không tính lượt


def _finish_bot_meeting(m: dict, background: BackgroundTasks | None = None) -> dict:
    """Kiểm tra bot trên Recall; nếu cuộc họp đã xong thì tải transcript và tạo biên bản."""
    bot = recall.get_bot(m["bot_id"])
    status = recall.bot_status(bot)
    if status in ACTIVE_BOT_STATES:
        store.update(m["id"], status="recording" if "call" in status else "joining")
        return store.get(m["id"])
    if status in {"fatal", "call_ended_with_error"}:
        store.update(m["id"], status="error", error=f"Bot gặp lỗi khi tham gia cuộc họp ({status}).")
        return store.get(m["id"])
    url = recall.transcript_url(bot)
    if not url:
        store.update(m["id"], status="processing")
        return store.get(m["id"])
    segments = parse_recall_json(recall.download_transcript(url))
    store.update(m["id"], status="processing", transcript=[s.to_dict() for s in segments])
    if background is not None:
        background.add_task(_process, m["id"], segments)
    else:
        _process(m["id"], segments)
    return store.get(m["id"])


# ---------- Trang web ----------

@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(STATIC / "landing.html")


@app.get("/app", include_in_schema=False)
def web_app():
    return FileResponse(STATIC / "index.html")


@app.get("/privacy", include_in_schema=False)
def privacy():
    return FileResponse(STATIC / "privacy.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


# ---------- API ----------

@app.get("/api/config")
def get_config(request: Request):
    return {
        "free_daily_limit": config.FREE_DAILY_LIMIT,
        "used_today": store.usage_today(f"ws:{owner(request)}"),
        "server_key": server_has_key(),
        "bot_enabled": bool(config.RECALL_API_KEY),
        "retention_days": config.RETENTION_DAYS,
        "max_upload_mb": round(config.MAX_UPLOAD_BYTES / 1_000_000, 1),
        "live_enabled": asr.available(),
    }


@app.post("/api/meetings/upload")
async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                 context: str = Form(""), x_anthropic_key: str | None = Header(None)):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File quá lớn. Giới hạn {config.MAX_UPLOAD_BYTES // 1_000_000} MB.")
    segments = parse_transcript(data.decode("utf-8", errors="replace"), file.filename or "")
    if not segments:
        raise HTTPException(400, "Không đọc được nội dung transcript. Hỗ trợ .vtt, .srt, .txt hoặc JSON của Recall.ai.")
    if sum(len(s.text) for s in segments) > config.MAX_TRANSCRIPT_CHARS:
        raise HTTPException(413, "Transcript quá dài cho một biên bản. Hãy chia thành nhiều phần.")
    key = (x_anthropic_key or "").strip() or None
    charged = take_quota(request, key)
    m = store.create("upload", owner(request), status="processing", platform="Tải lên")
    background.add_task(_process, m["id"], segments, context[:2000], key, charged)
    return m


class JoinRequest(BaseModel):
    meeting_url: str
    join_at: str | None = None


@app.post("/api/meetings/join")
def join(req: JoinRequest, request: Request):
    if not config.RECALL_API_KEY:
        raise HTTPException(400, "Bản cài đặt này chưa bật tính năng mời bot. Bạn vẫn có thể tải transcript lên.")
    if not recall.detect_platform(req.meeting_url):
        raise HTTPException(400, "Link họp không hợp lệ. Hỗ trợ Zoom, Google Meet và Microsoft Teams.")
    charged = take_quota(request, None)
    try:
        bot = recall.create_bot(req.meeting_url, req.join_at)
    except recall.RecallError as e:
        store.refund(charged or [])
        raise HTTPException(400, str(e))
    return store.create("bot", owner(request), status="joining", platform=recall.detect_platform(req.meeting_url),
                        meeting_url=req.meeting_url, bot_id=bot["id"])


def _mine(mid: str, request: Request) -> dict:
    m = store.get(mid, owner(request))
    if not m:
        raise HTTPException(404, "Không tìm thấy cuộc họp.")
    return m


@app.post("/api/meetings/{mid}/refresh")
def refresh(mid: str, request: Request, background: BackgroundTasks):
    m = _mine(mid, request)
    if m["source"] == "bot" and m["status"] in {"joining", "recording", "processing"} and not m["minutes"] and not m["transcript"]:
        try:
            return _finish_bot_meeting(m, background)
        except recall.RecallError as e:
            raise HTTPException(502, str(e))
    return m


@app.post("/api/webhooks/recall")
async def recall_webhook(request: Request, background: BackgroundTasks):
    """Đặt URL này trong bảng điều khiển Recall.ai cho sự kiện trạng thái bot."""
    body = await request.body()
    if config.RECALL_WEBHOOK_SECRET and not webhook.verify(config.RECALL_WEBHOOK_SECRET, dict(request.headers), body):
        raise HTTPException(401, "Chữ ký webhook không hợp lệ.")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Body không phải JSON.")
    bot_id = recall.bot_id_from_webhook(payload)
    m = store.by_bot(bot_id) if bot_id else None
    if m and not m["minutes"] and not m["transcript"]:
        try:
            _finish_bot_meeting(m, background)
        except recall.RecallError:
            log.exception("Không xử lý được webhook cho bot %s", bot_id)
    return {"ok": True}


@app.get("/api/meetings")
def list_meetings(request: Request):
    return store.list_for(owner(request))


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str, request: Request):
    m = _mine(mid, request)
    m["pending_chunks"] = live.pending(mid) if m["source"] == "live" else 0
    m.pop("meeting_url", None) if m["source"] == "live" else None
    return m


@app.delete("/api/meetings/{mid}")
def delete_meeting(mid: str, request: Request):
    if not store.delete(mid, owner(request)):
        raise HTTPException(404, "Không tìm thấy cuộc họp.")
    return {"ok": True}


def _ready(mid: str, request: Request) -> tuple[dict, Minutes, date]:
    m = _mine(mid, request)
    if not m["minutes"]:
        raise HTTPException(404, "Biên bản chưa sẵn sàng.")
    return m, Minutes.model_validate(m["minutes"]), datetime.fromisoformat(m["created_at"]).date()


@app.get("/api/meetings/{mid}/minutes.md")
def minutes_md(mid: str, request: Request):
    m, minutes, d = _ready(mid, request)
    return PlainTextResponse(to_markdown(minutes, d, m["platform"] or ""), media_type="text/markdown; charset=utf-8")


@app.get("/api/meetings/{mid}/minutes.docx")
def minutes_docx(mid: str, request: Request, org: str = ""):
    m, minutes, d = _ready(mid, request)
    data = to_docx(minutes, d, m["platform"] if m["source"] == "bot" else "", org[:120])
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="bien-ban-{mid}.docx"'})


# ---------- Ghi trực tiếp: nghe loa và micro, chép lời, tạo biên bản ----------

class LiveStart(BaseModel):
    glossary: str = ""


@app.post("/api/live/start")
def live_start(req: LiveStart, request: Request):
    if not asr.available():
        raise HTTPException(400, "Bản cài đặt này chưa bật ghi trực tiếp (thiếu faster-whisper). "
                                 "Cài bằng: pip install -r requirements-asr.txt")
    m = store.create("live", owner(request), status="recording", platform="Ghi trực tiếp")
    store.update(m["id"], meeting_url=req.glossary[:500])  # lưu gợi ý tên riêng cho bộ chép lời
    return store.get(m["id"])


@app.post("/api/live/{mid}/chunk")
async def live_chunk(mid: str, request: Request, file: UploadFile = File(...),
                     offset: float = Form(...), source: str = Form("system")):
    m = _mine(mid, request)
    if m["source"] != "live" or m["status"] not in {"recording", "finishing"}:
        raise HTTPException(409, "Cuộc họp này không còn đang ghi.")
    if source not in live.SPEAKERS:
        raise HTTPException(400, "Nguồn âm thanh không hợp lệ.")
    if not 0 <= offset <= config.MAX_LIVE_HOURS * 3600:
        raise HTTPException(400, f"Một buổi ghi tối đa {config.MAX_LIVE_HOURS} giờ.")
    data = await file.read(config.MAX_CHUNK_BYTES + 1)
    if len(data) > config.MAX_CHUNK_BYTES:
        raise HTTPException(413, "Đoạn âm thanh quá lớn.")
    if not data:
        return {"ok": True, "pending": live.pending(mid)}
    name = (file.filename or "").lower()
    suffix = ".mp4" if name.endswith((".mp4", ".m4a")) else ".ogg" if name.endswith(".ogg") else ".webm"
    live.add_chunk(mid, data, suffix, offset, source, m["meeting_url"] or "")
    return {"ok": True, "pending": live.pending(mid)}


@app.post("/api/live/{mid}/stop")
def live_stop(mid: str, request: Request, x_anthropic_key: str | None = Header(None)):
    m = _mine(mid, request)
    if m["source"] != "live" or m["status"] != "recording":
        raise HTTPException(409, "Cuộc họp này không còn đang ghi.")
    key = (x_anthropic_key or "").strip() or None
    charged = take_quota(request, key)  # hết lượt: vẫn giữ trạng thái đang ghi để người dùng nhập khóa riêng
    store.update(mid, status="finishing")

    def finish():
        cur = store.get(mid)
        segs = [Segment(**s) for s in (cur["transcript"] or [])]
        if not segs:
            store.update(mid, status="error", error="Không nghe được lời nói nào trong buổi ghi. "
                                                     "Kiểm tra lại đã chọn chia sẻ âm thanh và bật micro chưa.")
            if charged:
                store.refund(charged)
            return
        _process(mid, segs, "Transcript được chép tự động từ âm thanh. 'Người tham dự' là âm thanh phát ra từ loa "
                            "(nhiều người khác nhau), 'Tôi' là người ghi. Hãy suy ra tên người nói từ ngữ cảnh khi có thể.",
                 key, charged)

    live.finish_when_done(mid, finish)
    return {"ok": True, "pending": live.pending(mid)}
