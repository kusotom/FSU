param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [int]$Rounds = 3,
  [int]$Concurrency = 200
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\backend"

python .\scripts\load_test_2000.py --base-url $BaseUrl --devices 2000 --rounds $Rounds --concurrency $Concurrency

