#!/usr/bin/env bash
# Chạy Thư Ký AI trên máy của bạn (macOS / Linux), kèm ghi trực tiếp và chép lời miễn phí.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt -r requirements-asr.txt -r requirements-bot.txt
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Chưa đặt ANTHROPIC_API_KEY: hãy nhập khóa Claude API trong mục Cài đặt của ứng dụng."
fi
export SECURE_COOKIES=0 FREE_DAILY_LIMIT=${FREE_DAILY_LIMIT:-0} LOCAL_BOT=${LOCAL_BOT:-1}
echo "Mở http://localhost:8000/app trong Chrome hoặc Edge. Lần ghi đầu tiên sẽ tải model chép lời (vài trăm MB)."
( sleep 3; (command -v open >/dev/null && open http://localhost:8000/app) || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000/app) || true ) &
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
