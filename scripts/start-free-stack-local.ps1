param(
  [switch]$WithFrontend
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$logDir = Join-Path $root "runtime-logs\local-stack"
$dataDir = Join-Path $root "runtime-data\local-stack"
$pidFile = Join-Path $logDir "pids.json"

$promDir = "C:\Users\Administrator\tools\monitoring\prometheus-2.54.1.windows-amd64"
$alertDir = "C:\Users\Administrator\tools\monitoring\alertmanager-0.27.0.windows-amd64"
$grafanaDir = "C:\Users\Administrator\tools\monitoring\grafana-v11.1.4"

$amqttConfig = Join-Path $root "deploy\local\amqtt\amqtt.yml"
$promConfig = Join-Path $root "deploy\local\prometheus\prometheus.yml"
$alertConfig = Join-Path $root "deploy\local\alertmanager\alertmanager.yml"
$grafanaProvisioning = Join-Path $root "deploy\local\grafana\provisioning"
$grafanaHomeDashboard = Join-Path $root "deploy\local\grafana\dashboards\fsu-realtime-overview-local.json"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "prometheus") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "alertmanager") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "grafana\data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "grafana\logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "grafana\plugins") | Out-Null

if (Test-Path $pidFile) {
  Write-Host "[local-stack] Existing pid file found, stopping previous stack first..."
  & (Join-Path $PSScriptRoot "stop-free-stack-local.ps1")
}

foreach ($requiredPath in @(
  (Join-Path $promDir "prometheus.exe"),
  (Join-Path $alertDir "alertmanager.exe"),
  (Join-Path $grafanaDir "bin\grafana-server.exe"),
  $amqttConfig,
  $promConfig,
  $alertConfig,
  $grafanaHomeDashboard
)) {
  if (-not (Test-Path $requiredPath)) {
    throw "required path missing: $requiredPath"
  }
}

function Wait-HttpReady {
  param(
    [string]$Name,
    [string]$Url,
    [int]$TimeoutSec = 90
  )
  $start = Get-Date
  while ((Get-Date) -lt $start.AddSeconds($TimeoutSec)) {
    try {
      $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
        Write-Host ("[ok]   {0,-12} {1}" -f $Name, $Url)
        return
      }
    } catch {}
    Start-Sleep -Milliseconds 700
  }
  throw "timeout waiting for $Name ($Url)"
}

function Wait-PortReady {
  param(
    [string]$Name,
    [int]$Port,
    [int]$TimeoutSec = 45
  )
  $start = Get-Date
  while ((Get-Date) -lt $start.AddSeconds($TimeoutSec)) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
      $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
      if ($iar.AsyncWaitHandle.WaitOne(400)) {
        $client.EndConnect($iar) | Out-Null
        Write-Host ("[ok]   {0,-12} 127.0.0.1:{1}" -f $Name, $Port)
        return
      }
    } catch {}
    finally {
      $client.Close()
    }
    Start-Sleep -Milliseconds 500
  }
  throw "timeout waiting for $Name on port $Port"
}

function Start-LoggedProcess {
  param(
    [string]$Name,
    [string]$Command
  )
  $outLog = Join-Path $logDir "$Name.out.log"
  $errLog = Join-Path $logDir "$Name.err.log"
  $proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru
  return [PSCustomObject]@{
    name = $Name
    pid = $proc.Id
    out_log = $outLog
    err_log = $errLog
  }
}

Write-Host "[local-stack] Ensuring PostgreSQL service is running..."
Start-Service postgresql-x64-16 -ErrorAction SilentlyContinue
Get-Service postgresql-x64-16 | Select-Object Name, Status | Format-Table | Out-Host

Write-Host "[local-stack] Running backend migrations..."
Push-Location $backendDir
$env:DATABASE_URL = "postgresql+psycopg://fsu:fsu123456@127.0.0.1:5432/fsu"
python -m alembic upgrade head
Pop-Location

$procs = @()

