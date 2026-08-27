#define MyAppName "Stats"
#define MyAppPublisher "Stats"
#define MyAppExeName "StatsLauncher.exe"
#ifndef MyAppVersion
  #define MyAppVersion GetEnv("STATS_VERSION")
#endif

[Setup]
AppId={{A9D8AF67-7422-4F1C-B663-EE1699B7D412}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Stats
UsePreviousAppDir=no
DefaultGroupName=Stats
UsePreviousGroup=no
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
function LegacyBrand(): String;
begin
  { Build the retired product prefix without carrying it in current branding. }
  Result := Chr(84) + Chr(97) + Chr(98) + Chr(108) + Chr(111);
end;

procedure StopImage(const ImageName: String);
var
  ResultCode: Integer;
begin
  Exec(
    ExpandConstant('{cmd}'),
    '/C taskkill /IM "' + ImageName + '" /T /F >NUL 2>&1',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode
  );
end;

procedure StopStatsProcesses();
begin
  StopImage('StatsLauncher.exe');
  StopImage('StatsServer.exe');
  { Also stop the 1.0.0 process names during the one-time rename migration. }
  StopImage(LegacyBrand() + 'StatsLauncher.exe');
  StopImage(LegacyBrand() + 'StatsServer.exe');
end;

procedure RemoveLegacyInstall();
var
  LegacyName: String;
  LegacyDir: String;
begin
  LegacyName := LegacyBrand() + ' Stats';
  DeleteFile(ExpandConstant('{userstartup}\') + LegacyName + '.lnk');
  DeleteFile(ExpandConstant('{userdesktop}\') + LegacyName + '.lnk');
  DelTree(ExpandConstant('{userprograms}\') + LegacyName, True, True, True);

  LegacyDir := ExpandConstant('{localappdata}\Programs\') + LegacyName;
  if DirExists(LegacyDir) then
    DelTree(LegacyDir, True, True, True);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { Stop both the current Stats processes and the 1.0.0 processes before upgrade. }
  StopStatsProcesses();
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveLegacyInstall();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopStatsProcesses();
end;
