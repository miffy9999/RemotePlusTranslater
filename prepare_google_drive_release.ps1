param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [int]$ChunkSizeMiB = 90
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$resolvedZip = (Resolve-Path -LiteralPath $ZipPath).Path
$zipFile = Get-Item -LiteralPath $resolvedZip
if ($zipFile.Extension -ne '.zip') {
    throw 'ZipPath must point to the finished RemotePlus ZIP file.'
}
if ($ChunkSizeMiB -lt 32 -or $ChunkSizeMiB -gt 96) {
    throw 'ChunkSizeMiB must be between 32 and 96 for the Google Drive connector.'
}

$outputRoot = Join-Path $PSScriptRoot "dist\google-drive\$($zipFile.BaseName)"
Remove-Item -LiteralPath $outputRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$chunkSize = [int64]$ChunkSizeMiB * 1MB
$buffer = New-Object byte[] (4MB)
$parts = [System.Collections.Generic.List[object]]::new()
$source = [IO.File]::OpenRead($resolvedZip)
try {
    $partNumber = 0
    while ($source.Position -lt $source.Length) {
        $partNumber++
        $partName = "RemotePlusTranslator.package.part{0:D2}.bin" -f $partNumber
        $partPath = Join-Path $outputRoot $partName
        $remainingInPart = [Math]::Min($chunkSize, $source.Length - $source.Position)
        $target = [IO.File]::Create($partPath)
        try {
            while ($remainingInPart -gt 0) {
                $readSize = [int][Math]::Min($buffer.Length, $remainingInPart)
                $read = $source.Read($buffer, 0, $readSize)
                if ($read -le 0) { throw 'Unexpected end of the source ZIP.' }
                $target.Write($buffer, 0, $read)
                $remainingInPart -= $read
            }
        } finally {
            $target.Dispose()
        }
        $partFile = Get-Item -LiteralPath $partPath
        $parts.Add([ordered]@{
            name = $partName
            length = $partFile.Length
            sha256 = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    }
} finally {
    $source.Dispose()
}

$info = [ordered]@{
    schema_version = 1
    archive_name = $zipFile.Name
    archive_length = $zipFile.Length
    archive_sha256 = (Get-FileHash -LiteralPath $resolvedZip -Algorithm SHA256).Hash.ToLowerInvariant()
    parts = @($parts)
}
$info | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $outputRoot 'download-info.json') -Encoding UTF8
Copy-Item -LiteralPath '.\build\internal\GoogleDrive-Setup.ps1' -Destination $outputRoot -Force
Copy-Item -LiteralPath '.\build\internal\START_RemotePlus_Install.cmd' -Destination $outputRoot -Force
Copy-Item -LiteralPath '.\build\internal\GOOGLE_DRIVE_README_JA.txt' -Destination $outputRoot -Force

Write-Host "Google Drive release prepared: $outputRoot" -ForegroundColor Green
Write-Host "Parts: $($parts.Count)" -ForegroundColor Cyan
