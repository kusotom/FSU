param(
    [string]$HostName = '0.0.0.0',
    [int]$Port = 10378,
    [string]$OutputDir = 'C:\Users\Administrator\Desktop\fsu-platform\backend\logs\sc-bait\tcp'
)

$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
$listener.Start()

Write-Output "SC bait TCP capture started."
Write-Output "Listening on 0.0.0.0:$Port"
Write-Output "OutputDir=$OutputDir"

while ($true) {
    $client = $listener.AcceptTcpClient()
    try {
        $stream = $client.GetStream()
        $stream.ReadTimeout = 3000
        $buffer = New-Object byte[] 8192
        $memory = New-Object System.IO.MemoryStream
        while ($true) {
            try {
                $read = $stream.Read($buffer, 0, $buffer.Length)
            } catch {
                break
            }
            if ($read -le 0) {
                break
            }
            $memory.Write($buffer, 0, $read)
            if ($read -lt $buffer.Length) {
                break
            }
        }

        $payload = $memory.ToArray()
        $now = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ')
        $remote = $client.Client.RemoteEndPoint.ToString().Replace(':', '_')
        $binPath = Join-Path $OutputDir "$now`_$remote.bin"
        $jsonPath = Join-Path $OutputDir "$now`_$remote.json"
        [System.IO.File]::WriteAllBytes($binPath, $payload)

        $preview = ''
        if ($payload.Length -gt 0) {
            try {
                $preview = [System.Text.Encoding]::UTF8.GetString($payload)
            } catch {
                $preview = ''
            }
            if (-not $preview) {
                try {
                    $preview = [System.Text.Encoding]::GetEncoding('GBK').GetString($payload)
                } catch {
                    $preview = ''
                }
            }
        }

        $meta = [ordered]@{
            received_at_utc = [DateTime]::UtcNow.ToString('o')
            remote_endpoint = $client.Client.RemoteEndPoint.ToString()
            local_endpoint = $client.Client.LocalEndPoint.ToString()
            payload_size = $payload.Length
            payload_file = [System.IO.Path]::GetFileName($binPath)
            payload_preview = $preview.Substring(0, [Math]::Min($preview.Length, 4000))
        }
        $meta | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $jsonPath
        Write-Output ("Captured {0} bytes from {1}" -f $payload.Length, $client.Client.RemoteEndPoint.ToString())
    } finally {
        $client.Close()
    }
}
