param(
  [int]$HttpPort = 8000
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$backendDir = Join-Path $projectRoot "backend"
$pyExe = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $pyExe)) {
  $pyExe = "python"
}

Set-Location $backendDir

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

$env:FSU_GATEWAY_ENABLED = "true"
$env:FSU_UDP_BIND_HOST = "0.0.0.0"
$env:FSU_SOAP_PORT = [string]$HttpPort
$env:FSU_DSC_PORT = "9000"
$env:FSU_RDS_PORT = "7000"
$env:FSU_RAW_LOG_DIR = "logs/fsu_raw_packets"

Write-Host ("Starting FSU gateway probe on http://0.0.0.0:{0}" -f $HttpPort)
& $pyExe -m uvicorn app.modules.fsu_gateway.probe_app:app --host 0.0.0.0 --port $HttpPort --no-access-log
