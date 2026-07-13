param(
    [switch]$Models
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run install.bat first.'
}
$env:PYTHONUTF8 = '1'

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "QA command failed ($LASTEXITCODE): python $($Arguments -join ' ')"
    }
}

# Keep each command separate and check its native exit code. Windows PowerShell
# otherwise continues after a failed executable and can hide it with a later 0.
Invoke-Python -m pytest -q
Invoke-Python -m ruff check translator_app tests scripts launcher.py update_guard.py
Invoke-Python -m compileall -q translator_app launcher.py update_guard.py
Invoke-Python -m pip check

if ($Models) {
    Invoke-Python scripts\benchmark_hymt2.py
    Invoke-Python scripts\benchmark_public_audio.py
}

Write-Host 'QA passed.' -ForegroundColor Green