Write-Host "[local-stack] Starting backend..."
$backendCmd = @"
Set-Location '$backendDir'
`$env:DATABASE_URL='postgresql+psycopg://fsu:fsu123456@127.0.0.1:5432/fsu'
`$env:AUTO_CREATE_SCHEMA='false'
`$env:INGEST_MODE='queue'
`$env:INGEST_QUEUE_WORKERS='2'
`$env:INGEST_QUEUE_BATCH_SIZE='100'
`$env:INGEST_QUEUE_BATCH_WAIT_MS='120'
`$env:SYSTEM_RULE_EVAL_ENABLED='false'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"@
$procs += Start-LoggedProcess -Name "backend" -Command $backendCmd
Wait-HttpReady -Name "backend" -Url "http://127.0.0.1:8000/health" -TimeoutSec 120

Write-Host "[local-stack] Starting amqtt broker..."
$amqttCmd = @"
Set-Location '$backendDir'
amqtt -c '$amqttConfig'
"@
$procs += Start-LoggedProcess -Name "amqtt" -Command $amqttCmd
Wait-PortReady -Name "mqtt" -Port 1883 -TimeoutSec 60

Write-Host "[local-stack] Starting mqtt bridge..."
$bridgeCmd = @"
Set-Location '$backendDir'
`$env:MQTT_BROKER_HOST='127.0.0.1'
`$env:MQTT_BROKER_PORT='1883'
`$env:MQTT_TOPIC='fsu/telemetry/#'
`$env:MQTT_QOS='1'
`$env:BACKEND_INGEST_URL='http://127.0.0.1:8000/api/v1/ingest/telemetry'
`$env:BACKEND_TIMEOUT_SECONDS='5'
`$env:BACKEND_RETRY_TIMES='2'
`$env:BRIDGE_QUEUE_MAXSIZE='50000'
`$env:BRIDGE_WORKER_COUNT='4'
`$env:BRIDGE_METRICS_PORT='9108'
python .\scripts\mqtt_ingest_bridge.py
"@
$procs += Start-LoggedProcess -Name "mqtt-bridge" -Command $bridgeCmd
Wait-HttpReady -Name "bridge-mt" -Url "http://127.0.0.1:9108/" -TimeoutSec 60

Write-Host "[local-stack] Starting alertmanager..."
$alertCmd = @"
Set-Location '$alertDir'
.\alertmanager.exe --config.file='$alertConfig' --storage.path='$dataDir\alertmanager' --web.listen-address='127.0.0.1:9093'
"@
$procs += Start-LoggedProcess -Name "alertmanager" -Command $alertCmd
Wait-HttpReady -Name "alertmgr" -Url "http://127.0.0.1:9093/-/ready" -TimeoutSec 60

Write-Host "[local-stack] Starting prometheus..."
$promCmd = @"
Set-Location '$promDir'
.\prometheus.exe --config.file='$promConfig' --storage.tsdb.path='$dataDir\prometheus' --web.listen-address='127.0.0.1:9090' --web.enable-lifecycle
"@
$procs += Start-LoggedProcess -Name "prometheus" -Command $promCmd
Wait-HttpReady -Name "prometheus" -Url "http://127.0.0.1:9090/-/ready" -TimeoutSec 60

Write-Host "[local-stack] Starting grafana..."
$grafanaCmd = @"
Set-Location '$grafanaDir'
`$env:GF_SECURITY_ADMIN_USER='admin'
`$env:GF_SECURITY_ADMIN_PASSWORD='admin123456'
`$env:GF_USERS_ALLOW_SIGN_UP='false'
`$env:GF_SERVER_HTTP_PORT='3000'
`$env:GF_PATHS_DATA='$dataDir\grafana\data'
`$env:GF_PATHS_LOGS='$dataDir\grafana\logs'
`$env:GF_PATHS_PLUGINS='$dataDir\grafana\plugins'
`$env:GF_PATHS_PROVISIONING='$grafanaProvisioning'
`$env:GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH='$grafanaHomeDashboard'
.\bin\grafana-server.exe --homepath '$grafanaDir'
"@
$procs += Start-LoggedProcess -Name "grafana" -Command $grafanaCmd
Wait-HttpReady -Name "grafana" -Url "http://127.0.0.1:3000/api/health" -TimeoutSec 120

if ($WithFrontend) {
  Write-Host "[local-stack] Starting frontend (vite dev)..."
  $frontCmd = @"
Set-Location '$frontendDir'
npm run dev -- --host 127.0.0.1 --port 5173
"@
  $procs += Start-LoggedProcess -Name "frontend" -Command $frontCmd
  Wait-HttpReady -Name "frontend" -Url "http://127.0.0.1:5173/" -TimeoutSec 120
}

$procs | ConvertTo-Json -Depth 4 | Set-Content -Path $pidFile -Encoding UTF8

Write-Host ""
Write-Host "[local-stack] started successfully"
Write-Host ("[local-stack] pid file: {0}" -f $pidFile)
Write-Host "  Backend      http://127.0.0.1:8000/health"
Write-Host "  MQTT broker  127.0.0.1:1883"
Write-Host "  Bridge mt    http://127.0.0.1:9108/"
Write-Host "  Prometheus   http://127.0.0.1:9090"
Write-Host "  Alertmanager http://127.0.0.1:9093"
Write-Host "  Grafana      http://127.0.0.1:3000 (admin/admin123456)"
if ($WithFrontend) {
  Write-Host "  Frontend     http://127.0.0.1:5173"
}
