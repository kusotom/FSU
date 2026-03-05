$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\frontend"

Write-Host "Starting frontend on http://127.0.0.1:5173 ..."
npm run dev

