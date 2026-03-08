$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping legacy services..."
sc.exe stop FSUFrontend | Out-Null
sc.exe stop FSUBackend | Out-Null

Write-Host "Deleting legacy services..."
sc.exe delete FSUFrontend | Out-Null
sc.exe delete FSUBackend | Out-Null

Write-Host "Stopping scheduled tasks..."
schtasks.exe /End /TN FSUFrontend | Out-Null
schtasks.exe /End /TN FSUBackend | Out-Null

Write-Host "Deleting scheduled tasks..."
schtasks.exe /Delete /TN FSUFrontend /F | Out-Null
schtasks.exe /Delete /TN FSUBackend /F | Out-Null
schtasks.exe /Delete /TN FSUBackendTest /F | Out-Null

Write-Host "Done."
