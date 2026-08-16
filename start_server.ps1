$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
$dataPath = Join-Path $root "data"
$stdoutPath = Join-Path $dataPath "server.log"
$stderrPath = Join-Path $dataPath "server-error.log"

function Test-BridgeHealth {
    $client = $null
    try {
        # Socket local directo: no intervienen proxy, WinHTTP, navegador ni DNS.
        $client = New-Object Net.Sockets.TcpClient
        $pending = $client.BeginConnect("127.0.0.1", 8765, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(1500, $false)) { return $false }
        $client.EndConnect($pending)
        $stream = $client.GetStream()
        $stream.ReadTimeout = 1500
        $request = [Text.Encoding]::ASCII.GetBytes("GET /api/bridge/health HTTP/1.0`r`nHost: 127.0.0.1`r`nConnection: close`r`n`r`n")
        $stream.Write($request, 0, $request.Length)
        $buffer = New-Object byte[] 8192
        $builder = New-Object Text.StringBuilder
        do {
            $read = $stream.Read($buffer, 0, $buffer.Length)
            if ($read -gt 0) { [void]$builder.Append([Text.Encoding]::UTF8.GetString($buffer, 0, $read)) }
        } while ($read -gt 0)
        $text = $builder.ToString()
        return [bool]($text -match "HTTP/1\.[01] 200" -and
            $text -match '"name"\s*:\s*"Rastreador OSINT-BOOLEANO"' -and
            $text -match '"ai_used"\s*:\s*false')
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Stop-StaleBridgeListener {
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) { return }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $venvRoot = (Join-Path $root ".venv").ToLowerInvariant()
    $executable = [string]$owner.ExecutablePath
    $command = [string]$owner.CommandLine
    $isPython = $owner.Name -match "^python(w)?\.exe$"
    $isThisBridge = ($executable -and $executable.ToLowerInvariant().StartsWith($venvRoot)) -or
        $command -match "bridge\.server" -or $command -match "APP OSINT-BOOLEANO"
    if ($isPython -and $isThisBridge) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
        return
    }
    throw "El puerto 8765 pertenece a otro programa (PID $($listener.OwningProcess), $($owner.Name)). No se cerro por seguridad. Comando: $command"
}

if (-not (Test-Path $pythonPath)) { throw "No existe el Python virtual en $pythonPath" }
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null

if (Test-BridgeHealth) { exit 0 }
Stop-StaleBridgeListener

$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "-m", "bridge.server", "--host", "0.0.0.0" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($process.HasExited) { break }
    if (Test-BridgeHealth) { exit 0 }
}

$listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$portDetail = ""
if ($listener) {
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $portDetail = "Puerto 8765 ocupado por PID $($listener.OwningProcess) ($($owner.ProcessName))."
}
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300
$process.Refresh()
$errorDetail = ""
if (Test-Path $stderrPath) { $errorDetail = (Get-Content $stderrPath -Tail 12) -join " | " }
$outputDetail = ""
if (Test-Path $stdoutPath) { $outputDetail = (Get-Content $stdoutPath -Tail 6) -join " | " }
$exitDetail = if ($process.HasExited) { "Codigo de salida: $($process.ExitCode)." } else { "" }
throw "El servicio no respondio en el puerto 8765. $portDetail $exitDetail $errorDetail $outputDetail"
