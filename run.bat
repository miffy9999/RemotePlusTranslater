@echo off
setlocal
cd /d "%~dp0"

rem Remove deprecated VBScript launchers left from old patches.
if exist "RemotePlus Translator.vbs" del /q "RemotePlus Translator.vbs" >nul 2>nul
if exist "run_app_silent.vbs" del /q "run_app_silent.vbs" >nul 2>nul

if not exist ".venv\Scripts\pythonw.exe" (
  echo Run install.bat or install.ps1 first.
  pause
  exit /b 1
)

start "" "%~dp0.venv\Scripts\pythonw.exe" -m translator_app.cli desktop
exit /b 0
