@echo off
setlocal
cd /d "%~dp0"

rem Remove deprecated VBScript launchers left from old patches.
if exist "RemotePlus Translator.vbs" del /q "RemotePlus Translator.vbs" >nul 2>nul
if exist "run_app_silent.vbs" del /q "run_app_silent.vbs" >nul 2>nul

if not exist ".venv\Scripts\python.exe" goto repair_venv
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 goto repair_venv
goto venv_ready
:repair_venv
echo Repairing the local Python environment...
call install.bat
if errorlevel 1 exit /b 1
:venv_ready

set "PYTHONUTF8=1"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
set "REMOTEPLUS_START_PAUSED=1"

".venv\Scripts\python.exe" -m translator_app.cli desktop
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
  echo RemotePlus exited with code %APP_EXIT%.
  pause
)
exit /b %APP_EXIT%
