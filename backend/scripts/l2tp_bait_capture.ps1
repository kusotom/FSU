$ErrorActionPreference = 'Stop'

$OutputDir = 'C:\Users\Administrator\Desktop\fsu-platform\backend\logs\l2tp-bait'
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$udp = New-Object System.Net.Sockets.UdpClient(1701)
$remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)

Write-Output 'L2TP bait capture started.'
Write-Output 'Listening on 0.0.0.0:1701/UDP'
Write-Output ("OutputDir={0}" -f $OutputDir)

function Save-Packet {
    param(
        [byte[]]$Bytes,
        [System.Net.IPEndPoint]$Endpoint
    )

    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ')
    $base = '{0}_{1}_{2}' -f $stamp, $Endpoint.Address, $Endpoint.Port
    $binPath = Join-Path $OutputDir ($base + '.bin')
    $jsonPath = Join-Path $OutputDir ($base + '.json')

    [System.IO.File]::WriteAllBytes($binPath, $Bytes)

    $meta = [ordered]@{
        captured_at = $stamp
        remote_ip   = $Endpoint.Address.ToString()
        remote_port = $Endpoint.Port
        size        = $Bytes.Length
        hex         = ([System.BitConverter]::ToString($Bytes) -replace '-', '')
    }
    $meta | ConvertTo-Json -Depth 4 | Set-Content -Path $jsonPath -Encoding UTF8
}

while ($true) {
    $bytes = $udp.Receive([ref]$remote)
    Save-Packet -Bytes $bytes -Endpoint $remote
    Write-Output ("Captured {0} bytes from {1}:{2}" -f $bytes.Length, $remote.Address, $remote.Port)
}
