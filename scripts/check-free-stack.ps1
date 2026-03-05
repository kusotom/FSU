$ErrorActionPreference = "Continue"

function Check-Url {
  param(
    [string]$Name,
    [string]$Url,
    [int]$TimeoutSec = 4
  )

  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
    Write-Host ("[ok]   {0,-12} {1} ({2})" -f $Name, $Url, $resp.StatusCode)
  } catch {
    Write-Host ("[fail] {0,-12} {1} ({2})" -f $Name, $Url, $_.Exception.Message)
  }
}

Check-Url -Name "backend" -Url "http://127.0.0.1:8000/health"
Check-Url -Name "metrics" -Url "http://127.0.0.1:8000/metrics"
Check-Url -Name "prometheus" -Url "http://127.0.0.1:9090/-/ready"
Check-Url -Name "alertmgr" -Url "http://127.0.0.1:9093/-/ready"
Check-Url -Name "grafana" -Url "http://127.0.0.1:3000/api/health"
Check-Url -Name "frontend" -Url "http://127.0.0.1:8080"
