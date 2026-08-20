param(
    [Parameter(Mandatory = $true)][string]$RemoteHost,
    [string]$RemoteUser = 'remoteplus',
    [ValidateRange(1, 65535)][int]$Port = 22,
    [Parameter(Mandatory = $true)][string]$IdentityFile,
    [ValidateSet('stable', 'beta')][string]$Channel = 'stable',
    [string]$ReleaseRoot = '.\dist\vps-release'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($RemoteHost -notmatch '^[A-Za-z0-9.-]+$' -or $RemoteHost.StartsWith('-')) {
    throw 'RemoteHost must be a hostname or IPv4 address without shell characters.'
}
if ($RemoteUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw 'RemoteUser contains unsupported characters.'
}
$identity = (Resolve-Path -LiteralPath $IdentityFile).Path
$release = (Resolve-Path -LiteralPath $ReleaseRoot).Path
foreach ($required in @(
    "channels\$Channel\manifest.json",
    'site\index.html',
    'ops\activate_release.sh',
    'ops\check_capacity.sh'
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $release $required))) {
        throw "Release bundle file is missing: $required"
    }
}
$placeholder = Get-ChildItem -LiteralPath $release -File -Recurse |
    Where-Object { $_.Extension -in @('.html', '.json', '.sh') -or $_.Name -eq 'Caddyfile' } |
    Select-String -Pattern '(_HERE\b|\bREPLACE(_|\s+WITH\b))' -CaseSensitive:$false
if ($placeholder) {
    throw "Release bundle contains deployment placeholders: $($placeholder[0].FullName)"
}

$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$scp = (Get-Command scp.exe -ErrorAction Stop).Source
$tar = (Get-Command tar.exe -ErrorAction Stop).Source
$deploymentId = "remoteplus-$([DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss'))-$PID"
$remoteArchive = "/tmp/$deploymentId.tar.gz"
$remoteStage = "/tmp/$deploymentId"
$localArchive = Join-Path ([IO.Path]::GetTempPath()) "$deploymentId.tar.gz"
$target = "$RemoteUser@$RemoteHost"
$sshBase = @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-p', "$Port", '-i', $identity)
$scpBase = @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-P', "$Port", '-i', $identity)
$remoteCleanupNeeded = $false

try {
    & $tar '-czf' $localArchive '-C' $release '.'
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the release archive.' }
    & $scp @scpBase $localArchive "${target}:$remoteArchive"
    $remoteCleanupNeeded = $true
    if ($LASTEXITCODE -ne 0) { throw 'Could not upload the release archive.' }
    $activate = "set -eu; mkdir '$remoteStage'; tar -xzf '$remoteArchive' -C '$remoteStage'; " +
        "sh '$remoteStage/ops/check_capacity.sh' --strict; " +
        "sh '$remoteStage/ops/activate_release.sh' '$remoteStage' '$Channel' /srv/remoteplus"
    & $ssh @sshBase $target $activate
    if ($LASTEXITCODE -ne 0) { throw 'Remote preflight or activation failed.' }
    Write-Host "RemotePlus $Channel release activated on $RemoteHost." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $localArchive -Force -ErrorAction SilentlyContinue
    if ($remoteCleanupNeeded) {
        $cleanup = "rm -rf '$remoteStage' '$remoteArchive'"
        & $ssh @sshBase $target $cleanup 2>$null
    }
}
