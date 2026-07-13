@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto repair_venv
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 goto repair_venv
goto venv_ready
:repair_venv
echo Repairing the local Python environment...
call install.bat
if errorlevel 1 exit /b 1
:venv_ready
".venv\Scripts\python.exe" -m translator_app.cli doctor
set "DOCTOR_EXIT=%ERRORLEVEL%"
pause
exit /b %DOCTOR_EXIT%
