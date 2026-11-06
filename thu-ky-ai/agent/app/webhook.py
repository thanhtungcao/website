"""Xác thực chữ ký webhook của Recall.ai (định dạng Svix).

Recall ký mỗi webhook bằng HMAC-SHA256 trên chuỗi "{svix-id}.{svix-timestamp}.{body}"
với khóa bí mật dạng "whsec_<base64>". Header svix-signature chứa một hoặc nhiều
chữ ký "v1,<base64>" phân tách bằng dấu cách.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def verify(secret: str, headers: dict, body: bytes, tolerance: int = 300) -> bool:
    msg_id = headers.get("svix-id") or headers.get("webhook-id")
    ts = headers.get("svix-timestamp") or headers.get("webhook-timestamp")
    sigs = headers.get("svix-signature") or headers.get("webhook-signature")
    if not (msg_id and ts and sigs):
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
    except (ValueError, IndexError):
        return False
    expected = base64.b64encode(
        hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return any(hmac.compare_digest(expected, s.split(",", 1)[-1]) for s in sigs.split())
