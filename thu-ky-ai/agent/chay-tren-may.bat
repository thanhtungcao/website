@echo off
REM Chạy Thư Ký AI trên Windows, kèm ghi trực tiếp và chép lời miễn phí.
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt -r requirements-asr.txt
if "%ANTHROPIC_API_KEY%"=="" echo Chưa đặt ANTHROPIC_API_KEY: hãy nhập khóa Claude API trong mục Cài đặt của ứng dụng.
set SECURE_COOKIES=0
if "%FREE_DAILY_LIMIT%"=="" set FREE_DAILY_LIMIT=0
echo Mở http://localhost:8000/app trong Chrome hoặc Edge. Lần ghi đầu tiên sẽ tải model chép lời (vài trăm MB).
start "" http://localhost:8000/app
uvicorn app.main:app --host 127.0.0.1 --port 8000
