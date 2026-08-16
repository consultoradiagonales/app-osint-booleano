@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" configure_google_calendar.py
if errorlevel 1 (
  echo.
  echo No se pudo autorizar Google Calendar. Revise data\google-calendar-setup.log
  pause
  exit /b 1
)
echo.
echo Calendar de Consultora Diagonales configurado correctamente.
pause
