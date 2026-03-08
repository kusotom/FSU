$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$frontendDir = Join-Path $projectRoot "frontend"
$logDir = Join-Path $projectRoot "runtime-logs"
$outLog = Join-Path $logDir "frontend-daemon.out.log"
$errLog = Join-Path $logDir "frontend-daemon.err.log"
$npmCmd = "C:\Program Files\nodejs\npm.cmd"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $npmCmd)) {
  $npmCmd = "npm"
}

Set-Location $frontendDir

while ($true) {
  Add-Content -Path $outLog -Value ("[{0}] building frontend" -f (Get-Date -Format s))
  & $npmCmd run build 1>> $outLog 2>> $errLog
  Add-Content -Path $outLog -Value ("[{0}] starting frontend preview" -f (Get-Date -Format s))
  & $npmCmd run preview -- --host 0.0.0.0 --port 5173 1>> $outLog 2>> $errLog
  Add-Content -Path $errLog -Value ("[{0}] frontend preview exited, restart in 3s" -f (Get-Date -Format s))
  Start-Sleep -Seconds 3
}
