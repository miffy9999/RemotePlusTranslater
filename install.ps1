$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Find-Python {
    $candidates = @(
        @{Exe='py'; Args=@('-3.11')},
        @{Exe='py'; Args=@('-3.12')},
        @{Exe='py'; Args=@('-3.13')},
        @{Exe='python'; Args=@()}
    )
    foreach ($item in $candidates) {
        try {
            $version = & $item.Exe @($item.Args) -c "import struct, sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor) + ':' + str(8 * struct.calcsize('P')))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -in @('3.11:64','3.12:64','3.13:64')) { return $item }
        } catch { }
    }
    throw 'Python 3.11, 3.12, or 3.13 (64-bit) was not found.'
}

$python = Find-Python
Write-Host "Using Python $(& $python.Exe @($python.Args) --version)" -ForegroundColor Cyan
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$rebuildVenv = -not (Test-Path -LiteralPath $venvPython)
if (-not $rebuildVenv) {
    try {
        & $venvPython -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)" 2>$null
        $rebuildVenv = $LASTEXITCODE -ne 0
    } catch {
        $rebuildVenv = $true
    }
}
if ($rebuildVenv) {
    Write-Host 'Creating or repairing the project virtual environment...' -ForegroundColor Yellow
    & $python.Exe @($python.Args) -m venv --clear .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed: $LASTEXITCODE" }
}
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Packaging tool installation failed: $LASTEXITCODE" }
& $venvPython -m pip install --upgrade -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw "Application dependency installation failed: $LASTEXITCODE" }
& $venvPython -m translator_app.cli doctor
if ($LASTEXITCODE -ne 0) { throw "Installation doctor failed: $LASTEXITCODE" }
Write-Host "`nInstallation complete. Run prepare_models.bat once to download and verify the local STT and translation models." -ForegroundColor Green
Read-Host 'Press Enter to close'
