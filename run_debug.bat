@echo off
setlocal

cd /d "%~dp0"

set "REMOTEPLUS_DEBUG=1"

call "%~dp0run.bat"

pause