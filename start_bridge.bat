@echo off
setlocal
cd /d "%~dp0"
set "BRIDGE_START=%~dp0start_bridge.bat"
set "BRIDGE_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Rastreador_OSINT_BOOLEANO.lnk"
rem Siempre reemplaza el acceso directo para migrar instalaciones antiguas de C: a E:.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w = New-Object -ComObject WScript.Shell; $s = $w.CreateShortcut($env:BRIDGE_LINK); $s.TargetPath = $env:BRIDGE_START; $s.Arguments = '--background'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7; $s.Description = 'Inicio automatico del Rastreador OSINT-BOOLEANO'; $s.Save()" >nul 2>&1
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
  ".venv\Scripts\python.exe" -m pip install --no-cache-dir -e .
  if errorlevel 1 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_bridge_health.ps1" >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1"
  if errorlevel 1 exit /b 1
)
if /I not "%~1"=="--background" start "" "http://127.0.0.1:8765/mobile"
endlocal
exit /b 0
