param(
    [string]$Executable = ".\dist\RemotePlusTranslator\RemotePlusTranslator.exe",
    [string]$OutputDirectory = ".\docs\manual_ja"
)

$ErrorActionPreference = "Stop"
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
$edge = Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path -LiteralPath $edge)) {
    throw "Microsoft Edge was not found."
}
if (@(Get-Process -Name "RemotePlusTranslator", "llama-server" `
        -ErrorAction SilentlyContinue).Count) {
    throw "Close RemotePlus before capturing the manual screens."
}

$env:REMOTEPLUS_DATA_DIR = Join-Path $env:TEMP "RemotePlusManual-$PID"
try {
    Start-Process -FilePath $Executable -WorkingDirectory (Split-Path $Executable) |
        Out-Null
    $deadline = (Get-Date).AddSeconds(40)
    do {
        Start-Sleep -Milliseconds 250
        $front = Get-Process -Name "RemotePlusTranslator" -ErrorAction SilentlyContinue |
            Where-Object MainWindowTitle -EQ "RemotePlus Translator" |
            Select-Object -First 1
        $backend = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    } while ((-not $front -or -not $backend) -and (Get-Date) -lt $deadline)
    if (-not $front -or -not $backend) {
        throw "RemotePlus did not become ready."
    }

    $main = Join-Path $OutputDirectory "ui-main.png"
    & $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,1000 `
        --screenshot=$main "http://127.0.0.1:8765/"
    if (-not (Test-Path -LiteralPath $main) -or (Get-Item $main).Length -lt 10000) {
        throw "The main UI screenshot failed."
    }

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/" `
        -WebSession $session -TimeoutSec 5 | Out-Null
    Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:8765/api/control" -WebSession $session `
        -ContentType "application/json" -Body '{"active_language":"ko"}' `
        -TimeoutSec 5 | Out-Null
    Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:8765/api/reply" -WebSession $session `
        -ContentType "application/json" `
        -Body '{"text":"Please wait while I confirm the details."}' `
        -TimeoutSec 5 | Out-Null
    Start-Sleep -Seconds 4

    $conversation = Join-Path $OutputDirectory "ui-conversation.png"
    & $edge --headless=new --disable-gpu --hide-scrollbars --window-size=1440,1000 `
        --screenshot=$conversation "http://127.0.0.1:8765/"
    if (-not (Test-Path -LiteralPath $conversation) -or `
        (Get-Item $conversation).Length -lt 10000) {
        throw "The conversation UI screenshot failed."
    }
    [pscustomobject]@{ Main = $main; Conversation = $conversation } | ConvertTo-Json
} finally {
    Remove-Item Env:\REMOTEPLUS_DATA_DIR -ErrorAction SilentlyContinue
    $front = Get-Process -Name "RemotePlusTranslator" -ErrorAction SilentlyContinue |
        Where-Object MainWindowTitle -EQ "RemotePlus Translator" |
        Select-Object -First 1
    if ($front) {
        $front.CloseMainWindow() | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = @(Get-Process -Name "RemotePlusTranslator", "llama-server" `
            -ErrorAction SilentlyContinue)
    } while ($remaining.Count -and (Get-Date) -lt $deadline)
    if ($remaining.Count) {
        $remaining | Stop-Process -Force
    }
}
