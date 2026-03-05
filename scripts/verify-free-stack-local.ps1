$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "backend"

Write-Host "[verify] publishing mqtt test traffic..."
Push-Location $backendDir
python .\scripts\mock_mqtt_ingest.py --host 127.0.0.1 --port 1883 --count 12 --interval 0.2
Pop-Location

Start-Sleep -Seconds 3

Write-Host "[verify] reading bridge metrics..."
$bridgeMetrics = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:9108/" -TimeoutSec 5
$accepted = ($bridgeMetrics.Content -split "`n" | Where-Object { $_ -match '^fsu_mqtt_bridge_messages_total\{result="accepted"\}' } | ForEach-Object { ($_ -split ' ')[-1] } | Select-Object -First 1)
$forwarded = ($bridgeMetrics.Content -split "`n" | Where-Object { $_ -match '^fsu_mqtt_bridge_messages_total\{result="forwarded"\}' } | ForEach-Object { ($_ -split ' ')[-1] } | Select-Object -First 1)
Write-Host ("[verify] bridge accepted={0} forwarded={1}" -f $accepted, $forwarded)

Write-Host "[verify] querying backend latest telemetry..."
$loginBody = '{"username":"admin","password":"admin123"}'
$login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/login" -ContentType "application/json" -Body $loginBody -TimeoutSec 8
$headers = @{ Authorization = "Bearer $($login.access_token)" }
$latest = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/telemetry/latest?site_code=S001" -Headers $headers -TimeoutSec 8
$latestCount = ($latest | Measure-Object).Count
$deviceCount = ($latest | Where-Object { $_.device_code -eq "FSU-001" } | Measure-Object).Count
Write-Host ("[verify] latest_count={0} latest_has_FSU001={1}" -f $latestCount, $deviceCount)

Write-Host "[verify] querying prometheus targets..."
function Wait-PrometheusUp {
  param(
    [string]$Job,
    [int]$TimeoutSec = 45
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $uri = "http://127.0.0.1:9090/api/v1/query?query=up{job=`"$Job`"}"
      $q = Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 5
      $result = $q.data.result
      if ($result -and $result.Count -gt 0) {
        $value = [double]($result[0].value[1])
        if ($value -ge 1) {
          return $true
        }
      }
    } catch {}
    Start-Sleep -Seconds 2
  }
  return $false
}

$backendPromUp = Wait-PrometheusUp -Job "backend" -TimeoutSec 45
$bridgePromUp = Wait-PrometheusUp -Job "mqtt_bridge" -TimeoutSec 45
Write-Host ("[verify] prometheus backend up={0}" -f $backendPromUp)
Write-Host ("[verify] prometheus bridge up={0}" -f $bridgePromUp)

if (($deviceCount -lt 1) -or (-not $backendPromUp) -or (-not $bridgePromUp)) {
  throw "verification failed: telemetry or scrape targets are not healthy"
}

Write-Host "[verify] PASS"
