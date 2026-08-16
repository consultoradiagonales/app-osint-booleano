@echo off
setx OSINT_SMTP_HOST "smtp.gmail.com"
setx OSINT_SMTP_PORT "587"
setx OSINT_SMTP_USER "Fernandogenazzini@gmail.com"
setx OSINT_SMTP_FROM "Fernandogenazzini@gmail.com"
setx OSINT_SMTP_STARTTLS "true"
setx OSINT_SMTP_SSL "false"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = Read-Host 'Clave de aplicacion de Gmail' -AsSecureString; $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); $p = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b); & cmdkey.exe /generic:RastreadorOSINTBooleanoSMTP /user:Fernandogenazzini@gmail.com /pass:$p; [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b); Write-Host 'Credencial guardada.' -ForegroundColor Green"
echo.
echo Configuracion completada: smtp.gmail.com:587
pause