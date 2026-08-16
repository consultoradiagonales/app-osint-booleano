@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "%~dp0start_bridge.bat" --background
if not exist "data" mkdir "data"
".venv\Scripts\python.exe" -m bridge.watcher --scheduled >> "data\watcher.log" 2>&1
endlocal
