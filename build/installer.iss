#define MyAppName "RemotePlus Translator"
#define MyAppVersion "0.6.0"
#define MyAppExeName "RemotePlusTranslator.exe"

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
PrivilegesRequired=lowest
WizardStyle=modern
LicenseFile=..\EULA_JA.md
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Files]
Source: "..\dist\RemotePlusTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로가기 만들기"; GroupDescription: "바로가기"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "RemotePlus Translator 실행"; Flags: nowait postinstall skipifsilent
