@echo off
cd /d "E:\CODEX ChatGPT\01 - BOOLEANO\PROYECTO AUTOMATIZACION\APP OSINT-BOOLEANO"
echo Instalando modulo keyring...
".venv\Scripts\pip.exe" install keyring --quiet
echo.
echo Ejecutando prueba de email...
echo.
".venv\Scripts\python.exe" test_email.py
pause