$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$distRoot = Join-Path $PSScriptRoot 'dist\RemotePlusTranslator'
$exePath = Join-Path $distRoot 'RemotePlusTranslator.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
    throw 'Portable EXE not found. Run build.ps1 once before creating a fast app update.'
}

$staging = Join-Path $distRoot 'app_update.staging'
$target = Join-Path $distRoot 'app_update'
$backup = Join-Path $distRoot 'app_update.previous'
Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $staging | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'translator_app') -Destination $staging -Recurse -Force

# Runtime caches and local developer artifacts must never enter an update package.
Get-ChildItem -LiteralPath $staging -Directory -Filter '__pycache__' -Recurse |
    Remove-Item -Recurse -Force
# `-LiteralPath`와 `-Include`의 조합은 Windows PowerShell 버전에 따라 include가
# 무시될 수 있다. 확장자를 직접 비교해 정상 .py 파일이 지워지는 일을 막는다.
Get-ChildItem -LiteralPath $staging -File -Recurse |
    Where-Object { $_.Extension -in @('.pyc', '.pyo') } |
    Remove-Item -Force

$updateInit = Join-Path $staging 'translator_app\__init__.py'
$updateServer = Join-Path $staging 'translator_app\server.py'
if (-not (Test-Path -LiteralPath $updateInit) -or -not (Test-Path -LiteralPath $updateServer)) {
    throw 'Fast update staging is incomplete; the existing update was left untouched.'
}

$files = [ordered]@{}
Get-ChildItem -LiteralPath $staging -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($staging.Length + 1).Replace('\', '/')
    $files[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$version = (& '.\.venv\Scripts\python.exe' -c 'from translator_app import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw 'Could not determine the app version; the existing update was left untouched.'
}
$manifest = [ordered]@{
    schema = 1
    version = $version
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    files = $files
}
$manifestJson = $manifest | ConvertTo-Json -Depth 4
# Windows PowerShell의 -Encoding UTF8은 BOM을 붙인다. Python의 엄격한 JSON 로더와
# 동일하게 동작하도록 BOM 없는 UTF-8을 명시한다.
[System.IO.File]::WriteAllText(
    (Join-Path $staging 'manifest.json'),
    $manifestJson,
    [System.Text.UTF8Encoding]::new($false)
)

Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $target) {
    Move-Item -LiteralPath $target -Destination $backup
}
try {
    Move-Item -LiteralPath $staging -Destination $target
} catch {
    if (Test-Path -LiteralPath $backup) {
        Move-Item -LiteralPath $backup -Destination $target
    }
    throw
}
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue

Copy-Item -LiteralPath '.\config.toml' -Destination (Join-Path $distRoot 'config.toml') -Force
Copy-Item -LiteralPath '.\README.md' -Destination (Join-Path $distRoot 'README.md') -Force
Write-Host "Fast app update $($manifest.version) installed in dist\RemotePlusTranslator\app_update" -ForegroundColor Green
Write-Host 'Models, native DLLs, and the base EXE were not rebuilt. Restart the app to apply it.' -ForegroundColor Green
