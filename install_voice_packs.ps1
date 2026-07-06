param(
    [Parameter(Mandatory = $true)]
    [string]$LocaleList
)

$ErrorActionPreference = 'Stop'

foreach ($locale in $LocaleList.Split(',')) {
    Write-Host "Installing Windows speech components for $locale ..." -ForegroundColor Cyan
    Add-WindowsCapability -Online -Name "Language.Basic~~~$locale~0.0.1.0" | Out-Host
    Add-WindowsCapability -Online -Name "Language.TextToSpeech~~~$locale~0.0.1.0" | Out-Host
}

Write-Host 'Installation complete. Restart RemotePlus Translator.' -ForegroundColor Green
Read-Host 'Press Enter to close'
