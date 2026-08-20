param(
    [string]$Executable = ".\dist\RemotePlusTranslator\RemotePlusTranslator.exe"
)

$ErrorActionPreference = "Stop"
$Executable = (Resolve-Path -LiteralPath $Executable).Path

if (@(Get-Process -Name "RemotePlusTranslator", "llama-server" `
        -ErrorAction SilentlyContinue).Count) {
    throw "Close existing RemotePlus processes before running the stress test."
}

function Wait-Frontend([int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        Start-Sleep -Milliseconds 250
        $front = Get-Process -Name "RemotePlusTranslator" -ErrorAction SilentlyContinue |
            Where-Object MainWindowTitle -EQ "RemotePlus Translator" |
            Select-Object -First 1
    } while ((-not $front) -and (Get-Date) -lt $deadline)
    return $front
}

function Wait-Clean([int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = @(Get-Process -Name "RemotePlusTranslator", "llama-server" `
            -ErrorAction SilentlyContinue)
    } while ($remaining.Count -and (Get-Date) -lt $deadline)
    if ($remaining.Count) {
        $remaining | Stop-Process -Force
        throw "Backend process leak: $($remaining.Count) process(es)."
    }
}

function Start-TestApp([string]$DataRoot) {
    $env:REMOTEPLUS_DATA_DIR = $DataRoot
    Start-Process -FilePath $Executable -WorkingDirectory (Split-Path $Executable) |
        Out-Null
    $front = Wait-Frontend
    if (-not $front) {
        throw "Frontend did not start."
    }
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/" `
        -WebSession $session -TimeoutSec 5 | Out-Null
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 250
        $state = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/state" `
            -WebSession $session -TimeoutSec 5
    } while ($state.state.phase -notin @("listening", "paused") -and `
        (Get-Date) -lt $deadline)
    if ($state.state.phase -notin @("listening", "paused")) {
        throw "Backend did not become ready: $($state.state.phase)"
    }
    $control = @{ active_language = "ko" } | ConvertTo-Json
    Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:8765/api/control" -WebSession $session `
        -ContentType "application/json; charset=utf-8" -Body $control -TimeoutSec 5 |
        Out-Null
    return [pscustomobject]@{ Front = $front; Session = $session }
}

$results = @()
try {
    $dataRoot = Join-Path $env:TEMP "RemotePlusStress-backend-crash-$PID"
    $app = Start-TestApp $dataRoot
    $old = Get-Process -Name "llama-server" -ErrorAction Stop |
        Select-Object -First 1
    Stop-Process -Id $old.Id -Force
    $payload = @{ text = "The staff will review every detail and contact you shortly." } |
        ConvertTo-Json
    Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:8765/api/reply" -WebSession $app.Session `
        -ContentType "application/json; charset=utf-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 5 | Out-Null
    $deadline = (Get-Date).AddSeconds(35)
    do {
        Start-Sleep -Milliseconds 250
        $new = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue |
            Where-Object Id -NE $old.Id | Select-Object -First 1
    } while ((-not $new) -and (Get-Date) -lt $deadline)
    if (-not $new) {
        throw "Translation backend did not restart after forced termination."
    }
    if ($new.MainWindowHandle -ne 0) {
        throw "Restarted backend exposed a console window."
    }
    $app.Front.CloseMainWindow() | Out-Null
    Wait-Clean
    $results += [pscustomobject]@{
        Scenario = "backend-forced-kill-restart"
        Result = "PASS"
        OldPid = $old.Id
        NewPid = $new.Id
    }

    $dataRoot = Join-Path $env:TEMP "RemotePlusStress-active-close-$PID"
    $app = Start-TestApp $dataRoot
    $payload = @{
        text = "We will review the details, complete every arrangement, and contact you tomorrow."
    } | ConvertTo-Json
    Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "http://127.0.0.1:8765/api/reply" -WebSession $app.Session `
        -ContentType "application/json; charset=utf-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 5 | Out-Null
    $deadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 100
        $state = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/state" `
            -WebSession $app.Session -TimeoutSec 3
    } while ($state.state.phase -ne "translating" -and (Get-Date) -lt $deadline)
    $startedAt = Get-Date
    $app.Front.CloseMainWindow() | Out-Null
    Wait-Clean 15
    $elapsed = ((Get-Date) - $startedAt).TotalSeconds
    $results += [pscustomobject]@{
        Scenario = "close-during-translation"
        Result = "PASS"
        ObservedPhase = $state.state.phase
        ShutdownSeconds = [math]::Round($elapsed, 2)
    }
} finally {
    Remove-Item Env:\REMOTEPLUS_DATA_DIR -ErrorAction SilentlyContinue
    $remaining = @(Get-Process -Name "RemotePlusTranslator", "llama-server" `
        -ErrorAction SilentlyContinue)
    if ($remaining.Count) {
        $remaining | Stop-Process -Force
    }
}

$results | ConvertTo-Json
