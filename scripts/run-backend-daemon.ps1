$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$backendDir = Join-Path $projectRoot "backend"
$logDir = Join-Path $projectRoot "runtime-logs"
$outLog = Join-Path $logDir "backend-daemon.out.log"
$errLog = Join-Path $logDir "backend-daemon.err.log"
$pyExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $pyExe)) {
  $pyExe = "python"
}

Set-Location $backendDir

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

while ($true) {
  Add-Content -Path $outLog -Value ("[{0}] starting backend daemon" -f (Get-Date -Format s))
  & $pyExe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --backlog 4096 --timeout-keep-alive 30 --no-access-log 1>> $outLog 2>> $errLog
  Add-Content -Path $errLog -Value ("[{0}] backend exited, restart in 3s" -f (Get-Date -Format s))
  Start-Sleep -Seconds 3
}
