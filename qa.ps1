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

$parseErrors = @()
foreach ($script in @(
    '.\build.ps1',
    '.\publish_release.ps1',
    '.\deploy_to_vps.ps1',
    '.\scripts\stress_portable.ps1'
)) {
    $currentErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path -LiteralPath $script),
        [ref]$null,
        [ref]$currentErrors
    ) | Out-Null
    $parseErrors += @($currentErrors)
}
if ($parseErrors.Count -gt 0) {
    throw "PowerShell syntax QA failed: $($parseErrors[0].Message)"
}

# Keep each command separate and check its native exit code. Windows PowerShell
# otherwise continues after a failed executable and can hide it with a later 0.
Invoke-Python -m pytest -q
Invoke-Python -m ruff check translator_app tests scripts launcher.py
Invoke-Python -m compileall -q translator_app launcher.py
Invoke-Python -m pip check
Invoke-Python scripts\prepare_finetune_data.py
Invoke-Python scripts\generate_compliance.py cache\qa-compliance

if ($Models) {
    Invoke-Python scripts\benchmark_hymt2.py
    Invoke-Python scripts\benchmark_public_audio.py
}

Write-Host 'QA passed.' -ForegroundColor Green
