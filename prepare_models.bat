@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m translator_app.cli prepare
set "PREPARE_EXIT=%ERRORLEVEL%"
pause
exit /b %PREPARE_EXIT%
