param(
  [string]$PlatformIp = "192.168.100.123",
  [string]$UdpPorts = "9000,7000",
  [string]$BackendIngestUrl = "",
  [string]$SiteCode = "51051243812345",
  [string]$SiteName = "eStoneII Site",
  [string]$FsuCode = "51051243812345",
  [string]$FsuName = "eStoneII FSU",
  [string]$OutputDir = "backend\logs\estoneii-ds-gateway",
  [int]$DurationSeconds = 0,
  [double]$StatusIntervalSeconds = 5,
  [int]$UnknownCaptureMinSize = 31,
  [switch]$CapturePackets,
  [switch]$NoCaptureUnknownPackets,
  [switch]$ForwardShortAcks
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$backendDir = Join-Path $projectRoot "backend"
$pyExe = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $pyExe)) {
  $pyExe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
}
if (-not (Test-Path $pyExe)) {
  $pyExe = "python"
}

Set-Location $projectRoot

$gatewayArgs = @(
  "backend\scripts\estoneii_ds_gateway.py",
  "--udp-ports", $UdpPorts,
  "--duration-seconds", "$DurationSeconds",
  "--status-interval-seconds", "$StatusIntervalSeconds",
  "--unknown-capture-min-size", "$UnknownCaptureMinSize",
  "--output-dir", $OutputDir,
  "--ds-url", "udp://${PlatformIp}:9000",
  "--site-code", $SiteCode,
  "--site-name", $SiteName,
  "--fsu-code", $FsuCode,
  "--fsu-name", $FsuName
)

if ($BackendIngestUrl) {
  $gatewayArgs += @("--backend-ingest-url", $BackendIngestUrl)
}
if ($CapturePackets) {
  $gatewayArgs += "--capture-packets"
}
if ($NoCaptureUnknownPackets) {
  $gatewayArgs += "--no-capture-unknown-packets"
}
if ($ForwardShortAcks) {
  $gatewayArgs += "--forward-short-acks"
}

Write-Host "Starting eStoneII DS gateway on UDP $UdpPorts, DS URL udp://${PlatformIp}:9000 ..."
& $pyExe @gatewayArgs
