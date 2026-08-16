@echo off
REM build_exe.bat — Compila el Rastreador OSINT-BOOLEANO como .exe
REM Ejecutar desde la carpeta APP OSINT-BOOLEANO

echo ============================================================
echo   COMPILANDO RASTREADOR OSINT-BOOLEANO
echo ============================================================
echo.

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] Instalando PyInstaller...
    ".venv\Scripts\python.exe" -m pip install pyinstaller
)

".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --console ^
    --name "OSINT-BOOLEANO" ^
    --add-data "bridge;bridge" ^
    --add-data "panel;panel" ^
    --hidden-import bridge ^
    --hidden-import bridge.server ^
    --hidden-import bridge.pipeline ^
    --hidden-import bridge.watcher ^
    --hidden-import bridge.notifier ^
    --hidden-import bridge.windows_credentials ^
    --hidden-import bridge.storage ^
    --hidden-import bridge.recipients ^
    --hidden-import bridge.models ^
    --hidden-import bridge.boolean_parser ^
    launcher.py

".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name "OSINT-BOOLEANO-Rastreo" ^
    --add-data "bridge;bridge" ^
    --hidden-import bridge ^
    --hidden-import bridge.watcher ^
    --hidden-import bridge.storage ^
    --hidden-import bridge.recipients ^
    --hidden-import bridge.google_calendar ^
    watcher_launcher.py

echo.
if exist "dist\OSINT-BOOLEANO\OSINT-BOOLEANO.exe" (
    echo [OK] ejecutables creados en: dist\OSINT-BOOLEANO\ y dist\OSINT-BOOLEANO-Rastreo.exe
    echo.
    echo Copie OSINT-BOOLEANO.exe a la carpeta APP OSINT-BOOLEANO
    echo junto a las carpetas: config\  data\  alerts\  bridge\
) else (
    echo [ERROR] No se creo el .exe. Revise los mensajes de arriba.
)

echo.
