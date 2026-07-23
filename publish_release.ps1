param(
    [ValidateSet('stable', 'beta')][string]$Channel = 'stable',
    [string]$DeploymentBundle = '.\dist\vps-deployment',
    [switch]$Mandatory
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$version = (& '.\.venv\Scripts\python.exe' -c 'from translator_app import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw 'Could not determine the application version.'
}
$installer = ".\dist\installer\RemotePlusTranslator-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Signed installer not found: $installer. Run build.ps1 -CommercialRelease first."
}
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid') {
    throw "Installer Authenticode signature is not valid: $($signature.Status)"
}

$deploymentFile = Join-Path $DeploymentBundle 'deployment.json'
$renderedSite = Join-Path $DeploymentBundle 'site'
if (-not (Test-Path -LiteralPath $deploymentFile) -or -not (Test-Path -LiteralPath $renderedSite)) {
    throw 'Rendered VPS deployment bundle is missing. Run scripts\prepare_vps_deployment.py first.'
}
$deployment = Get-Content -LiteralPath $deploymentFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($deployment.schema -ne 1 -or [string]::IsNullOrWhiteSpace($deployment.download_domain)) {
    throw 'Rendered VPS deployment metadata is invalid.'
}
if ($deployment.version -ne $version) {
    throw "Deployment bundle targets version $($deployment.version), but the installer is $version."
}
$placeholder = Get-ChildItem -LiteralPath $DeploymentBundle -File -Recurse |
    Select-String -Pattern '(_HERE\b|\bREPLACE(_|\s+WITH\b))' -CaseSensitive:$false
if ($placeholder) {
    throw "Rendered VPS deployment bundle contains placeholders: $($placeholder[0].Path)"
}
$baseUrl = "https://$($deployment.download_domain)"

$releaseRoot = ".\dist\vps-release\releases\$version"
$channelRoot = ".\dist\vps-release\channels\$Channel"
if (Test-Path -LiteralPath $releaseRoot) {
    $existingInstaller = Join-Path $releaseRoot (Split-Path -Leaf $installer)
    if (-not (Test-Path -LiteralPath $existingInstaller) -or
        (Get-FileHash -LiteralPath $existingInstaller -Algorithm SHA256).Hash -ne
        (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash) {
        throw "Versioned release path already exists with different content: $releaseRoot"
    }
} else {
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    Copy-Item -LiteralPath $installer -Destination $releaseRoot
}
New-Item -ItemType Directory -Path $channelRoot -Force | Out-Null
$publishedInstaller = Join-Path $releaseRoot (Split-Path -Leaf $installer)
$artifactBaseUrl = "$($BaseUrl.TrimEnd('/'))/releases/$version/"
$arguments = @(
    '.\scripts\generate_release_manifest.py',
    '--artifact', $publishedInstaller,
    '--base-url', $artifactBaseUrl,
    '--channel', $Channel,
    '--version', $version,
    '--output', (Join-Path $channelRoot 'manifest.json')
)
if ($Mandatory) { $arguments += '--mandatory' }
& '.\.venv\Scripts\python.exe' @arguments
if ($LASTEXITCODE -ne 0) { throw 'Release manifest generation failed.' }

$siteTarget = '.\dist\vps-release\site'
Remove-Item -LiteralPath $siteTarget -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $renderedSite -Destination $siteTarget -Recurse
$opsTarget = '.\dist\vps-release\ops'
Remove-Item -LiteralPath $opsTarget -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $opsTarget -Force | Out-Null
foreach ($name in @('activate_release.sh', 'rollback_channel.sh', 'check_capacity.sh', 'Caddyfile', 'deployment.json')) {
    $source = Join-Path $DeploymentBundle $name
    if (-not (Test-Path -LiteralPath $source)) { throw "Deployment bundle file is missing: $source" }
    Copy-Item -LiteralPath $source -Destination $opsTarget
}
Write-Host "VPS upload tree ready: dist\vps-release ($Channel $version)" -ForegroundColor Green
Write-Host 'Next: deploy_to_vps.ps1 (activation includes a strict capacity preflight).' -ForegroundColor Yellow
