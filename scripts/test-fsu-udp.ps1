param(
  [string]$HostName = "127.0.0.1",
  [int]$DscPort = 9000,
  [int]$RdsPort = 7000,
  [int]$TimeoutMs = 2000
)

$ErrorActionPreference = "Stop"

function Send-FsuUdpProbe {
  param(
    [string]$Name,
    [int]$Port,
    [string]$Message
  )

  $client = [System.Net.Sockets.UdpClient]::new()
  try {
    $client.Client.ReceiveTimeout = $TimeoutMs
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Message)
    [void]$client.Send($bytes, $bytes.Length, $HostName, $Port)
    Write-Host ("sent {0} bytes to {1}:{2} ({3})" -f $bytes.Length, $HostName, $Port, $Name)

    $remote = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
    $ack = $client.Receive([ref]$remote)
    $ackHex = [System.BitConverter]::ToString($ack).Replace("-", "").ToLowerInvariant()
    Write-Host ("ack from {0}:{1} length={2} hex={3}" -f $remote.Address, $remote.Port, $ack.Length, $ackHex)
  } catch {
    Write-Host ("no ack from {0}:{1} within {2}ms: {3}" -f $HostName, $Port, $TimeoutMs, $_.Exception.Message)
  } finally {
    $client.Close()
  }
}

Send-FsuUdpProbe -Name "UDP_DSC" -Port $DscPort -Message "hello fsu udp 9000"
Send-FsuUdpProbe -Name "UDP_RDS" -Port $RdsPort -Message "hello fsu udp 7000"
