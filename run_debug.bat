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
rem Do not nest a quoted Python path inside FOR /F: cmd.exe can reinterpret the
rem first and last quote as one command name (especially from a spaced path).
rem PowerShell supplies an integer epoch without touching the project path.
set "RUN_STARTED=0"
for /f "delims=" %%I in ('%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "RUN_STARTED=%%I"
if "%RUN_STARTED%"=="0" (
  echo Could not create the debug run timestamp.
  exit /b 1
)
if "%REMOTEPLUS_BATCH_SELFTEST%"=="1" (
  echo RUN_STARTED=%RUN_STARTED%
  exit /b 0
)
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo The project virtual environment is damaged or belongs to another computer.
  echo Run install.bat to repair it, then start RemotePlus again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m translator_app.cli desktop
set "APP_EXIT=%ERRORLEVEL%"
echo.
echo Creating timing summary for the latest debug run...
".venv\Scripts\python.exe" scripts\analyze_timing_log.py --latest --after-unix %RUN_STARTED% --write
set "SUMMARY_EXIT=%ERRORLEVEL%"
echo.
echo Debug run exit code: %APP_EXIT%
pause
if not "%APP_EXIT%"=="0" exit /b %APP_EXIT%
exit /b %SUMMARY_EXIT%
