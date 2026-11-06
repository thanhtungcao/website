"""Tạo biên bản từ file transcript ngay trên dòng lệnh.

Ví dụ:
    python cli.py samples/hop-an-phat.vtt
    python cli.py samples/hop-an-phat.vtt --docx bien-ban.docx --org "Công ty ABC"
"""
import argparse
import sys
from pathlib import Path

from app.minutes import MinutesError, generate_minutes
from app.render import to_docx, to_markdown
from app.transcript import parse_transcript


def main() -> int:
    ap = argparse.ArgumentParser(description="Thư Ký AI: tạo biên bản họp từ transcript")
    ap.add_argument("transcript", type=Path, help="File .vtt, .srt, .txt hoặc JSON của Recall.ai")
    ap.add_argument("--docx", type=Path, help="Xuất thêm file Word theo thể thức biên bản hành chính")
    ap.add_argument("--org", default="", help="Tên cơ quan, tổ chức in ở đầu biên bản Word")
    ap.add_argument("--context", default="", help="Thông tin thêm về cuộc họp")
    ap.add_argument("--glossary", default="", help="Tên riêng, thuật ngữ, phân tách bằng dấu phẩy")
    args = ap.parse_args()

    segments = parse_transcript(args.transcript.read_text(encoding="utf-8"), args.transcript.name)
    print(f"Đã đọc {len(segments)} đoạn hội thoại. Đang tạo biên bản...", file=sys.stderr)
    glossary = [t.strip() for t in args.glossary.split(",") if t.strip()] or None
    try:
        minutes = generate_minutes(segments, glossary=glossary, context=args.context)
    except MinutesError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    print(to_markdown(minutes))
    if args.docx:
        args.docx.write_bytes(to_docx(minutes, organization=args.org))
        print(f"Đã lưu {args.docx}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
