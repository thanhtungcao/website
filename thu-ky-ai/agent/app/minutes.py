"""Tạo biên bản họp có cấu trúc từ transcript bằng Claude."""
from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from . import config
from .transcript import Segment, to_prompt_text

MeetingType = Literal["hanh_chinh", "ban_hang", "giao_ban", "mot_mot", "phong_van", "khac"]

MEETING_TYPE_LABELS = {
    "hanh_chinh": "Họp hành chính",
    "ban_hang": "Gọi bán hàng",
    "giao_ban": "Giao ban",
    "mot_mot": "Họp 1:1",
    "phong_van": "Phỏng vấn",
    "khac": "Cuộc họp",
}


class Point(BaseModel):
    text: str = Field(description="Một ý, viết thành câu hoàn chỉnh bằng tiếng Việt")
    timestamp: str = Field(description="Mốc thời gian trong transcript nơi ý này được nói, dạng MM:SS hoặc H:MM:SS")


class ActionItem(BaseModel):
    task: str = Field(description="Việc cần làm, bắt đầu bằng động từ")
    owner: str = Field(description="Người phụ trách; 'Chưa giao' nếu không ai nhận")
    deadline: str = Field(description="Hạn chót như được nói trong cuộc họp, chuẩn hóa dạng dd/mm nếu có thể; 'Chưa có' nếu không nêu")
    timestamp: str


class UncertainItem(BaseModel):
    term: str = Field(description="Tên riêng, con số, ngày tháng hoặc từ mà bản ghi có thể sai")
    reason: str
    timestamp: str


class Minutes(BaseModel):
    title: str = Field(description="Tên cuộc họp ngắn gọn, cụ thể")
    meeting_type: MeetingType
    purpose: str = Field(description="Mục đích cuộc họp, một câu")
    chair: str = Field(description="Người chủ trì nếu xác định được, nếu không thì 'Chưa xác định'")
    attendees: list[str]
    summary: list[Point] = Field(description="Các nội dung chính đã thảo luận, theo thứ tự")
    decisions: list[Point] = Field(description="Chỉ những điều đã được thống nhất rõ ràng")
    action_items: list[ActionItem]
    open_questions: list[Point] = Field(description="Vấn đề còn bỏ ngỏ, chưa có kết luận")
    risks: list[Point]
    uncertain: list[UncertainItem] = Field(description="Những chỗ người duyệt cần kiểm tra lại")


SYSTEM_PROMPT = """Bạn là thư ký cuộc họp chuyên nghiệp cho doanh nghiệp Việt Nam. Bạn nhận transcript (có thể do máy nhận dạng giọng nói tạo ra, có lỗi chính tả, nói lẫn tiếng Anh) và viết biên bản họp bằng tiếng Việt chuẩn mực, khách quan.

Nguyên tắc:
- Chỉ ghi điều thực sự có trong transcript. Không suy đoán quyết định, người phụ trách hay hạn chót. Khi không rõ, ghi "Chưa giao" hoặc "Chưa có".
- Mỗi ý phải kèm mốc thời gian lấy đúng từ transcript để người đọc nghe lại được.
- Phân biệt rõ: điều đã được thống nhất (quyết định) và điều mới được đề xuất hoặc còn tranh luận (vấn đề còn mở).
- Giữ nguyên thuật ngữ tiếng Anh thông dụng trong công sở (deadline, KPI, demo...) khi người họp dùng chúng, nhưng viết câu bằng tiếng Việt.
- Đưa vào mục cần kiểm tra mọi tên riêng, con số, số tiền, ngày tháng mà bản ghi có dấu hiệu nhận dạng sai hoặc mâu thuẫn.
- Viết ngắn gọn theo văn phong biên bản: câu trần thuật, không dùng ngôi thứ nhất, không bình luận."""


class MinutesError(RuntimeError):
    pass


def generate_minutes(
    segments: list[Segment],
    *,
    glossary: list[str] | None = None,
    context: str = "",
    client: anthropic.Anthropic | None = None,
) -> Minutes:
    if not segments:
        raise MinutesError("Transcript trống, không có gì để tạo biên bản.")
    client = client or anthropic.Anthropic()
    glossary = glossary if glossary is not None else config.GLOSSARY

    parts = []
    if glossary:
        parts.append("Từ điển của tổ chức (dùng để sửa lỗi nhận dạng tên riêng và thuật ngữ):\n" + ", ".join(glossary))
    if context:
        parts.append("Thông tin thêm về cuộc họp:\n" + context)
    parts.append("<transcript>\n" + to_prompt_text(segments) + "\n</transcript>")
    parts.append("Hãy viết biên bản cho cuộc họp trên.")

    try:
        response = client.beta.messages.parse(
            model=config.MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            output_format=Minutes,
        )
    except anthropic.AuthenticationError as e:
        raise MinutesError("Khóa ANTHROPIC_API_KEY không hợp lệ hoặc chưa được đặt.") from e
    except anthropic.RateLimitError as e:
        raise MinutesError("Claude API đang giới hạn tốc độ. Thử lại sau ít phút.") from e
    except anthropic.APIStatusError as e:
        raise MinutesError(f"Claude API trả lỗi {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise MinutesError("Không kết nối được tới Claude API.") from e

    if response.stop_reason == "refusal":
        raise MinutesError("Mô hình từ chối xử lý transcript này.")
    if response.stop_reason == "max_tokens":
        raise MinutesError("Biên bản quá dài, bị cắt giữa chừng. Hãy chia nhỏ transcript.")
    if response.parsed_output is None:
        raise MinutesError("Không đọc được kết quả từ mô hình.")
    return response.parsed_output
