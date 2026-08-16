$ErrorActionPreference = "Stop"
$target = "RastreadorOSINTBooleanoSMTP"

Write-Host "Configuracion de alertas por correo" -ForegroundColor Cyan
Write-Host "La clave se guardara en el Administrador de credenciales de Windows."
$hostName = Read-Host "Servidor SMTP (ej.: smtp.gmail.com)"
if ($hostName -match "@") { throw "Servidor SMTP invalido. Para Gmail escriba smtp.gmail.com; el correo va en Usuario SMTP." }
$port = Read-Host "Puerto [587]"
if ([string]::IsNullOrWhiteSpace($port)) { $port = "587" }
$user = Read-Host "Usuario SMTP"
$from = Read-Host "Remitente [$user]"
if ([string]::IsNullOrWhiteSpace($from)) { $from = $user }
$securePassword = Read-Host "Clave SMTP o clave de aplicacion" -AsSecureString

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    & cmdkey.exe /generic:$target /user:$user /pass:$plainPassword | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Windows no pudo guardar la credencial." }
} finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $plainPassword = $null
}

[Environment]::SetEnvironmentVariable("OSINT_SMTP_HOST", $hostName, "User")
[Environment]::SetEnvironmentVariable("OSINT_SMTP_PORT", $port, "User")
[Environment]::SetEnvironmentVariable("OSINT_SMTP_USER", $user, "User")
[Environment]::SetEnvironmentVariable("OSINT_SMTP_FROM", $from, "User")
[Environment]::SetEnvironmentVariable("OSINT_SMTP_STARTTLS", "true", "User")
[Environment]::SetEnvironmentVariable("OSINT_SMTP_SSL", "false", "User")
$env:OSINT_SMTP_HOST = $hostName
$env:OSINT_SMTP_PORT = $port
$env:OSINT_SMTP_USER = $user
$env:OSINT_SMTP_FROM = $from
$env:OSINT_SMTP_STARTTLS = "true"
$env:OSINT_SMTP_SSL = "false"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $root ".venv\Scripts\python.exe"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $pythonPath -and $_.CommandLine -match "bridge.server" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
& (Join-Path $root "start_bridge.bat") --background

Write-Host "Correo configurado y rastreador reiniciado." -ForegroundColor Green
Write-Host "Use el boton Probar del panel para confirmar el email y la invitacion de Google Calendar."
