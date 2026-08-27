#define MyAppName "Tablou Stats"
#define MyAppPublisher "Tablou"
#define MyAppExeName "TablouStatsLauncher.exe"
#ifndef MyAppVersion
  #define MyAppVersion GetEnv("TABLOU_VERSION")
#endif

[Setup]
AppId={{A9D8AF67-7422-4F1C-B663-EE1699B7D412}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Tablou Stats
DefaultGroupName=Tablou Stats
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\installer-output
OutputBaseFilename=Tablou-Stats-Setup-{#MyAppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Tablou Stats Windows Installer

[Tasks]
Name: "startup"; Description: "Start Tablou Stats automatically when I sign in"; GroupDescription: "Startup:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\TablouStatsLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\TablouStatsServer\*"; DestDir: "{app}\server"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Tablou Stats\Tablou Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\Tablou Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startup
Name: "{userdesktop}\Tablou Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Tablou Stats"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM TablouStatsLauncher.exe /T /F >NUL 2>&1"; Flags: runhidden; RunOnceId: "StopLauncher"
Filename: "{cmd}"; Parameters: "/C taskkill /IM TablouStatsServer.exe /T /F >NUL 2>&1"; Flags: runhidden; RunOnceId: "StopServer"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Stop an older installed copy before replacing binaries during an upgrade. }
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM TablouStatsLauncher.exe /T /F >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM TablouStatsServer.exe /T /F >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
