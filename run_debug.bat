@echo off
setlocal
cd /d "%~dp0"
set "REMOTEPLUS_DEBUG=1"
set "REMOTEPLUS_DEBUG_STARTUP=1"
".venv\Scripts\python.exe" -m translator_app.cli serve
pause
