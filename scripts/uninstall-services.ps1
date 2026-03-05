$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping services..."
sc.exe stop FSUFrontend | Out-Null
sc.exe stop FSUBackend | Out-Null

Write-Host "Deleting services..."
sc.exe delete FSUFrontend | Out-Null
sc.exe delete FSUBackend | Out-Null

Write-Host "Done."

