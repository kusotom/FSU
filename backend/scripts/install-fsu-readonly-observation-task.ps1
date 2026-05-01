$ErrorActionPreference = "Stop"

$TaskName = "FSU Readonly Observation"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
$ProjectRoot = Split-Path -Parent $BackendDir
$Runner = Join-Path $ScriptDir "run-fsu-readonly-observation.cmd"
$TaskRunner = Join-Path $ScriptDir "run-fsu-readonly-observation-task.ps1"

if (-not (Test-Path -LiteralPath $Runner)) {
    throw "Runner not found: $Runner"
}
if (-not (Test-Path -LiteralPath $TaskRunner)) {
    throw "Task runner not found: $TaskRunner"
}

Write-Host "Installing scheduled task: $TaskName"
Write-Host "Project root: $ProjectRoot"
Write-Host "Runner: $Runner"
Write-Host "Task runner: $TaskRunner"
Write-Host "Schedule: every 30 minutes"
Write-Host "Safety: readonly observation only; no ACK sender is invoked."

$exists = $false
try {
    schtasks.exe /Query /TN $TaskName | Out-Null
    $exists = $true
} catch {
    $exists = $false
}

if ($exists) {
    Write-Host "Existing task found; it will be updated with /F."
}

$encodedCommandText = "Set-Location -LiteralPath '$ProjectRoot'; & '$Runner'"
$encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($encodedCommandText))
$taskRun = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $encodedCommand
$createArgs = @(
    "/Create",
    "/TN", $TaskName,
    "/TR", $taskRun,
    "/SC", "MINUTE",
    "/MO", "30",
    "/F"
)

try {
    schtasks.exe @createArgs
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "schtasks create failed; falling back to ScheduledTasks module."
    Write-Host $_
    try {
        $actionArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $TaskRunner + '"'
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $ProjectRoot
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    } catch {
        Write-Host "Failed to create scheduled task."
        Write-Host "Run this script in an Administrator PowerShell, or create the task manually in Task Scheduler."
        throw
    }
}

Write-Host ""
Write-Host "Created or updated task: $TaskName"
Write-Host ""
Write-Host "Manual run:"
Write-Host ('schtasks /Run /TN "' + $TaskName + '"')
Write-Host ""
Write-Host "Query:"
Write-Host ('schtasks /Query /TN "' + $TaskName + '" /V /FO LIST')
Write-Host ""
Write-Host "Delete:"
Write-Host ('schtasks /Delete /TN "' + $TaskName + '" /F')
