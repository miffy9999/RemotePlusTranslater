param(
    [string]$Publisher = 'RemotePlus',
    [int]$CertificateYears = 3,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($env:OS -ne 'Windows_NT') {
    throw 'Internal Authenticode releases can only be built on Windows.'
}
if ($Publisher -notmatch '^[A-Za-z0-9 ._-]{2,80}$') {
    throw 'Publisher must contain only letters, numbers, spaces, dot, underscore, or hyphen.'
}
if ($CertificateYears -lt 1 -or $CertificateYears -gt 5) {
    throw 'CertificateYears must be between 1 and 5.'
}

$subject = "CN=$Publisher"
$friendlyName = "$Publisher Internal Code Signing"
$codeSigningEku = '1.3.6.1.5.5.7.3.3'

function Get-InternalSigningCertificate {
    Get-ChildItem -LiteralPath 'Cert:\CurrentUser\My' |
        Where-Object {
            $ekuValues = @($_.EnhancedKeyUsageList | ForEach-Object { [string]$_.ObjectId })
            $_.Subject -eq $subject -and
            $_.FriendlyName -eq $friendlyName -and
            $_.HasPrivateKey -and
            $_.NotAfter -gt (Get-Date).AddDays(90) -and
            ($ekuValues -contains $codeSigningEku)
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
}

function Install-PublicCertificateTrust([System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate) {
    foreach ($storeName in @('Root', 'TrustedPublisher')) {
        $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
            $storeName,
            [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
        )
        try {
            $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
            if (-not ($store.Certificates | Where-Object Thumbprint -eq $Certificate.Thumbprint)) {
                $store.Add($Certificate)
            }
        } finally {
            $store.Close()
        }
    }
}

$certificate = Get-InternalSigningCertificate
if (-not $certificate) {
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -FriendlyName $friendlyName `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears($CertificateYears)
}
Install-PublicCertificateTrust $certificate

if (-not $SkipBuild) {
    & '.\build.ps1'
    if ($LASTEXITCODE -ne 0) {
        throw "Portable build failed with exit code $LASTEXITCODE"
    }
}

$version = (& '.\.venv\Scripts\python.exe' -c 'from translator_app import __version__; print(__version__)').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw 'Could not determine the application version.'
}

$portableRoot = Join-Path $PSScriptRoot 'dist\RemotePlusTranslator'
$mainExe = Join-Path $portableRoot 'RemotePlusTranslator.exe'
$llamaExe = Join-Path $portableRoot 'models\hymt2\llama\llama-server.exe'
foreach ($required in @($mainExe, $llamaExe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required release executable was not found: $required"
    }
}

function Set-InternalSignature([string]$Path) {
    $existing = Get-AuthenticodeSignature -LiteralPath $Path
    if ($existing.Status -eq 'Valid') {
        if ($existing.SignerCertificate.Subject -ne $subject -or
            $existing.SignerCertificate.Thumbprint -eq $certificate.Thumbprint) {
            return
        }
    }
    $signature = Set-AuthenticodeSignature `
        -LiteralPath $Path `
        -Certificate $certificate `
        -HashAlgorithm SHA256 `
        -TimestampServer 'http://timestamp.digicert.com'
    if ($signature.Status -ne 'Valid') {
        throw "Signing failed: $Path ($($signature.Status): $($signature.StatusMessage))"
    }
}

# Sign every unsigned executable module that Windows Defender can load. Preserve
# already-valid vendor signatures (for example Microsoft runtime components).
$signedPaths = [System.Collections.Generic.List[string]]::new()
Get-ChildItem -LiteralPath $portableRoot -Recurse -File |
    Where-Object Extension -In @('.exe', '.dll', '.pyd') |
    ForEach-Object {
        $before = Get-AuthenticodeSignature -LiteralPath $_.FullName
        Set-InternalSignature $_.FullName
        $after = Get-AuthenticodeSignature -LiteralPath $_.FullName
        if ($after.Status -ne 'Valid') {
            throw "Invalid signature after signing: $($_.FullName) ($($after.Status))"
        }
        if ($before.Status -ne 'Valid') {
            $signedPaths.Add($_.FullName)
        }
    }

$dateTag = Get-Date -Format 'yyyyMMdd'
$releaseName = "RemotePlusTranslator-$version-INTERNAL-SIGNED-$dateTag"
$releaseRoot = Join-Path $PSScriptRoot "dist\$releaseName"
$releaseAppRoot = Join-Path $releaseRoot 'RemotePlusTranslator'
$zipPath = Join-Path $PSScriptRoot "dist\$releaseName.zip"
$hashPath = "$zipPath.sha256.txt"

Remove-Item -LiteralPath $releaseRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $hashPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -LiteralPath $portableRoot -Destination $releaseAppRoot -Recurse -Force

$publicCertificatePath = Join-Path $releaseRoot 'RemotePlus-Internal-Code-Signing.cer'
Export-Certificate -Cert $certificate -FilePath $publicCertificatePath -Type CERT | Out-Null
Copy-Item -LiteralPath '.\build\internal\Install-RemotePlus.ps1' -Destination $releaseRoot -Force
Copy-Item -LiteralPath '.\build\internal\Install_RemotePlus.cmd' -Destination $releaseRoot -Force
Copy-Item -LiteralPath '.\build\internal\README_FIRST_JA.txt' -Destination $releaseRoot -Force

$manifestItems = foreach ($file in Get-ChildItem -LiteralPath $releaseAppRoot -Recurse -File) {
    $relativePath = $file.FullName.Substring($releaseAppRoot.TrimEnd('\').Length + 1)
    [ordered]@{
        path = $relativePath.Replace('\', '/')
        length = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    schema_version = 1
    publisher = $Publisher
    version = $version
    certificate_thumbprint = $certificate.Thumbprint
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    files = @($manifestItems)
}
$manifest | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $releaseRoot 'release-manifest.json') -Encoding UTF8

$releaseInfo = [ordered]@{
    schema_version = 1
    publisher = $Publisher
    version = $version
    certificate_thumbprint = $certificate.Thumbprint
    certificate_not_after = $certificate.NotAfter.ToUniversalTime().ToString('o')
    app_directory = 'RemotePlusTranslator'
    signed_entrypoints = @(
        'RemotePlusTranslator.exe',
        'models/hymt2/llama/llama-server.exe'
    )
}
$releaseInfo | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $releaseRoot 'release-info.json') -Encoding UTF8

Compress-Archive -LiteralPath $releaseRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$zipHash  $([IO.Path]::GetFileName($zipPath))" |
    Set-Content -LiteralPath $hashPath -Encoding ASCII

$signatureReport = [ordered]@{
    publisher = $Publisher
    version = $version
    certificate_subject = $certificate.Subject
    certificate_thumbprint = $certificate.Thumbprint
    certificate_not_after = $certificate.NotAfter.ToString('o')
    newly_signed_module_count = $signedPaths.Count
    package = $zipPath
    package_sha256 = $zipHash
    package_bytes = (Get-Item -LiteralPath $zipPath).Length
}
$signatureReport | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dist\internal-signature-report.json') -Encoding UTF8

Write-Host "Internal signed release created: $zipPath" -ForegroundColor Green
Write-Host "Certificate thumbprint: $($certificate.Thumbprint)" -ForegroundColor Cyan
Write-Host "SHA256: $zipHash" -ForegroundColor Cyan
Write-Warning 'This internal certificate becomes trusted only after Install_RemotePlus.cmd runs on each hotel PC.'
