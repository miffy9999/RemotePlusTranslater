@echo off
setlocal
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
set "PYTHONUTF8=1"
set "PYGAME_HIDE_SUPPORT_PROMPT=1"
set "REMOTEPLUS_DEBUG=1"
set "REMOTEPLUS_DEBUG_STARTUP=1"
for /f %%I in ('".venv\Scripts\python.exe" -c "import time; print(time.time())"') do set "RUN_STARTED=%%I"
".venv\Scripts\python.exe" -m translator_app.cli desktop
set "APP_EXIT=%ERRORLEVEL%"
echo.
echo Creating timing summary for the latest debug run...
".venv\Scripts\python.exe" scripts\analyze_timing_log.py --latest --after-unix %RUN_STARTED% --write
echo.
echo Debug run exit code: %APP_EXIT%
pause
exit /b %APP_EXIT%
