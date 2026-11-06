@echo off
REM Thu Ky AI - chay tren Windows: ghi cuoc hop truc tiep, chep loi va tao bien ban.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Thu Ky AI

REM ---- 1. Tim Python 3.9 tro len ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul || goto :nopython

REM ---- 2. Tao moi truong va cai thu vien (chi lau o lan dau) ----
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Dang tao moi truong Python...
  %PY% -m venv .venv || goto :fail
)
set "VPY=.venv\Scripts\python.exe"
echo [2/3] Dang kiem tra thu vien. Lan dau mat vai phut, vui long cho...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-asr.txt || goto :fail

REM ---- 3. Doc cau hinh tu file .env (neu co) ----
if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do if not "%%b"=="" set "%%a=%%b"
)
if not defined SECURE_COOKIES set "SECURE_COOKIES=0"
if not defined FREE_DAILY_LIMIT set "FREE_DAILY_LIMIT=0"
if not defined ANTHROPIC_API_KEY (
  echo.
  echo  Chua co khoa Claude API. Mo file .env bang Notepad de dien,
  echo  hoac nhap khoa trong muc Cai dat cua ung dung.
  echo.
)

echo [3/3] Dang khoi dong Thu Ky AI tai http://localhost:8000/app
echo       Giu cua so nay mo trong khi dung. Dong cua so de tat ung dung.
echo       Lan ghi am dau tien se tai model chep loi (khoang 500 MB).
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8000/app"
"%VPY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo.
  echo Ung dung da dung voi loi. Neu bao "address already in use", hay dong cua so Thu Ky AI cu roi chay lai.
  pause
)
exit /b

:nopython
echo.
echo Chua tim thay Python 3.9 tro len tren may.
echo  1. Tai Python 3.12 tai https://www.python.org/downloads/windows/
echo  2. Khi cai, nho TICH O "Add python.exe to PATH"
echo  3. Chay lai file nay.
start "" https://www.python.org/downloads/windows/
pause
exit /b 1

:fail
echo.
echo Cai dat that bai. Kiem tra ket noi Internet roi chay lai.
echo Neu van loi, cai "Microsoft Visual C++ Redistributable" tai https://aka.ms/vs/17/release/vc_redist.x64.exe
pause
exit /b 1
