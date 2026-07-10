$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    throw 'Run install.bat first.'
}

& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
Remove-Item -Recurse -Force '.\dist\RemotePlusTranslator' -ErrorAction SilentlyContinue
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean '.\build\local_bridge.spec'
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
Copy-Item '.\config.toml' '.\dist\RemotePlusTranslator\config.toml' -Force
Copy-Item '.\README.md' '.\dist\RemotePlusTranslator\README.md' -Force
Copy-Item '.\THIRD_PARTY_NOTICES.md' '.\dist\RemotePlusTranslator\THIRD_PARTY_NOTICES.md' -Force
Copy-Item '.\docs' '.\dist\RemotePlusTranslator\docs' -Recurse -Force
New-Item -ItemType Directory '.\dist\RemotePlusTranslator\models' -Force | Out-Null
Copy-Item '.\models\whisper' '.\dist\RemotePlusTranslator\models\whisper' -Recurse -Force
New-Item -ItemType Directory '.\dist\RemotePlusTranslator\models\hymt2' -Force | Out-Null
Copy-Item '.\models\hymt2\Hy-MT2-1.8B-Q4_K_M.gguf' '.\dist\RemotePlusTranslator\models\hymt2\Hy-MT2-1.8B-Q4_K_M.gguf' -Force
Copy-Item '.\models\hymt2\llama' '.\dist\RemotePlusTranslator\models\hymt2\llama' -Recurse -Force
$env:REMOTEPLUS_BUILD_DOCTOR = '1'
$doctor = Start-Process -FilePath '.\dist\RemotePlusTranslator\RemotePlusTranslator.exe' -ArgumentList 'doctor' -WindowStyle Hidden -Wait -PassThru
Remove-Item Env:\REMOTEPLUS_BUILD_DOCTOR -ErrorAction SilentlyContinue
if ($doctor.ExitCode -ne 0) {
    throw "Built application failed doctor checks with exit code $($doctor.ExitCode)"
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($iscc) {
    & $iscc.Source '.\build\installer.iss'
    Write-Host 'Installer created in dist\installer' -ForegroundColor Green
} else {
    Write-Host 'Portable build created in dist\RemotePlusTranslator.' -ForegroundColor Green
    Write-Host 'Install Inno Setup 6 and rerun to also create Setup.exe.' -ForegroundColor Yellow
}
