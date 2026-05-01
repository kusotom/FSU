$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$toolsDir = Join-Path $env:USERPROFILE "Tools"
$downloads = Join-Path $toolsDir "downloads"
$installRoot = Join-Path $toolsDir "monitoring"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null

$assets = @(
  @{
    name = "prometheus"
    zip = "prometheus-2.54.1.windows-amd64.zip"
    url = "https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.windows-amd64.zip"
  },
  @{
    name = "alertmanager"
    zip = "alertmanager-0.27.0.windows-amd64.zip"
    url = "https://github.com/prometheus/alertmanager/releases/download/v0.27.0/alertmanager-0.27.0.windows-amd64.zip"
  },
  @{
    name = "grafana"
    zip = "grafana-11.1.4.windows-amd64.zip"
    url = "https://dl.grafana.com/oss/release/grafana-11.1.4.windows-amd64.zip"
  }
)

Write-Host "[install] python dependencies..."
Set-Location (Join-Path $root "backend")
$pythonExe = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
  $pythonExe = "python"
}
& $pythonExe -m pip install prometheus-client paho-mqtt amqtt

foreach ($asset in $assets) {
  $zipPath = Join-Path $downloads $asset.zip
  if (-not (Test-Path $zipPath)) {
    Write-Host ("[install] downloading {0}..." -f $asset.name)
    Start-BitsTransfer -Source $asset.url -Destination $zipPath
  } else {
    Write-Host ("[install] found {0}" -f $zipPath)
  }
  Write-Host ("[install] extracting {0}..." -f $asset.zip)
  Expand-Archive -Path $zipPath -DestinationPath $installRoot -Force
}

Write-Host "[install] done"
Write-Host ("  Prometheus:   {0}" -f (Join-Path $installRoot "prometheus-2.54.1.windows-amd64"))
Write-Host ("  Alertmanager: {0}" -f (Join-Path $installRoot "alertmanager-0.27.0.windows-amd64"))
Write-Host ("  Grafana:      {0}" -f (Join-Path $installRoot "grafana-v11.1.4"))
