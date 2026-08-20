@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0GoogleDrive-Setup.ps1"
if errorlevel 1 (
  echo.
  echo RemotePlus Translator could not be prepared or installed.
  pause
  exit /b 1
)
exit /b 0
