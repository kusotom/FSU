$ErrorActionPreference = "Stop"

$TaskName = "FSU Readonly Observation"

Write-Host "Deleting scheduled task: $TaskName"

try {
    schtasks.exe /Delete /TN $TaskName /F
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks exited with code $LASTEXITCODE"
    }
    Write-Host "Deleted task: $TaskName"
} catch {
    Write-Host "Failed to delete scheduled task. It may not exist, or PowerShell may lack permission."
    throw
}
