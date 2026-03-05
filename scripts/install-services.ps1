$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendBat = Join-Path $scriptDir "run-backend.bat"
$frontendBat = Join-Path $scriptDir "run-frontend.bat"

foreach ($svc in @("FSUBackend", "FSUFrontend")) {
  sc.exe stop $svc | Out-Null
  sc.exe delete $svc | Out-Null
}

Write-Host "Installing FSUBackend service..."
sc.exe create FSUBackend binPath= "cmd /c `"$backendBat`"" start= auto | Out-Null
sc.exe description FSUBackend "FSU backend API service (FastAPI/Uvicorn)" | Out-Null

Write-Host "Installing FSUFrontend service..."
sc.exe create FSUFrontend binPath= "cmd /c `"$frontendBat`"" start= auto | Out-Null
sc.exe description FSUFrontend "FSU frontend preview service (Vite preview)" | Out-Null

Write-Host "Starting services..."
sc.exe start FSUBackend | Out-Null
sc.exe start FSUFrontend | Out-Null

Write-Host "Done. Services: FSUBackend, FSUFrontend"
