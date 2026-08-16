@echo off
setlocal
set "PY32=tools\python38-x86\python.exe"
if not exist "%PY32%" (
  echo ERROR: Falta Python 3.8 de 32 bits.
  exit /b 1
)
if not exist "compat_win7\bridge" mkdir "compat_win7\bridge"
xcopy /E /I /Y bridge compat_win7\bridge >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem compat_win7\bridge -Filter *.py -Recurse | %% { $v=Get-Content $_.FullName -Raw; $v=$v -replace ' \| ',' or '; Set-Content $_.FullName $v -Encoding UTF8 }"
"%PY32%" -m pip install pyinstaller >nul
"%PY32%" -m PyInstaller --noconfirm --clean --onedir --console --name "OSINT-BOOLEANO-Win7-32" --paths compat_win7 --add-data "compat_win7\bridge;bridge" --add-data "panel;panel" --hidden-import bridge.server --hidden-import bridge.watcher --hidden-import bridge.google_calendar launcher.py
"%PY32%" -m PyInstaller --noconfirm --clean --onefile --console --name "OSINT-BOOLEANO-Rastreo-Win7-32" --paths compat_win7 --add-data "compat_win7\bridge;bridge" --hidden-import bridge.watcher --hidden-import bridge.google_calendar watcher_launcher.py
"%PY32%" -m PyInstaller --noconfirm --clean --onefile --console --name "Instalar-OSINT-BOOLEANO-Win7-32" --add-data "dist\OSINT-BOOLEANO-Win7-32;payload\app" --add-data "dist\OSINT-BOOLEANO-Rastreo-Win7-32.exe;payload\app" --add-data "config;payload\config" --add-data "README_INSTALACION.txt;." installer_launcher.py
if exist "dist\Instalar-OSINT-BOOLEANO-Win7-32.exe" echo [OK] dist\Instalar-OSINT-BOOLEANO-Win7-32.exe
endlocal
