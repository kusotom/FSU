param(
  [Parameter(Mandatory = $true)]
  [string]$Message
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"

Write-Host "Creating Alembic revision: $Message"
alembic revision --autogenerate -m "$Message"

