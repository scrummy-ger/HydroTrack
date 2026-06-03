[Setup]
AppId={{HydroTrackApp}}
AppName=HydroTrack
AppVersion=1.0.1
AppPublisher=Daniel Siepmann
DefaultDirName={autopf}\HydroTrack
DefaultGroupName=HydroTrack
OutputBaseFilename=HydroTrack_Setup
OutputDir=output
Compression=lzma
SolidCompression=yes
SetupIconFile=HydroTrack.ico
UninstallDisplayIcon={app}\HydroTrack.exe

VersionInfoVersion=1.0.0.1
VersionInfoCompany=DS Development
VersionInfoDescription=HydroTrack

WizardStyle=modern
WizardSmallImageFile=HydroTrack_Small.bmp

DisableDirPage=no
DisableProgramGroupPage=yes

[Files]
Source: "dist\HydroTrack.exe"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; Flags: unchecked
Name: "autostart"; Description: "Mit Windows starten"; Flags: unchecked

[Icons]
Name: "{group}\HydroTrack"; Filename: "{app}\HydroTrack.exe"
Name: "{group}\HydroTrack deinstallieren"; Filename: "{uninstallexe}"
Name: "{userdesktop}\HydroTrack"; Filename: "{app}\HydroTrack.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HydroTrack.exe"; Description: "HydroTrack starten"; Flags: nowait postinstall skipifsilent

[Registry]
; Autostart (optional)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
ValueType: string; ValueName: "HydroTrack"; \
ValueData: "{app}\HydroTrack.exe"; Tasks: autostart; Flags: uninsdeletevalue

[UninstallDelete]
; Falls du später Logs oder Daten hast (optional)
Type: files; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\data"
