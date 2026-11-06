"""Ghi cuộc họp trực tiếp: trình duyệt gửi từng đoạn âm thanh (loa và micro), máy chủ chép lời
tuần tự trong một luồng nền, nối vào transcript; khi kết thúc thì tạo biên bản."""
from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
from collections import defaultdict
from typing import Callable

from . import asr, store
from .transcript import Segment

log = logging.getLogger("thukyai.live")

SPEAKERS = {"system": "Người tham dự", "mic": "Tôi"}

_jobs: "queue.Queue[tuple[str, str, float, str, str]]" = queue.Queue()
_pending: dict[str, int] = defaultdict(int)
_finishing: dict[str, Callable[[], None]] = {}
_lock = threading.Lock()
_worker: threading.Thread | None = None
_transcribe = asr.transcribe          # thay được trong kiểm thử


def pending(mid: str) -> int:
    with _lock:
        return _pending.get(mid, 0)


def add_chunk(mid: str, data: bytes, suffix: str, offset: float, source: str, hint: str = "") -> None:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="tk-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    with _lock:
        _pending[mid] += 1
    _ensure_worker()
    _jobs.put((mid, path, offset, source, hint))


def finish_when_done(mid: str, callback: Callable[[], None]) -> None:
    """Gọi `callback` khi mọi đoạn âm thanh của cuộc họp đã được chép lời."""
    with _lock:
        if _pending.get(mid, 0) == 0:
            run_now = True
        else:
            _finishing[mid] = callback
            run_now = False
    if run_now:  # không chặn request: tạo biên bản trong luồng riêng
        threading.Thread(target=callback, name="tk-finish", daemon=True).start()


def _append(mid: str, segs: list[Segment]) -> None:
    if not segs:
        return
    m = store.get(mid)  # chỉ luồng nền này ghi transcript của cuộc họp đang ghi
    if not m:
        return
    merged = (m["transcript"] or []) + [s.to_dict() for s in segs]
    merged.sort(key=lambda s: s["start"])
    store.update(mid, transcript=merged)


def _run() -> None:
    while True:
        mid, path, offset, source, hint = _jobs.get()
        try:
            segs = _transcribe(path, offset, SPEAKERS.get(source, "Không rõ"), hint)
            _append(mid, segs)
        except Exception:
            log.exception("Chép lời thất bại (cuộc họp %s, giây %.0f)", mid, offset)
        finally:
            try:
                os.remove(path)        # không giữ file âm thanh sau khi chép lời
            except OSError:
                pass
            with _lock:
                _pending[mid] -= 1
                done = _pending[mid] <= 0
                if done:
                    _pending.pop(mid, None)
                callback = _finishing.pop(mid, None) if done else None
            if callback:
                try:
                    callback()
                except Exception:
                    log.exception("Không tạo được biên bản cho cuộc họp %s", mid)
            _jobs.task_done()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="tk-asr", daemon=True)
            _worker.start()


def wait_idle() -> None:
    """Dùng trong kiểm thử: chờ hàng đợi xử lý xong."""
    _jobs.join()
