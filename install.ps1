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
            $version = & $item.Exe @($item.Args) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($version -in @('3.11','3.12','3.13')) { return $item }
        } catch { }
    }
    throw 'Python 3.11, 3.12, or 3.13 (64-bit) was not found.'
}

$python = Find-Python
Write-Host "Using Python $(& $python.Exe @($python.Args) --version)" -ForegroundColor Cyan
if (-not (Test-Path '.venv')) {
    & $python.Exe @($python.Args) -m venv .venv
}
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip setuptools wheel
& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
& '.\.venv\Scripts\python.exe' -m translator_app.cli doctor
Write-Host "`nInstallation complete. The live-caption model downloads automatically on first prepare/run; Windows speech language packs are not required." -ForegroundColor Green
Read-Host 'Press Enter to close'
