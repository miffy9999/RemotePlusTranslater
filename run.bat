@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run install.bat or install.ps1 first.
  pause
  exit /b 1
)
start "" /min wscript.exe //nologo "%~dp0RemotePlus Translator.vbs"
exit /b 0
