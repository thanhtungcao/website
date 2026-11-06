import os

VERSION = "2026.11.06-4"


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

# Ghi trực tiếp và chép lời trên máy chủ (faster-whisper)
ASR_ENABLED = os.environ.get("ASR_ENABLED", "1") == "1"
ASR_MODEL = os.environ.get("ASR_MODEL", "small")              # tiny | base | small | medium | large-v3 | large-v3-turbo
ASR_DEVICE = os.environ.get("ASR_DEVICE", "auto")             # auto | cpu | cuda
ASR_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")  # int8 cho CPU, float16 cho GPU
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "vi")
MAX_CHUNK_BYTES = _int("MAX_CHUNK_BYTES", 10_000_000)
MAX_LIVE_HOURS = _int("MAX_LIVE_HOURS", 4)

# Bot vào họp chạy trên máy (Playwright + Edge/Chrome). Chỉ bật trên máy cá nhân: bot mở trình duyệt trên máy chủ.
LOCAL_BOT = os.environ.get("LOCAL_BOT", "0") == "1"
BOT_HEADLESS = os.environ.get("BOT_HEADLESS", "0") == "1"      # 0: hiện cửa sổ bot để bạn bấm giúp khi cần
BOT_BROWSER_PATH = os.environ.get("BOT_BROWSER_PATH", "")      # để trống: tự dùng Edge, rồi Chrome
BOT_ADMIT_TIMEOUT_MIN = _int("BOT_ADMIT_TIMEOUT_MIN", 10)       # chờ chủ trì cho vào tối đa (phút)
BOT_CHUNK_SECONDS = _int("BOT_CHUNK_SECONDS", 20)
BOT_MAX_CONCURRENT = _int("BOT_MAX_CONCURRENT", 2)
