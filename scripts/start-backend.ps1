$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

Write-Host "Starting backend on http://127.0.0.1:8000 ..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --backlog 4096 --timeout-keep-alive 30 --no-access-log
