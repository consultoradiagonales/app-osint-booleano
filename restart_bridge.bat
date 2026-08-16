@echo off
setlocal
cd /d "%~dp0"
echo [1/3] Deteniendo bridge en puerto 8765...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
    echo     Proceso %%a terminado.
)
echo [2/3] Esperando 2 segundos...
timeout /t 2 /nobreak >nul
echo [3/3] Iniciando bridge...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1"
exit /b 0