$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

$pyExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $pyExe)) {
  $pyExe = "python"
}

Write-Host "Starting backend on http://127.0.0.1:8000 ..."
& $pyExe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --backlog 4096 --timeout-keep-alive 30 --no-access-log
