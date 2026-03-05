$ErrorActionPreference = "Continue"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $root "runtime-logs\local-stack"
$pidFile = Join-Path $logDir "pids.json"

if (-not (Test-Path $pidFile)) {
  Write-Host "[local-stack] no pid file found, nothing to stop"
  exit 0
}

$items = Get-Content -Path $pidFile -Raw | ConvertFrom-Json
if ($items -isnot [System.Array]) {
  $items = @($items)
}

foreach ($item in $items) {
  $processId = [int]$item.pid
  if ($processId -le 0) {
    continue
  }
  try {
    $proc = Get-Process -Id $processId -ErrorAction Stop
    Stop-Process -Id $processId -Force -ErrorAction Stop
    Write-Host ("[stopped] {0,-12} pid={1}" -f $item.name, $processId)
  } catch {
    Write-Host ("[skip]   {0,-12} pid={1} already exited" -f $item.name, $processId)
  }
}

Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "[local-stack] stopped"
