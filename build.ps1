param([switch]$CommercialRelease)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$commercialMetadata = $null
$commercialInfoPath = '.\legal\distributor-info.local.json'
if ($CommercialRelease) {
    if (-not (Test-Path -LiteralPath $commercialInfoPath)) {
        throw 'Copy legal\distributor-info.example.json to legal\distributor-info.local.json and enter the real operator information.'
    }
    try {
        $commercialMetadata = Get-Content -Raw -Encoding UTF8 $commercialInfoPath | ConvertFrom-Json
    } catch {
        throw "Invalid commercial distributor metadata: $($_.Exception.Message)"
    }
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    throw 'Run install.bat first.'
}

& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed with exit code $LASTEXITCODE"
}
Remove-Item -Recurse -Force '.\dist\RemotePlusTranslator' -ErrorAction SilentlyContinue
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean '.\build\local_bridge.spec'
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
Copy-Item '.\config.toml' '.\dist\RemotePlusTranslator\config.toml' -Force
Copy-Item '.\README.md' '.\dist\RemotePlusTranslator\README.md' -Force
Copy-Item '.\THIRD_PARTY_NOTICES.md' '.\dist\RemotePlusTranslator\THIRD_PARTY_NOTICES.md' -Force
if ($CommercialRelease) {
    & '.\.venv\Scripts\python.exe' '.\scripts\prepare_commercial_release.py' `
        --info $commercialInfoPath `
        --destination '.\dist\RemotePlusTranslator'
    if ($LASTEXITCODE -ne 0) {
        throw 'Commercial legal documents are incomplete. The release was not created.'
    }
} else {
    # Development packages intentionally retain obvious template tokens. The
    # commercial build path above is the only path that may produce release docs.
    Copy-Item '.\EULA_JA.md' '.\dist\RemotePlusTranslator\EULA_JA.md' -Force
    Copy-Item '.\PRIVACY_NOTICE_JA.md' '.\dist\RemotePlusTranslator\PRIVACY_NOTICE_JA.md' -Force
}
Copy-Item '.\docs' '.\dist\RemotePlusTranslator\docs' -Recurse -Force
& '.\.venv\Scripts\python.exe' '.\scripts\generate_compliance.py' '.\dist\RemotePlusTranslator'
if ($LASTEXITCODE -ne 0) {
    throw 'Compliance inventory is incomplete. Add the missing license files before release.'
}

function Sign-CommercialArtifact([string]$Path) {
    if (-not $CommercialRelease) { return }
    $thumbprint = $env:REMOTEPLUS_SIGN_CERT_SHA1
    if (-not $thumbprint) { throw 'REMOTEPLUS_SIGN_CERT_SHA1 is required for -CommercialRelease.' }
    $thumbprint = $thumbprint.Replace(' ', '').ToUpperInvariant()
    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
    if (-not $certificate) { throw "Code-signing certificate was not found: $thumbprint" }
    if (-not $certificate.HasPrivateKey) { throw 'The code-signing certificate has no accessible private key.' }
    if ($certificate.NotAfter -lt (Get-Date).AddDays(30)) {
        throw "The code-signing certificate expires too soon: $($certificate.NotAfter.ToString('o'))"
    }
    $codeSigningEku = '1.3.6.1.5.5.7.3.3'
    if (-not ($certificate.EnhancedKeyUsageList.ObjectId.Value -contains $codeSigningEku)) {
        throw 'The selected certificate is not valid for Code Signing.'
    }
    if ($commercialMetadata.distribution_scope -eq 'third_party_distribution' -and
        $certificate.Subject -eq $certificate.Issuer) {
        throw 'A self-signed internal certificate cannot be used for third-party distribution.'
    }
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) { throw 'signtool.exe from the Windows SDK is required for -CommercialRelease.' }
    & $signtool.Source sign /sha1 $thumbprint /fd SHA256 /tr 'http://timestamp.digicert.com' /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed: $Path" }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid') { throw "Invalid Authenticode signature: $Path ($($signature.Status))" }
}

function Write-SignatureReport([string[]]$Paths) {
    if (-not $CommercialRelease) { return }
    $items = foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        [ordered]@{
            file = (Resolve-Path -LiteralPath $path).Path
            sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            status = $signature.Status.ToString()
            subject = $signature.SignerCertificate.Subject
            issuer = $signature.SignerCertificate.Issuer
            thumbprint = $signature.SignerCertificate.Thumbprint
            certificate_not_after = $signature.SignerCertificate.NotAfter.ToString('o')
            timestamp_subject = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Subject } else { $null }
        }
    }
    $report = [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        distribution_scope = $commercialMetadata.distribution_scope
        publisher = $commercialMetadata.publisher_legal_name
        artifacts = @($items)
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath '.\dist\signature-report.json' -Encoding UTF8
}

Sign-CommercialArtifact '.\dist\RemotePlusTranslator\RemotePlusTranslator.exe'
Sign-CommercialArtifact '.\dist\RemotePlusTranslator\RemotePlusTtsWorker.exe'
New-Item -ItemType Directory '.\dist\RemotePlusTranslator\models' -Force | Out-Null
Copy-Item '.\models\whisper' '.\dist\RemotePlusTranslator\models\whisper' -Recurse -Force
New-Item -ItemType Directory '.\dist\RemotePlusTranslator\models\hymt2' -Force | Out-Null
Copy-Item '.\models\hymt2\Hy-MT2-1.8B-Q4_K_M.gguf' '.\dist\RemotePlusTranslator\models\hymt2\Hy-MT2-1.8B-Q4_K_M.gguf' -Force
Copy-Item '.\models\hymt2\llama' '.\dist\RemotePlusTranslator\models\hymt2\llama' -Recurse -Force
& '.\.venv\Scripts\python.exe' '.\scripts\bundle_tts_packs.py' '.' '.\dist\RemotePlusTranslator'
if ($LASTEXITCODE -ne 0) {
    throw 'Reviewed TTS packs are missing or failed integrity verification.'
}
$env:REMOTEPLUS_BUILD_DOCTOR = '1'
$doctor = Start-Process -FilePath '.\dist\RemotePlusTranslator\RemotePlusTranslator.exe' -ArgumentList 'doctor' -WindowStyle Hidden -Wait -PassThru
Remove-Item Env:\REMOTEPLUS_BUILD_DOCTOR -ErrorAction SilentlyContinue
if ($doctor.ExitCode -ne 0) {
    throw "Built application failed doctor checks with exit code $($doctor.ExitCode)"
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($CommercialRelease -and $iscc) {
    & $iscc.Source '.\build\installer.iss'
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
    Write-Host 'Installer created in dist\installer' -ForegroundColor Green
    Sign-CommercialArtifact ".\dist\installer\RemotePlusTranslator-Setup-0.6.0.exe"
    Write-SignatureReport @(
        '.\dist\RemotePlusTranslator\RemotePlusTranslator.exe',
        '.\dist\RemotePlusTranslator\RemotePlusTtsWorker.exe',
        '.\dist\installer\RemotePlusTranslator-Setup-0.6.0.exe'
    )
} else {
    if ($CommercialRelease) { throw 'Inno Setup 6 is required for -CommercialRelease.' }
    Write-Host 'Portable build created in dist\RemotePlusTranslator.' -ForegroundColor Green
    Write-Host 'Development builds do not create a distributable installer.' -ForegroundColor Yellow
}
