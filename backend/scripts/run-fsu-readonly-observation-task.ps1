$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
$ProjectRoot = Split-Path -Parent $BackendDir
$LogFile = Join-Path $ProjectRoot "backend\logs\fsu_raw_packets\readonly-observation-scheduler.log"
$NodeScript = Join-Path $ProjectRoot "backend\scripts\run-fsu-readonly-observation.js"

Set-Location -LiteralPath $ProjectRoot

$start = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value "[$start] Starting FSU readonly observation"

try {
    & node $NodeScript *>> $LogFile
    $code = $LASTEXITCODE
} catch {
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value $_.Exception.Message
    $code = 1
}

$end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value "[$end] Finished FSU readonly observation with exit code $code"
exit $code
