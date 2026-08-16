@echo off
setlocal
call build_exe.bat
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name "Instalar-Rastreador-OSINT-BOOLEANO" ^
  --add-data "dist\OSINT-BOOLEANO;payload\app" ^
  --add-data "dist\OSINT-BOOLEANO-Rastreo.exe;payload\app" ^
  --add-data "config;payload\config" ^
  --add-data "README_INSTALACION.txt;." ^
  installer_launcher.py
if exist "dist\Instalar-Rastreador-OSINT-BOOLEANO.exe" (
  echo.
  echo [OK] Instalador creado: dist\Instalar-Rastreador-OSINT-BOOLEANO.exe
) else (
  exit /b 1
)
endlocal
