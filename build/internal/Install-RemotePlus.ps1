param(
    [switch]$NoLaunch,
    [switch]$NoShortcuts,
    [switch]$NonInteractive,
    [string]$InstallDirectoryName = 'RemotePlus Translator'
)

$ErrorActionPreference = 'Stop'

if ($InstallDirectoryName -notmatch '^RemotePlus Translator(?: QA)?$') {
    throw 'Invalid RemotePlus installation directory name.'
}

function Write-InstallLog([string]$Message) {
    $logDirectory = Join-Path $env:LOCALAPPDATA 'RemotePlusTranslator'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $line = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] $Message"
    Add-Content -LiteralPath (Join-Path $logDirectory 'install.log') -Value $line -Encoding UTF8
}

function Assert-PathUnder([string]$Path, [string]$AllowedRoot) {
    $resolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $resolvedRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
    if (-not ($resolvedPath + '\').StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe installation path: $resolvedPath"
    }
}

try {
    $releaseRoot = Split-Path -Parent $PSCommandPath
    $infoPath = Join-Path $releaseRoot 'release-info.json'
    $manifestPath = Join-Path $releaseRoot 'release-manifest.json'
    $certificatePath = Join-Path $releaseRoot 'RemotePlus-Internal-Code-Signing.cer'
    foreach ($required in @($infoPath, $manifestPath, $certificatePath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Installation file is missing: $required"
        }
    }

    $info = Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($info.publisher -ne 'RemotePlus' -or $manifest.publisher -ne 'RemotePlus') {
        throw 'The package publisher is not RemotePlus.'
    }

    $certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
        $certificatePath
    )
    $expectedThumbprint = ([string]$info.certificate_thumbprint).Replace(' ', '').ToUpperInvariant()
    if ($certificate.Thumbprint -ne $expectedThumbprint -or
        $manifest.certificate_thumbprint -ne $expectedThumbprint) {
        throw 'The package certificate fingerprint does not match its release information.'
    }
    if ($certificate.NotAfter -lt (Get-Date).AddDays(30)) {
        throw 'The RemotePlus internal certificate is expired or expires too soon.'
    }

    foreach ($storeName in @('Root', 'TrustedPublisher')) {
        $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
            $storeName,
            [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
        )
        try {
            $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
            if (-not ($store.Certificates | Where-Object Thumbprint -eq $expectedThumbprint)) {
                $store.Add($certificate)
            }
        } finally {
            $store.Close()
        }
    }
    Write-InstallLog "Trusted RemotePlus publisher certificate $expectedThumbprint"

    $sourceRoot = Join-Path $releaseRoot ([string]$info.app_directory)
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
        throw 'The RemotePlusTranslator application folder is missing.'
    }
    $expectedPaths = @{}
    foreach ($item in $manifest.files) {
        $relativePath = ([string]$item.path).Replace('/', '\')
        if ([IO.Path]::IsPathRooted($relativePath) -or $relativePath.Contains('..')) {
            throw "Unsafe manifest path: $relativePath"
        }
        $manifestKey = $relativePath.ToLowerInvariant()
        if ($expectedPaths.ContainsKey($manifestKey)) {
            throw "Duplicate manifest path: $relativePath"
        }
        $expectedPaths[$manifestKey] = $true
        $filePath = Join-Path $sourceRoot $relativePath
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            throw "Package file is missing: $relativePath"
        }
        $file = Get-Item -LiteralPath $filePath
        if ($file.Length -ne [long]$item.length) {
            throw "Package file size mismatch: $relativePath"
        }
        $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne [string]$item.sha256) {
            throw "Package file hash mismatch: $relativePath"
        }
    }
    $actualFiles = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File)
    if ($actualFiles.Count -ne $expectedPaths.Count) {
        throw 'The application folder contains missing or unexpected files.'
    }
    foreach ($actualFile in $actualFiles) {
        $relativePath = $actualFile.FullName.Substring($sourceRoot.TrimEnd('\').Length + 1)
        if (-not $expectedPaths.ContainsKey($relativePath.ToLowerInvariant())) {
            throw "Unexpected package file: $relativePath"
        }
    }

    foreach ($relativePath in $info.signed_entrypoints) {
        $filePath = Join-Path $sourceRoot ([string]$relativePath).Replace('/', '\')
        $signature = Get-AuthenticodeSignature -LiteralPath $filePath
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Thumbprint -ne $expectedThumbprint) {
            throw "RemotePlus signature verification failed: $relativePath ($($signature.Status))"
        }
    }

    Get-ChildItem -LiteralPath $releaseRoot -Recurse -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue

    $programsRoot = Join-Path $env:LOCALAPPDATA 'Programs'
    $installRoot = Join-Path $programsRoot $InstallDirectoryName
    $stagingRoot = "$installRoot.new"
    $backupRoot = "$installRoot.previous"
    foreach ($path in @($installRoot, $stagingRoot, $backupRoot)) {
        Assert-PathUnder $path $programsRoot
    }
    New-Item -ItemType Directory -Path $programsRoot -Force | Out-Null

    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and $_.Path.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)
            } catch {
                $false
            }
        } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $sourceRoot -Destination $stagingRoot -Recurse -Force

    foreach ($relativePath in $info.signed_entrypoints) {
        $filePath = Join-Path $stagingRoot ([string]$relativePath).Replace('/', '\')
        $signature = Get-AuthenticodeSignature -LiteralPath $filePath
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Thumbprint -ne $expectedThumbprint) {
            throw "Installed file signature verification failed: $relativePath"
        }
    }

    Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $installRoot) {
        Move-Item -LiteralPath $installRoot -Destination $backupRoot
    }
    try {
        Move-Item -LiteralPath $stagingRoot -Destination $installRoot
    } catch {
        if ((Test-Path -LiteralPath $backupRoot) -and -not (Test-Path -LiteralPath $installRoot)) {
            Move-Item -LiteralPath $backupRoot -Destination $installRoot
        }
        throw
    }

    $appExe = Join-Path $installRoot 'RemotePlusTranslator.exe'
    if (-not $NoShortcuts) {
        $shell = New-Object -ComObject WScript.Shell
        $desktopShortcut = $shell.CreateShortcut(
            (Join-Path ([Environment]::GetFolderPath('Desktop')) 'RemotePlus Translator.lnk')
        )
        $desktopShortcut.TargetPath = $appExe
        $desktopShortcut.WorkingDirectory = $installRoot
        $desktopShortcut.IconLocation = "$appExe,0"
        $desktopShortcut.Save()

        $startMenuDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
        New-Item -ItemType Directory -Path $startMenuDirectory -Force | Out-Null
        $startMenuShortcut = $shell.CreateShortcut(
            (Join-Path $startMenuDirectory 'RemotePlus Translator.lnk')
        )
        $startMenuShortcut.TargetPath = $appExe
        $startMenuShortcut.WorkingDirectory = $installRoot
        $startMenuShortcut.IconLocation = "$appExe,0"
        $startMenuShortcut.Save()
    }

    Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-InstallLog "Installed RemotePlus Translator $($info.version) to $installRoot"
    if (-not $NoLaunch) {
        Start-Process -FilePath $appExe -WorkingDirectory $installRoot
    }

    if (-not $NonInteractive) {
        Add-Type -AssemblyName System.Windows.Forms
        $message = "RemotePlus Translator $($info.version) installation is complete."
        [System.Windows.Forms.MessageBox]::Show($message, 'RemotePlus', 'OK', 'Information') |
            Out-Null
    }
} catch {
    Write-InstallLog "ERROR: $($_.Exception.Message)"
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    if (-not $NonInteractive -and ('System.Windows.Forms.MessageBox' -as [type])) {
        $message = "RemotePlus Translator could not be installed.`n`n$($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($message, 'RemotePlus', 'OK', 'Error') |
            Out-Null
    }
    throw
}
