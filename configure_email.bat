@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_email.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo guardar la configuracion de correo.
  pause
  exit /b 1
)
pause
