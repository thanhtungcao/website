"""Đọc transcript từ nhiều nguồn về một dạng chung: danh sách Segment.

Hỗ trợ:
- WebVTT (.vtt): file transcript xuất từ Zoom, Microsoft Teams, Google Meet
- SRT (.srt)
- Văn bản thường: mỗi dòng "Tên: nội dung" hoặc "[00:12:30] Tên: nội dung"
- JSON transcript của Recall.ai (danh sách người nói kèm từ và mốc thời gian)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict


@dataclass
class Segment:
    start: float  # giây tính từ đầu cuộc họp
    speaker: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_ts(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


_CUE_TIME = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*")
_VTT_VOICE = re.compile(r"^<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>)?$", re.S)
_SPEAKER_LINE = re.compile(r"^(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*[-–]?\s*)?([^:\n]{1,40}):\s*(.+)$")


def _parse_cues(raw: str) -> list[Segment]:
    """Dùng chung cho VTT và SRT: khối cue gồm dòng thời gian và nội dung."""
    segments: list[Segment] = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for block in blocks:
        lines = [l for l in block.strip().split("\n") if l.strip()]
        idx = next((i for i, l in enumerate(lines) if _CUE_TIME.search(l)), None)
        if idx is None:
            continue
        start = parse_ts(lines[idx].split("-->")[0])
        body = " ".join(lines[idx + 1:]).strip()
        if not body:
            continue
        speaker, text = "Không rõ", body
        voice = _VTT_VOICE.match(body)
        if voice:
            speaker, text = voice.group(1).strip(), voice.group(2).strip()
        else:
            m = _SPEAKER_LINE.match(body)
            if m:
                speaker, text = m.group(2).strip(), m.group(3).strip()
        text = re.sub(r"</?[^>]+>", "", text).strip()
        if segments and segments[-1].speaker == speaker and start - segments[-1].start < 30:
            segments[-1].text += " " + text  # gộp các cue liên tiếp của cùng người nói
        else:
            segments.append(Segment(start, speaker, text))
    return segments


def _parse_plain(raw: str) -> list[Segment]:
    segments: list[Segment] = []
    clock = 0.0
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        m = _SPEAKER_LINE.match(line)
        if m:
            if m.group(1):
                clock = parse_ts(m.group(1))
            segments.append(Segment(clock, m.group(2).strip(), m.group(3).strip()))
        elif segments:
            segments[-1].text += " " + line
        else:
            segments.append(Segment(clock, "Không rõ", line))
        clock += 1  # không có mốc thời gian thì giữ thứ tự tăng dần
    return segments


def parse_recall_json(data: list | dict) -> list[Segment]:
    """Transcript Recall.ai: [{participant: {name}, words: [{text, start_timestamp: {relative}}]}]."""
    if isinstance(data, dict):
        data = data.get("transcript") or data.get("results") or []
    segments: list[Segment] = []
    for part in data:
        words = part.get("words") or []
        if not words:
            continue
        who = (part.get("participant") or {}).get("name") or part.get("speaker") or "Không rõ"
        ts = words[0].get("start_timestamp")
        start = ts.get("relative", 0.0) if isinstance(ts, dict) else float(ts or 0)
        text = " ".join(w.get("text", "") for w in words).strip()
        segments.append(Segment(float(start), who, text))
    return segments


def parse_transcript(raw: str, filename: str = "") -> list[Segment]:
    name = filename.lower()
    stripped = raw.lstrip("﻿").strip()
    if name.endswith(".json") or stripped.startswith("[") or stripped.startswith("{"):
        try:
            return parse_recall_json(json.loads(stripped))
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    if stripped.startswith("WEBVTT") or name.endswith((".vtt", ".srt")) or _CUE_TIME.search(stripped[:500]):
        segs = _parse_cues(stripped)
        if segs:
            return segs
    return _parse_plain(stripped)


def to_prompt_text(segments: list[Segment]) -> str:
    return "\n".join(f"[{fmt_ts(s.start)}] {s.speaker}: {s.text}" for s in segments)
