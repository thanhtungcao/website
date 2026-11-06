"""Thư Ký AI: máy chủ web.

Chạy:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import recall, store
from .minutes import Minutes, MinutesError, generate_minutes
from .render import to_docx, to_markdown
from .transcript import Segment, parse_recall_json, parse_transcript

log = logging.getLogger("thukyai")
app = FastAPI(title="Thư Ký AI")
STATIC = Path(__file__).parent / "static"

ACTIVE_BOT_STATES = {"ready", "joining_call", "in_waiting_room", "in_call_not_recording",
                     "in_call_recording", "recording_permission_allowed", "queued"}


def _process(mid: str, segments: list[Segment], context: str = "") -> None:
    """Chạy nền: tạo biên bản từ transcript và lưu lại."""
    store.update(mid, status="processing", transcript=[s.to_dict() for s in segments])
    try:
        minutes = generate_minutes(segments, context=context)
        store.update(mid, status="ready", minutes=minutes.model_dump(), error=None)
    except MinutesError as e:
        store.update(mid, status="error", error=str(e))
    except Exception:  # lỗi không lường trước vẫn phải hiện cho người dùng
        log.exception("Tạo biên bản thất bại cho %s", mid)
        store.update(mid, status="error", error="Có lỗi khi tạo biên bản. Xem log máy chủ.")


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
        store.update(m["id"], status="processing")  # cuộc họp đã kết thúc, transcript đang được xử lý
        return store.get(m["id"])
    segments = parse_recall_json(recall.download_transcript(url))
    if background is not None:
        store.update(m["id"], status="processing")
        background.add_task(_process, m["id"], segments)
    else:
        _process(m["id"], segments)
    return store.get(m["id"])


# ---------- Trang web ----------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


# ---------- API ----------

@app.post("/api/meetings/upload")
async def upload(background: BackgroundTasks, file: UploadFile = File(...), context: str = Form("")):
    raw = (await file.read()).decode("utf-8", errors="replace")
    segments = parse_transcript(raw, file.filename or "")
    if not segments:
        raise HTTPException(400, "Không đọc được nội dung transcript. Hỗ trợ .vtt, .srt, .txt hoặc JSON của Recall.ai.")
    m = store.create("upload", status="processing", platform="Tải lên")
    background.add_task(_process, m["id"], segments, context)
    return m


class JoinRequest(BaseModel):
    meeting_url: str
    join_at: str | None = None


@app.post("/api/meetings/join")
def join(req: JoinRequest):
    try:
        bot = recall.create_bot(req.meeting_url, req.join_at)
    except recall.RecallError as e:
        raise HTTPException(400, str(e))
    return store.create("bot", status="joining", platform=recall.detect_platform(req.meeting_url),
                        meeting_url=req.meeting_url, bot_id=bot["id"])


@app.post("/api/meetings/{mid}/refresh")
def refresh(mid: str, background: BackgroundTasks):
    m = store.get(mid)
    if not m:
        raise HTTPException(404, "Không tìm thấy cuộc họp.")
    if m["source"] == "bot" and m["status"] in {"joining", "recording", "processing"} and not m["minutes"]:
        try:
            return _finish_bot_meeting(m, background)
        except recall.RecallError as e:
            raise HTTPException(502, str(e))
    return m


@app.post("/api/webhooks/recall")
async def recall_webhook(request: Request, background: BackgroundTasks):
    """Đặt URL này trong bảng điều khiển Recall.ai cho sự kiện trạng thái bot và transcript."""
    payload = await request.json()
    bot_id = recall.bot_id_from_webhook(payload)
    m = store.by_bot(bot_id) if bot_id else None
    if m and not m["minutes"]:
        try:
            _finish_bot_meeting(m, background)
        except recall.RecallError:
            log.exception("Không xử lý được webhook cho bot %s", bot_id)
    return {"ok": True}


@app.get("/api/meetings")
def list_meetings():
    return store.list_all()


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str):
    m = store.get(mid)
    if not m:
        raise HTTPException(404, "Không tìm thấy cuộc họp.")
    return m


def _ready(mid: str) -> tuple[dict, Minutes, date]:
    m = store.get(mid)
    if not m or not m["minutes"]:
        raise HTTPException(404, "Biên bản chưa sẵn sàng.")
    return m, Minutes.model_validate(m["minutes"]), datetime.fromisoformat(m["created_at"]).date()


@app.get("/api/meetings/{mid}/minutes.md")
def minutes_md(mid: str):
    m, minutes, d = _ready(mid)
    return PlainTextResponse(to_markdown(minutes, d, m["platform"] or ""), media_type="text/markdown; charset=utf-8")


@app.get("/api/meetings/{mid}/minutes.docx")
def minutes_docx(mid: str, org: str = ""):
    m, minutes, d = _ready(mid)
    data = to_docx(minutes, d, m["platform"] if m["source"] == "bot" else "", org)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="bien-ban-{mid}.docx"'})
