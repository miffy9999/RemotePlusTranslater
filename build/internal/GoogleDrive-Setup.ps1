param(
    [switch]$VerifyOnly,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

function Assert-PathUnderTemp([string]$Path) {
    $resolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not ($resolvedPath + '\').StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe temporary path: $resolvedPath"
    }
}

try {
    $downloadRoot = Split-Path -Parent $PSCommandPath
    $infoPath = Join-Path $downloadRoot 'download-info.json'
    if (-not (Test-Path -LiteralPath $infoPath -PathType Leaf)) {
        throw 'download-info.json is missing.'
    }
    $info = Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$info.schema_version -ne 1 -or @($info.parts).Count -lt 2) {
        throw 'The RemotePlus download information is invalid.'
    }

    $workRoot = Join-Path ([IO.Path]::GetTempPath()) 'RemotePlusTranslator-Download'
    Assert-PathUnderTemp $workRoot
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    $archivePath = Join-Path $workRoot ([string]$info.archive_name)

    $target = [IO.File]::Create($archivePath)
    try {
        foreach ($part in $info.parts) {
            $partName = [string]$part.name
            if ($partName -notmatch '^RemotePlusTranslator\.package\.part\d{2}\.bin$') {
                throw "Invalid package part name: $partName"
            }
            $partPath = Join-Path $downloadRoot $partName
            if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
                throw "Download file is missing: $partName"
            }
            $partFile = Get-Item -LiteralPath $partPath
            if ($partFile.Length -ne [long]$part.length) {
                throw "Download file size mismatch: $partName"
            }
            $partHash = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($partHash -ne [string]$part.sha256) {
                throw "Download file is damaged: $partName"
            }
            $source = [IO.File]::OpenRead($partPath)
            try {
                $source.CopyTo($target)
            } finally {
                $source.Dispose()
            }
        }
    } finally {
        $target.Dispose()
    }

    $archiveFile = Get-Item -LiteralPath $archivePath
    if ($archiveFile.Length -ne [long]$info.archive_length) {
        throw 'The reconstructed RemotePlus ZIP has the wrong size.'
    }
    $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($archiveHash -ne [string]$info.archive_sha256) {
        throw 'The reconstructed RemotePlus ZIP is damaged.'
    }
    if ($VerifyOnly) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
        Write-Output 'GOOGLE_DRIVE_PACKAGE_VERIFY_OK'
        return
    }

    $extractRoot = Join-Path $workRoot 'extracted'
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force
    $installers = @(
        Get-ChildItem -LiteralPath $extractRoot -Recurse -File -Filter 'Install_RemotePlus.cmd'
    )
    if ($installers.Count -ne 1) {
        throw "Expected one RemotePlus installer; found $($installers.Count)."
    }
    $process = Start-Process -FilePath $installers[0].FullName `
        -WorkingDirectory $installers[0].DirectoryName -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "RemotePlus installation failed with exit code $($process.ExitCode)."
    }
    Remove-Item -LiteralPath $workRoot -Recurse -Force
} catch {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    if (-not $NonInteractive -and ('System.Windows.Forms.MessageBox' -as [type])) {
        $message = "RemotePlus download or installation failed.`n`n$($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show($message, 'RemotePlus', 'OK', 'Error') |
            Out-Null
    }
    throw
}
