$ErrorActionPreference = "Stop"

Set-Location "$PSScriptRoot\..\backend"

Write-Host "Sending mock telemetry every 5 seconds. Ctrl + C to stop."
while ($true) {
  python .\scripts\mock_ingest.py
  Start-Sleep -Seconds 5
}

