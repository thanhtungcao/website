import io
from pathlib import Path

from docx import Document

from app.minutes import ActionItem, Minutes, Point, UncertainItem
from app.recall import bot_id_from_webhook, bot_status, detect_platform, transcript_url
from app.render import to_docx, to_markdown
from app.transcript import fmt_ts, parse_transcript, to_prompt_text

SAMPLE = Path(__file__).parent.parent / "samples" / "hop-an-phat.vtt"


def test_parse_vtt_voice_tags():
    segs = parse_transcript(SAMPLE.read_text(encoding="utf-8"), SAMPLE.name)
    assert segs[0].speaker == "Nguyễn Văn Hùng"
    assert segs[0].start == 5
    assert any("tám phần trăm" in s.text for s in segs)
    assert "[17:40] Trần Thị Lan:" in to_prompt_text(segs)


def test_parse_vtt_speaker_prefix_and_merge():
    raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nAn: Xin chào\n\n00:00:03.000 --> 00:00:05.000\nAn: mọi người\n\n00:00:06.000 --> 00:00:08.000\nBình: Chào An\n"
    segs = parse_transcript(raw, "x.vtt")
    assert [(s.speaker, s.text) for s in segs] == [("An", "Xin chào mọi người"), ("Bình", "Chào An")]


def test_parse_srt():
    raw = "1\n00:01:02,500 --> 00:01:04,000\nLan: Em nhận việc này\n"
    segs = parse_transcript(raw, "a.srt")
    assert segs[0].start == 62.5 and segs[0].speaker == "Lan"


def test_parse_plain_with_timestamps():
    raw = "[00:10] Hùng: Bắt đầu họp\n[01:05:30] Lan: Kết thúc\ntiếp tục câu"
    segs = parse_transcript(raw, "notes.txt")
    assert segs[0].start == 10 and segs[1].start == 3930
    assert segs[1].text == "Kết thúc tiếp tục câu"


def test_parse_recall_json():
    raw = '[{"participant":{"name":"Hà"},"words":[{"text":"Xin","start_timestamp":{"relative":12.5}},{"text":"chào"}]}]'
    segs = parse_transcript(raw, "t.json")
    assert (segs[0].speaker, segs[0].start, segs[0].text) == ("Hà", 12.5, "Xin chào")


def test_fmt_ts():
    assert fmt_ts(62) == "01:02" and fmt_ts(3930) == "1:05:30"


def test_recall_helpers():
    assert detect_platform("https://meet.google.com/abc-defg-hij") == "Google Meet"
    assert detect_platform("https://us02web.zoom.us/j/123") == "Zoom"
    assert detect_platform("https://teams.microsoft.com/l/meetup-join/x") == "Microsoft Teams"
    assert detect_platform("https://example.com") == ""
    bot = {"status_changes": [{"code": "joining_call"}, {"code": "done"}],
           "recordings": [{"media_shortcuts": {"transcript": {"data": {"download_url": "https://x/t.json"}}}}]}
    assert bot_status(bot) == "done" and transcript_url(bot) == "https://x/t.json"
    assert bot_id_from_webhook({"event": "bot.done", "data": {"bot": {"id": "b1"}}}) == "b1"


def _minutes() -> Minutes:
    return Minutes(
        title="Chốt hợp đồng An Phát", meeting_type="ban_hang", purpose="Chốt điều khoản hợp đồng",
        chair="Nguyễn Văn Hùng", attendees=["Nguyễn Văn Hùng", "Trần Thị Lan"],
        summary=[Point(text="An Phát muốn giảm giá nếu ký sớm.", timestamp="00:13")],
        decisions=[Point(text="Giảm 8% nếu ký trước 15/11.", timestamp="17:40")],
        action_items=[ActionItem(task="Gửi báo giá mới", owner="Trần Thị Lan", deadline="Thứ Sáu", timestamp="23:05")],
        open_questions=[Point(text="Phí triển khai tính riêng hay gộp.", timestamp="38:20")],
        risks=[], uncertain=[UncertainItem(term="anh Quang", reason="Có thể là anh Quân", timestamp="31:48")],
    )


def test_markdown():
    md = to_markdown(_minutes())
    assert "## Quyết định" in md and "`[17:40]`" in md and "| Gửi báo giá mới | Trần Thị Lan |" in md
    assert "## Rủi ro" not in md  # mục trống thì bỏ


def test_docx_layout():
    doc = Document(io.BytesIO(to_docx(_minutes(), organization="Công ty ABC")))
    text = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in cells and "CÔNG TY ABC" in cells
    assert "BIÊN BẢN HỌP" in text and "II. KẾT LUẬN, QUYẾT ĐỊNH" in text
    assert "Gửi báo giá mới" in cells
