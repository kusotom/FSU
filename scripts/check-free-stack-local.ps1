param(
  [switch]$WithFrontend
)

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

function Check-Port {
  param(
    [string]$Name,
    [int]$Port
  )
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne(500)) {
      $client.EndConnect($iar) | Out-Null
      Write-Host ("[ok]   {0,-12} 127.0.0.1:{1}" -f $Name, $Port)
      return
    }
    Write-Host ("[fail] {0,-12} 127.0.0.1:{1} (connect timeout)" -f $Name, $Port)
  } catch {
    Write-Host ("[fail] {0,-12} 127.0.0.1:{1} ({2})" -f $Name, $Port, $_.Exception.Message)
  } finally {
    $client.Close()
  }
}

Check-Url -Name "backend" -Url "http://127.0.0.1:8000/health"
Check-Url -Name "metrics" -Url "http://127.0.0.1:8000/metrics"
Check-Port -Name "mqtt" -Port 1883
Check-Url -Name "bridge-mt" -Url "http://127.0.0.1:9108/"
Check-Url -Name "prometheus" -Url "http://127.0.0.1:9090/-/ready"
Check-Url -Name "alertmgr" -Url "http://127.0.0.1:9093/-/ready"
Check-Url -Name "grafana" -Url "http://127.0.0.1:3000/api/health"
if ($WithFrontend) {
  Check-Url -Name "frontend" -Url "http://127.0.0.1:5173/"
}
