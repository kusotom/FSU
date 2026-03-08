$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendBat = Join-Path $scriptDir "run-backend.bat"
$frontendBat = Join-Path $scriptDir "run-frontend.bat"

function Remove-LegacyService {
  param([string]$Name)

  sc.exe stop $Name | Out-Null
  sc.exe delete $Name | Out-Null
}

function Remove-Task {
  param([string]$Name)

  schtasks.exe /End /TN $Name | Out-Null
  schtasks.exe /Delete /TN $Name /F | Out-Null
}

function New-DaemonTask {
  param(
    [string]$Name,
    [string]$TaskCommand,
    [string]$Description
  )

  schtasks.exe /Create /TN $Name /SC ONLOGON /RL HIGHEST /TR $TaskCommand /F | Out-Null
  Write-Host "$Description installed."
}

foreach ($svc in @("FSUBackend", "FSUFrontend")) {
  Remove-LegacyService -Name $svc
}

foreach ($task in @("FSUBackend", "FSUFrontend", "FSUBackendTest")) {
  Remove-Task -Name $task
}

if (-not (Test-Path $backendBat)) {
  throw "Backend launcher not found: $backendBat"
}

if (-not (Test-Path $frontendBat)) {
  throw "Frontend launcher not found: $frontendBat"
}

$backendCommand = "cmd.exe /c `"$backendBat`""
$frontendCommand = "cmd.exe /c `"$frontendBat`""

Write-Host "Installing startup tasks..."
New-DaemonTask -Name "FSUBackend" -TaskCommand $backendCommand -Description "FSU backend startup task"
New-DaemonTask -Name "FSUFrontend" -TaskCommand $frontendCommand -Description "FSU frontend startup task"

Write-Host "Starting tasks..."
schtasks.exe /Run /TN FSUBackend | Out-Null
schtasks.exe /Run /TN FSUFrontend | Out-Null

Write-Host "Done. Startup tasks: FSUBackend, FSUFrontend"
