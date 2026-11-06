import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


MODEL = os.environ.get("THUKY_MODEL", "claude-opus-5-5")
RECALL_API_KEY = os.environ.get("RECALL_API_KEY", "")
RECALL_REGION = os.environ.get("RECALL_REGION", "us-west-2")
RECALL_LANGUAGE = os.environ.get("RECALL_LANGUAGE", "vi")
RECALL_WEBHOOK_SECRET = os.environ.get("RECALL_WEBHOOK_SECRET", "")
BOT_NAME = os.environ.get("BOT_NAME", "Thư Ký AI")
DB_PATH = os.environ.get("DB_PATH", "thukyai.db")
GLOSSARY = [t.strip() for t in os.environ.get("GLOSSARY", "").split(",") if t.strip()]

# Giới hạn cho bản dùng miễn phí công khai
FREE_DAILY_LIMIT = _int("FREE_DAILY_LIMIT", 5)          # số biên bản / ngày / người dùng (0 = không giới hạn)
GLOBAL_DAILY_LIMIT = _int("GLOBAL_DAILY_LIMIT", 200)    # trần chung cả hệ thống / ngày, chặn chi phí bất thường
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 2_000_000)
MAX_TRANSCRIPT_CHARS = _int("MAX_TRANSCRIPT_CHARS", 300_000)
RETENTION_DAYS = _int("RETENTION_DAYS", 30)
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "1") == "1"
