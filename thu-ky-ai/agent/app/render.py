"""Xuất biên bản ra Markdown và Word (.docx) theo thể thức biên bản hành chính."""
from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm, RGBColor

from .minutes import Minutes, MEETING_TYPE_LABELS


def to_markdown(m: Minutes, meeting_date: date | None = None, platform: str = "") -> str:
    d = (meeting_date or date.today()).strftime("%d/%m/%Y")
    out = [f"# BIÊN BẢN HỌP: {m.title}", ""]
    meta = [MEETING_TYPE_LABELS.get(m.meeting_type, "Cuộc họp"), d]
    if platform:
        meta.append(platform)
    out += [" · ".join(meta), "", f"**Mục đích:** {m.purpose}", f"**Chủ trì:** {m.chair}",
            f"**Thành phần tham dự:** {', '.join(m.attendees) or 'Chưa xác định'}", ""]

    def points(title, items):
        if not items:
            return
        out.append(f"## {title}")
        for p in items:
            out.append(f"- {p.text} `[{p.timestamp}]`")
        out.append("")

    points("Nội dung chính", m.summary)
    points("Quyết định", m.decisions)
    if m.action_items:
        out += ["## Việc cần làm", "", "| Việc | Phụ trách | Hạn | Mốc |", "|---|---|---|---|"]
        out += [f"| {a.task} | {a.owner} | {a.deadline} | {a.timestamp} |" for a in m.action_items]
        out.append("")
    points("Vấn đề còn mở", m.open_questions)
    points("Rủi ro", m.risks)
    if m.uncertain:
        out.append("## Cần kiểm tra lại")
        out += [f"- **{u.term}**: {u.reason} `[{u.timestamp}]`" for u in m.uncertain]
        out.append("")
    return "\n".join(out)


def _para(doc, text="", *, bold=False, italic=False, size=13, align=None, after=4):
    p = doc.add_paragraph()
    if text:
        r = p.add_run(text)
        r.bold, r.italic, r.font.size = bold, italic, Pt(size)
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    return p


def to_docx(m: Minutes, meeting_date: date | None = None, platform: str = "", organization: str = "") -> bytes:
    d = meeting_date or date.today()
    doc = Document()
    for s in doc.sections:
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)
        s.left_margin, s.right_margin = Cm(3), Cm(2)
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Times New Roman", Pt(13)

    # Phần đầu: tên cơ quan bên trái, quốc hiệu và tiêu ngữ bên phải (NĐ 30/2020/NĐ-CP)
    head = doc.add_table(rows=2, cols=2)
    head.autofit = True
    left, right = head.cell(0, 0), head.cell(0, 1)
    left.paragraphs[0].add_run((organization or "TÊN CƠ QUAN, TỔ CHỨC").upper()).bold = True
    left.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    rq = right.paragraphs[0]
    rq.add_run("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM").bold = True
    rq.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tn = right.add_paragraph()
    tn.add_run("Độc lập - Tự do - Hạnh phúc").bold = True
    tn.alignment = WD_ALIGN_PARAGRAPH.CENTER
    head.cell(1, 0).paragraphs[0].add_run("Số:      /BB-...")
    head.cell(1, 0).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    dl = head.cell(1, 1).paragraphs[0].add_run(f"..., ngày {d.day:02d} tháng {d.month:02d} năm {d.year}")
    dl.italic = True
    head.cell(1, 1).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for row in head.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(12)

    _para(doc, after=6)
    _para(doc, "BIÊN BẢN HỌP", bold=True, size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
    _para(doc, m.title, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)

    _para(doc, f"Thời gian: ngày {d.strftime('%d/%m/%Y')}" + (f". Hình thức: trực tuyến qua {platform}" if platform else ""))
    _para(doc, f"Chủ trì: {m.chair}")
    _para(doc, f"Thành phần tham dự: {', '.join(m.attendees) or 'Chưa xác định'}")
    _para(doc, f"Mục đích: {m.purpose}", after=10)

    def section(title, items):
        if not items:
            return
        _para(doc, title, bold=True, after=4)
        for i, p in enumerate(items, 1):
            para = _para(doc, f"{i}. {p.text} ")
            ts = para.add_run(f"[{p.timestamp}]")
            ts.font.size, ts.font.color.rgb = Pt(10), RGBColor(0x23, 0x46, 0xC8)

    section("I. NỘI DUNG CUỘC HỌP", m.summary)
    section("II. KẾT LUẬN, QUYẾT ĐỊNH", m.decisions)
    if m.action_items:
        _para(doc, "III. PHÂN CÔNG THỰC HIỆN", bold=True)
        t = doc.add_table(rows=1, cols=4)
        t.style = "Table Grid"
        for cell, h in zip(t.rows[0].cells, ["Nội dung công việc", "Người phụ trách", "Thời hạn", "Mốc"]):
            cell.paragraphs[0].add_run(h).bold = True
        for a in m.action_items:
            row = t.add_row().cells
            for cell, v in zip(row, [a.task, a.owner, a.deadline, a.timestamp]):
                cell.text = v
        _para(doc, after=8)
    section("IV. VẤN ĐỀ CÒN BỎ NGỎ", m.open_questions)
    section("V. RỦI RO", m.risks)

    _para(doc, "Biên bản được lập trên cơ sở ghi âm cuộc họp, các mốc thời gian dẫn chiếu tới bản ghi gốc.", italic=True, size=12, after=16)
    sign = doc.add_table(rows=1, cols=2)
    for cell, (role, name) in zip(sign.rows[0].cells, [("THƯ KÝ", ""), ("CHỦ TRÌ", m.chair if m.chair != "Chưa xác định" else "")]):
        p = cell.paragraphs[0]
        p.add_run(role).bold = True
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        n = cell.add_paragraph()
        n.add_run("(Ký, ghi rõ họ tên)").italic = True
        n.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if name:
            nm = cell.add_paragraph("\n\n\n" + name)
            nm.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
