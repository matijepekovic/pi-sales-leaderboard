#define MyAppName "Stats"
#define MyAppPublisher "Stats"
#define MyAppExeName "StatsLauncher.exe"
#ifndef MyAppVersion
  #define MyAppVersion GetEnv("STATS_VERSION")
#endif

[Setup]
AppId={{6E12138A-14A6-4EA8-B0AD-87C3096ACF91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Stats
DefaultGroupName=Stats
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\installer-output
OutputBaseFilename=Stats-Setup-{#MyAppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Stats Windows Installer

[Tasks]
Name: "startup"; Description: "Start Stats automatically when I sign in"; GroupDescription: "Startup:"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\StatsLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\StatsUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\StatsServer\*"; DestDir: "{app}\server"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Stats\Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startup
Name: "{userdesktop}\Stats"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Stats"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM StatsLauncher.exe /T /F >NUL 2>&1"; Flags: runhidden; RunOnceId: "StopLauncher"
Filename: "{cmd}"; Parameters: "/C taskkill /IM StatsServer.exe /T /F >NUL 2>&1"; Flags: runhidden; RunOnceId: "StopServer"

[Code]
procedure StopStatsProcesses();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM StatsLauncher.exe /T /F >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM StatsServer.exe /T /F >NUL 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopStatsProcesses();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    DeleteFile(ExpandConstant('{userstartup}\Stats.lnk'));
    StopStatsProcesses();
  end;
end;
