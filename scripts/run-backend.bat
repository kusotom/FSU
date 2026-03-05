@echo off
setlocal
cd /d %~dp0\..\backend
if not exist .env copy .env.example .env
set "PY_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if exist "%PY_EXE%" (
  "%PY_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --backlog 4096 --timeout-keep-alive 30 --no-access-log
) else (
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --backlog 4096 --timeout-keep-alive 30 --no-access-log
)
