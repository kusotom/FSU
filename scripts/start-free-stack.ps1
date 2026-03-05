param(
  [switch]$Build
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if ($Build) {
  Write-Host "[stack] docker compose up -d --build"
  docker compose up -d --build
} else {
  Write-Host "[stack] docker compose up -d"
  docker compose up -d
}

Write-Host "[stack] services:"
docker compose ps

Write-Host "[stack] endpoints:"
Write-Host "  Backend      http://127.0.0.1:8000/health"
Write-Host "  Prometheus   http://127.0.0.1:9090"
Write-Host "  Alertmanager http://127.0.0.1:9093"
Write-Host "  Grafana      http://127.0.0.1:3000 (admin/admin123456)"
Write-Host "  Frontend     http://127.0.0.1:8080"
