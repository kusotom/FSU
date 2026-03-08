$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\frontend"

$npmCmd = "C:\Program Files\nodejs\npm.cmd"
if (-not (Test-Path $npmCmd)) {
  $npmCmd = "npm"
}

Write-Host "Starting frontend on http://127.0.0.1:5173 ..."
& $npmCmd run dev
