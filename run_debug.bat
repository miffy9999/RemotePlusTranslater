@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat or install.ps1 first.
  pause
  exit /b 1
)
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
