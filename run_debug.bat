@echo off
setlocal
cd /d "%~dp0"
set "REMOTEPLUS_DEBUG=1"
set "REMOTEPLUS_DEBUG_STARTUP=1"
set "REMOTEPLUS_ENUMERATE_AUDIO_DEVICES=1"
set "REMOTEPLUS_ENUMERATE_TTS_OUTPUTS=1"
".venv\Scripts\python.exe" -m translator_app.cli desktop
pause
