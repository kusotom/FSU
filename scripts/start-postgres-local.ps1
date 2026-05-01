param(
  [int]$Port = 5432
)

$ErrorActionPreference = "Stop"

$pgDir = Join-Path $env:USERPROFILE "Tools\PostgreSQL\16"
$dataDir = Join-Path $pgDir "data"
$logFile = Join-Path $pgDir "postgresql.log"
$pgCtl = Join-Path $pgDir "bin\pg_ctl.exe"
$pgIsReady = Join-Path $pgDir "bin\pg_isready.exe"

foreach ($requiredPath in @($pgCtl, $pgIsReady, (Join-Path $dataDir "PG_VERSION"))) {
  if (-not (Test-Path $requiredPath)) {
    throw "required PostgreSQL path missing: $requiredPath"
  }
}

& $pgIsReady -h 127.0.0.1 -p $Port -d fsu -U fsu | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Host ("[ok]   postgres   127.0.0.1:{0}" -f $Port)
  exit 0
}

Write-Host ("[local-stack] Starting portable PostgreSQL on 127.0.0.1:{0}..." -f $Port)
& $pgCtl -D $dataDir -l $logFile -o "-p $Port -c listen_addresses=localhost" start -w
