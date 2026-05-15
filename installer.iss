[Setup]
AppName=StreamSwitcher Pro
AppVersion=1.0.0
AppPublisher=StreamSwitcher
DefaultDirName={autopf}\StreamSwitcher
DefaultGroupName=StreamSwitcher Pro
OutputDir=Output
OutputBaseFilename=StreamSwitcher_Setup
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\StreamSwitcher.exe
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\StreamSwitcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\StreamSwitcher Pro"; Filename: "{app}\StreamSwitcher.exe"
Name: "{autodesktop}\StreamSwitcher Pro"; Filename: "{app}\StreamSwitcher.exe"

[Run]
Filename: "{app}\StreamSwitcher.exe"; Flags: nowait postinstall skipifsilent
