$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$downloads = "C:\Users\Administrator\tools\downloads"
$installRoot = "C:\Users\Administrator\tools\monitoring"
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
pip install prometheus-client paho-mqtt amqtt

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
Write-Host "  Prometheus:  C:\\Users\\Administrator\\tools\\monitoring\\prometheus-2.54.1.windows-amd64"
Write-Host "  Alertmanager: C:\\Users\\Administrator\\tools\\monitoring\\alertmanager-0.27.0.windows-amd64"
Write-Host "  Grafana:     C:\\Users\\Administrator\\tools\\monitoring\\grafana-v11.1.4"
