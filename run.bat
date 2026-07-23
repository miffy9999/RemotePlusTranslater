@echo off
setlocal
cd /d "%~dp0"

rem Remove deprecated VBScript launchers left from old patches.
if exist "RemotePlus Translator.vbs" del /q "RemotePlus Translator.vbs" >nul 2>nul
if exist "run_app_silent.vbs" del /q "run_app_silent.vbs" >nul 2>nul

if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat or install.ps1 first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo The windowless Python launcher is missing. Run install.bat to repair it.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo The project virtual environment is damaged or belongs to another computer.
  echo Run install.bat to repair it, then start RemotePlus again.
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
set "REMOTEPLUS_START_PAUSED=1"

rem Normal use has one native RemotePlus window. The local API and translation
rem engine run without a console; use run_debug.bat when terminal logs are needed.
start "" ".venv\Scripts\pythonw.exe" -m translator_app.cli desktop
exit /b 0
