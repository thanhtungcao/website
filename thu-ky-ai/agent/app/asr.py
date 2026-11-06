"""Chuyển giọng nói thành chữ ngay trên máy chủ bằng faster-whisper (miễn phí, không gửi âm thanh ra ngoài).

Cài thêm:  pip install -r requirements-asr.txt
Model mặc định "small" chạy được trên CPU; máy có GPU nên dùng "large-v3-turbo" để chính xác hơn.
Model được tải từ HuggingFace ở lần chạy đầu và lưu trong bộ nhớ đệm.
"""
from __future__ import annotations

import threading

from . import config
from .transcript import Segment

_model = None
_lock = threading.Lock()


def available() -> bool:
    if not config.ASR_ENABLED:
        return False
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(config.ASR_MODEL, device=config.ASR_DEVICE, compute_type=config.ASR_COMPUTE_TYPE)
        return _model


def transcribe(path: str, offset: float, speaker: str, hint: str = "") -> list[Segment]:
    """Chép lời một đoạn âm thanh (webm/opus, mp4, wav...). `offset` là giây tính từ đầu buổi ghi."""
    segments, _info = _get_model().transcribe(
        path,
        language=config.ASR_LANGUAGE,
        vad_filter=True,                   # bỏ đoạn im lặng, giảm "ảo giác" chữ
        beam_size=5,
        condition_on_previous_text=False,
        initial_prompt=hint or None,       # tên riêng, thuật ngữ giúp nhận dạng đúng
    )
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append(Segment(round(offset + s.start, 2), speaker, text))
    return out
