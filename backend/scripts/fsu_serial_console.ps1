param(
    [string]$Port = "COM1",
    [int]$BaudRate = 115200,
    [int]$DataBits = 8,
    [ValidateSet("None", "Odd", "Even", "Mark", "Space")]
    [string]$Parity = "None",
    [ValidateSet("One", "OnePointFive", "Two")]
    [string]$StopBits = "One",
    [int]$ReadTimeoutMs = 500,
    [int]$StartupDelayMs = 1200,
    [int]$LoginPauseMs = 700,
    [int]$CaptureSeconds = 15,
    [string]$Username,
    [string]$Password,
    [switch]$AutoLogin,
    [switch]$NoLogFile,
    [string]$LogDir = "C:\Users\Administrator\Desktop\fsu-platform\backend\logs\serial-console"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-SerialLine {
    param(
        [System.IO.Ports.SerialPort]$SerialPort,
        [string]$Text
    )
    $SerialPort.Write($Text + "`r`n")
}

function Read-SerialAvailable {
    param(
        [System.IO.Ports.SerialPort]$SerialPort
    )
    try {
        return $SerialPort.ReadExisting()
    } catch {
        return ""
    }
}

[System.IO.Ports.Parity]$parityValue = [System.Enum]::Parse([System.IO.Ports.Parity], $Parity)
[System.IO.Ports.StopBits]$stopBitsValue = [System.Enum]::Parse([System.IO.Ports.StopBits], $StopBits)

$serialPort = [System.IO.Ports.SerialPort]::new($Port, $BaudRate, $parityValue, $DataBits, $stopBitsValue)
$serialPort.ReadTimeout = $ReadTimeoutMs
$serialPort.WriteTimeout = $ReadTimeoutMs
$serialPort.Handshake = [System.IO.Ports.Handshake]::None
$serialPort.DtrEnable = $true
$serialPort.RtsEnable = $true
$serialPort.NewLine = "`r`n"

$logWriter = $null
if (-not $NoLogFile) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $timestamp = Get-Date -Format "yyyyMMddTHHmmss"
    $logPath = Join-Path $LogDir "$timestamp-$Port.log"
    $logWriter = [System.IO.StreamWriter]::new($logPath, $false, [System.Text.Encoding]::UTF8)
    Write-Host "LogFile=$logPath"
}

try {
    $serialPort.Open()
    Write-Host "Opened $Port @ $BaudRate $DataBits$Parity$StopBits"
    Start-Sleep -Milliseconds $StartupDelayMs

    Write-SerialLine -SerialPort $serialPort -Text ""
    Start-Sleep -Milliseconds 300

    if ($AutoLogin) {
        if (-not $Username) {
            throw "AutoLogin requires -Username."
        }
        if ($null -eq $Password) {
            throw "AutoLogin requires -Password."
        }

        Write-Host "Sending username..."
        Write-SerialLine -SerialPort $serialPort -Text $Username
        Start-Sleep -Milliseconds $LoginPauseMs

        Write-Host "Sending password..."
        Write-SerialLine -SerialPort $serialPort -Text $Password
        Start-Sleep -Milliseconds $LoginPauseMs
    }

    $deadline = (Get-Date).AddSeconds($CaptureSeconds)
    while ((Get-Date) -lt $deadline) {
        $content = Read-SerialAvailable -SerialPort $serialPort
        if ($content) {
            Write-Host $content -NoNewline
            if ($logWriter) {
                $logWriter.Write($content)
                $logWriter.Flush()
            }
        }
        Start-Sleep -Milliseconds 150
    }
} finally {
    if ($logWriter) {
        $logWriter.Dispose()
    }
    if ($serialPort.IsOpen) {
        $serialPort.Close()
    }
}
