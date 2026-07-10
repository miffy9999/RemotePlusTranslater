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

set "PYTHONUTF8=1"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
set "REMOTEPLUS_START_PAUSED=1"

".venv\Scripts\python.exe" -m translator_app.cli desktop
if errorlevel 1 (
  echo RemotePlus exited with code %errorlevel%.
  pause
)
