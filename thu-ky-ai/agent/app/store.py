"""Lưu cuộc họp trong SQLite. Đủ cho MVP; thay bằng Postgres khi có nhiều người dùng."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,          -- upload | bot
            platform TEXT,
            meeting_url TEXT,
            bot_id TEXT,
            status TEXT NOT NULL,          -- joining | recording | processing | ready | error
            error TEXT,
            transcript TEXT,               -- JSON danh sách segment
            minutes TEXT                   -- JSON biên bản
        )"""
    )
    return c


def create(source: str, **fields) -> dict:
    mid = uuid.uuid4().hex[:12]
    row = {"id": mid, "created_at": datetime.now(timezone.utc).isoformat(), "source": source,
           "status": fields.pop("status", "processing"), **fields}
    with _lock, _conn() as c:
        cols = ",".join(row)
        c.execute(f"INSERT INTO meetings ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
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


def get(mid: str) -> dict | None:
    with _conn() as c:
        return _decode(c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone())


def by_bot(bot_id: str) -> dict | None:
    with _conn() as c:
        return _decode(c.execute("SELECT * FROM meetings WHERE bot_id=?", (bot_id,)).fetchone())


def list_all(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, created_at, source, platform, status, error, minutes FROM meetings "
                         "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        m = json.loads(d.pop("minutes")) if d["minutes"] else None
        d["title"] = m["title"] if m else None
        d["action_count"] = len(m["action_items"]) if m else 0
        out.append(d)
    return out
