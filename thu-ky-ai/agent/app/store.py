"""Lưu cuộc họp trong SQLite. Mỗi cuộc họp thuộc về một không gian làm việc (owner),
người dùng chỉ thấy cuộc họp của chính mình."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

from . import config

_lock = threading.Lock()
_ready_for: str | None = None

_COLUMNS = {
    "id": "TEXT PRIMARY KEY",
    "owner": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL",
    "source": "TEXT NOT NULL",          # upload | bot
    "platform": "TEXT",
    "meeting_url": "TEXT",
    "bot_id": "TEXT",
    "status": "TEXT NOT NULL",          # joining | recording | processing | ready | error
    "error": "TEXT",
    "transcript": "TEXT",               # JSON danh sách segment
    "minutes": "TEXT",                  # JSON biên bản
}


def _conn() -> sqlite3.Connection:
    global _ready_for
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    if _ready_for != config.DB_PATH:
        c.execute("CREATE TABLE IF NOT EXISTS meetings (" + ",".join(f"{k} {v}" for k, v in _COLUMNS.items()) + ")")
        have = {r[1] for r in c.execute("PRAGMA table_info(meetings)")}
        for k, v in _COLUMNS.items():  # nâng cấp CSDL cũ
            if k not in have:
                c.execute(f"ALTER TABLE meetings ADD COLUMN {k} {v}")
        c.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT, subject TEXT, n INTEGER, PRIMARY KEY (day, subject))")
        c.execute("CREATE INDEX IF NOT EXISTS meetings_owner ON meetings(owner, created_at)")
        c.commit()
        _ready_for = config.DB_PATH
    return c


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(source: str, owner: str, **fields) -> dict:
    mid = uuid.uuid4().hex[:12]
    row = {"id": mid, "owner": owner, "created_at": _now().isoformat(), "source": source,
           "status": fields.pop("status", "processing"), **fields}
    with _lock, _conn() as c:
        c.execute(f"INSERT INTO meetings ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    return get(mid)


def update(mid: str, **fields) -> None:
    for k in ("transcript", "minutes"):
        if k in fields and not isinstance(fields[k], (str, type(None))):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    with _lock, _conn() as c:
        c.execute(f"UPDATE meetings SET {','.join(f'{k}=?' for k in fields)} WHERE id=?", [*fields.values(), mid])


def _decode(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("transcript", "minutes"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def get(mid: str, owner: str | None = None) -> dict | None:
    with _conn() as c:
        m = _decode(c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone())
    if m and owner is not None and m["owner"] != owner:
        return None
    return m


def by_bot(bot_id: str) -> dict | None:
    with _conn() as c:
        return _decode(c.execute("SELECT * FROM meetings WHERE bot_id=?", (bot_id,)).fetchone())


def delete(mid: str, owner: str) -> bool:
    with _lock, _conn() as c:
        return c.execute("DELETE FROM meetings WHERE id=? AND owner=?", (mid, owner)).rowcount > 0


def list_for(owner: str, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, created_at, source, platform, status, error, minutes FROM meetings "
                         "WHERE owner=? ORDER BY created_at DESC LIMIT ?", (owner, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        m = json.loads(d.pop("minutes")) if d["minutes"] else None
        d["title"] = m["title"] if m else None
        d["action_count"] = len(m["action_items"]) if m else 0
        out.append(d)
    return out


def purge_old() -> int:
    """Xóa cuộc họp quá hạn lưu trữ và số liệu sử dụng cũ."""
    if config.RETENTION_DAYS <= 0:
        return 0
    cutoff = (_now() - timedelta(days=config.RETENTION_DAYS)).isoformat()
    with _lock, _conn() as c:
        n = c.execute("DELETE FROM meetings WHERE created_at < ?", (cutoff,)).rowcount
        c.execute("DELETE FROM usage WHERE day < ?", ((_now() - timedelta(days=2)).date().isoformat(),))
    return n


# ---------- Hạn mức sử dụng miễn phí ----------

def usage_today(subject: str) -> int:
    with _conn() as c:
        r = c.execute("SELECT n FROM usage WHERE day=? AND subject=?", (_now().date().isoformat(), subject)).fetchone()
    return r["n"] if r else 0


def try_consume(subjects: list[str], limit: int, global_limit: int) -> bool:
    """Trừ một lượt cho mọi subject nếu chưa ai vượt hạn mức. Trả False nếu đã hết lượt."""
    day = _now().date().isoformat()
    with _lock, _conn() as c:
        def used(s):
            r = c.execute("SELECT n FROM usage WHERE day=? AND subject=?", (day, s)).fetchone()
            return r["n"] if r else 0
        if limit > 0 and any(used(s) >= limit for s in subjects):
            return False
        if global_limit > 0 and used("*") >= global_limit:
            return False
        for s in [*subjects, "*"]:
            c.execute("INSERT INTO usage(day, subject, n) VALUES (?,?,1) "
                      "ON CONFLICT(day, subject) DO UPDATE SET n = n + 1", (day, s))
    return True


def refund(subjects: list[str]) -> None:
    day = _now().date().isoformat()
    with _lock, _conn() as c:
        for s in [*subjects, "*"]:
            c.execute("UPDATE usage SET n = MAX(n - 1, 0) WHERE day=? AND subject=?", (day, s))
