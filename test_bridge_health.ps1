$ErrorActionPreference = "SilentlyContinue"
$client = $null
try {
    $client = New-Object Net.Sockets.TcpClient
    $pending = $client.BeginConnect("127.0.0.1", 8765, $null, $null)
    if (-not $pending.AsyncWaitHandle.WaitOne(2000, $false)) { exit 1 }
    $client.EndConnect($pending)
    $stream = $client.GetStream()
    $stream.ReadTimeout = 2000
    $request = [Text.Encoding]::ASCII.GetBytes("GET /api/bridge/health HTTP/1.0`r`nHost: 127.0.0.1`r`nConnection: close`r`n`r`n")
    $stream.Write($request, 0, $request.Length)
    $buffer = New-Object byte[] 8192
    $builder = New-Object Text.StringBuilder
    do {
        $read = $stream.Read($buffer, 0, $buffer.Length)
        if ($read -gt 0) { [void]$builder.Append([Text.Encoding]::UTF8.GetString($buffer, 0, $read)) }
    } while ($read -gt 0)
    $text = $builder.ToString()
    if ($text -match "HTTP/1\.[01] 200" -and
        $text -match '"name"\s*:\s*"Rastreador OSINT-BOOLEANO"' -and
        $text -match '"ai_used"\s*:\s*false') { exit 0 }
} catch {}
finally {
    if ($client) { $client.Dispose() }
}
exit 1
