$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Test-PythonCandidate($candidate) {
    try {
        $probe = & $candidate.Exe @($candidate.Args) -c "import struct,sys; ok=(3,11)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 and 'windowsapps' not in sys.executable.casefold(); print(f'{sys.version_info.major}.{sys.version_info.minor}|{struct.calcsize('P') * 8}'); raise SystemExit(0 if ok else 1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe -match '^(3\.11|3\.12|3\.13)\|64$') {
            return $true
        }
    } catch { }
    return $false
}

function Find-Python {
    $candidates = @(
        @{Exe='py'; Args=@('-3.11')},
        @{Exe='py'; Args=@('-3.12')},
        @{Exe='py'; Args=@('-3.13')},
        @{Exe='python'; Args=@()},
        @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'); Args=@()},
        @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); Args=@()},
        @{Exe=(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'); Args=@()}
    )
    foreach ($item in $candidates) {
        if (Test-PythonCandidate $item) { return $item }
    }
    return $null
}

$python = Find-Python
if ($null -eq $python) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw 'Python 3.11, 3.12, or 3.13 (64-bit) was not found, and winget is unavailable. Install 64-bit Python 3.12 and run install.bat again.'
    }
    Write-Host 'Python 3.12 is missing. Installing the official 64-bit package with winget...' -ForegroundColor Yellow
    & $winget.Source install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Python installation failed with exit code $LASTEXITCODE"
    }
    $python = Find-Python
    if ($null -eq $python) {
        throw 'Python was installed but could not be located. Open a new terminal and run install.bat again.'
    }
}
Write-Host "Using Python $(& $python.Exe @($python.Args) --version) (64-bit)" -ForegroundColor Cyan

$venvRoot = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$venvConfig = Join-Path $venvRoot 'pyvenv.cfg'
$venvHealthy = $false
if ((Test-Path $venvPython) -and (Test-Path $venvConfig) -and
    -not ((Get-Content -LiteralPath $venvConfig -Raw) -match '(?i)WindowsApps')) {
    try {
        & $venvPython -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
        $venvHealthy = $LASTEXITCODE -eq 0
    } catch { }
}
if (-not $venvHealthy) {
    if (Test-Path $venvRoot) {
        $resolvedRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
        $resolvedVenv = [IO.Path]::GetFullPath($venvRoot)
        if ([IO.Path]::GetDirectoryName($resolvedVenv).TrimEnd('\') -ne $resolvedRoot) {
            throw "Refusing to remove unexpected virtual environment path: $resolvedVenv"
        }
        Write-Host 'Removing an unusable virtual environment from another PC or Python installation.' -ForegroundColor Yellow
        Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
    }
    & $python.Exe @($python.Args) -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE" }
}

& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Build tool installation failed with exit code $LASTEXITCODE" }
& $venvPython -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw "Project dependency installation failed with exit code $LASTEXITCODE" }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Installed dependencies are inconsistent (exit code $LASTEXITCODE)" }
& $venvPython -m translator_app.cli doctor
if ($LASTEXITCODE -ne 0) { throw "Installation doctor failed with exit code $LASTEXITCODE" }
Write-Host "`nInstallation complete. Run prepare_models.bat once to download/verify the local STT and translation models. Edge TTS is online; Windows speech language packs are not required." -ForegroundColor Green
