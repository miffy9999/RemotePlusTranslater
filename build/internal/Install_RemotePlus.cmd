@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-RemotePlus.ps1"
if errorlevel 1 (
  echo.
  echo RemotePlus Translator could not be installed.
  echo Please send this file to the administrator:
  echo %LOCALAPPDATA%\RemotePlusTranslator\install.log
  pause
  exit /b 1
)
exit /b 0
