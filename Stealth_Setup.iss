#define MyAppName "Stealth."
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Stealth."
#define MyAppExeName "Stealth.exe"

[Setup]
AppId={{8E4A2D6F-9B53-4C2C-A8D8-3B66D9F041B7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Stealth.
DefaultGroupName=Stealth.
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Stealth_Setup
SetupIconFile=minecraft_instance.ico
UninstallDisplayIcon={app}\minecraft_instance.ico
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut for Stealth."; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "dist\Stealth.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "minecraft_instance.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Stealth."; Filename: "{app}\Stealth.exe"; WorkingDir: "{app}"; IconFilename: "{app}\minecraft_instance.ico"
Name: "{autodesktop}\Stealth."; Filename: "{app}\Stealth.exe"; WorkingDir: "{app}"; IconFilename: "{app}\minecraft_instance.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Stealth.exe"; Description: "Launch Stealth."; Flags: postinstall nowait skipifsilent
