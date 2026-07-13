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
if (-not (Test-Path '.venv')) {
    & $python.Exe @($python.Args) -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed: $LASTEXITCODE" }
}
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Packaging tool installation failed: $LASTEXITCODE" }
& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw "Application dependency installation failed: $LASTEXITCODE" }
& '.\.venv\Scripts\python.exe' -m translator_app.cli doctor
if ($LASTEXITCODE -ne 0) { throw "Installation doctor failed: $LASTEXITCODE" }
Write-Host "`nInstallation complete. Run prepare_models.bat once to download and verify the local STT, translation, and TTS models. Windows speech language packs are not required." -ForegroundColor Green
Read-Host 'Press Enter to close'
