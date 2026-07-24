#define MyAppName "RemotePlus Translator"
#ifndef MyAppVersion
#define MyAppVersion "0.8.4"
#endif
#define MyAppExeName "RemotePlusTranslator.exe"
#define WebView2InstallerName "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"

[Setup]
AppId={{D0354E08-4A89-4BAE-B90F-66E2F15ED241}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\RemotePlus Translator
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer
OutputBaseFilename=RemotePlusTranslator-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Commercial hotel deployment belongs under IT-managed Program Files.
PrivilegesRequired=admin
WizardStyle=modern
; Use the rendered release document, never the source template containing placeholders.
LicenseFile=..\dist\RemotePlusTranslator\EULA_JA.md
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Files]
Source: "..\dist\RemotePlusTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\redist\{#WebView2InstallerName}"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "바로가기"

[Run]
Filename: "{tmp}\{#WebView2InstallerName}"; Parameters: "/silent /install"; StatusMsg: "Microsoft Edge WebView2 Runtime 설치 중..."; Flags: waituntilterminated runhidden; Check: not HasWebView2Runtime
Filename: "{app}\{#MyAppExeName}"; Description: "RemotePlus Translator 실행"; Flags: nowait postinstall skipifsilent; Check: HasWebView2Runtime

[Code]
const
  WebView2MachineKey = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2UserKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWebView2Runtime(): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM, WebView2MachineKey, 'pv', Version);
  if not Result then
    Result := RegQueryStringValue(HKCU, WebView2UserKey, 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;
