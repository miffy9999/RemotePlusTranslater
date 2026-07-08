$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$env:PYTHONUTF8 = '1'
$env:PYGAME_HIDE_SUPPORT_PROMPT = '1'
$env:REMOTEPLUS_SILENT_LAUNCH = '1'
$env:REMOTEPLUS_START_PAUSED = '1'
$env:REMOTEPLUS_DESKTOP_AUTO_SHUTDOWN = '1'

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw 'Run install.bat or install.ps1 first.'
}

$arguments = @('-m', 'translator_app.cli', 'desktop')
Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
