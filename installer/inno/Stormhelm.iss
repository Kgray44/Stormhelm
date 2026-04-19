; Stormhelm Windows installer scaffold.
; Compile with:
;   ISCC.exe /DMyAppVersion=0.1.1 /DSourceDir="C:\path\to\release\portable\Stormhelm-0.1.1-windows-x64" installer\inno\Stormhelm.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.1.1"
#endif

#ifndef SourceDir
  #define SourceDir "..\..\release\portable\Stormhelm-0.1.1-windows-x64"
#endif

[Setup]
AppName=Stormhelm
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Stormhelm
DefaultGroupName=Stormhelm
UninstallDisplayIcon={app}\stormhelm-ui.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
OutputDir=..\Output
OutputBaseFilename=Stormhelm-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Stormhelm"; Filename: "{app}\stormhelm-ui.exe"
Name: "{group}\Uninstall Stormhelm"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Stormhelm"; Filename: "{app}\stormhelm-ui.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "startupplaceholder"; Description: "Startup with Windows (planned for a later phase)"; Flags: unchecked

[Run]
Filename: "{app}\stormhelm-ui.exe"; Description: "Launch Stormhelm"; Flags: nowait postinstall skipifsilent
