; Inno Setup 6 script for the Fernal installer. Build it with packaging\build.py (PyInstaller first, then ISCC);
; paths below are relative to this file. Saved as UTF-8 with a BOM so the Korean strings read correctly.

[Setup]
; Never change AppId: it identifies the install for upgrades and for the uninstall entry.
AppId={{51848C6E-0883-4D37-9E07-A78DFD6A9A3F}
AppName=Fernal
AppVersion=1.0.0
AppPublisher=Fernal
DefaultDirName={autopf}\Fernal
DefaultGroupName=Fernal
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt); the dialog lets the user choose an all-users install instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=fernal.ico
UninstallDisplayIcon={app}\Fernal.exe
CloseApplications=yes
OutputDir=Output
OutputBaseFilename=Fernal-Setup-1.0.0

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.TaskDesktopIcon=Create a &desktop shortcut
korean.TaskDesktopIcon=바탕 화면에 바로 가기 만들기(&D)
english.TaskAutoStart=Start Fernal when &Windows starts
korean.TaskAutoStart=&Windows를 시작할 때 Fernal 자동 실행

[Tasks]
; Both are off by default.
Name: "desktopicon"; Description: "{cm:TaskDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:TaskAutoStart}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The PyInstaller onedir output (Fernal.exe and _internal\).
Source: "..\dist\Fernal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Fernal"; Filename: "{app}\Fernal.exe"
Name: "{group}\{cm:UninstallProgram,Fernal}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Fernal"; Filename: "{app}\Fernal.exe"; Tasks: desktopicon
Name: "{userstartup}\Fernal"; Filename: "{app}\Fernal.exe"; Tasks: autostart

[Run]
Filename: "{app}\Fernal.exe"; Description: "{cm:LaunchProgram,Fernal}"; Flags: nowait postinstall skipifsilent

; The uninstaller removes only what Setup installed: the program files, the shortcuts and the uninstall entry.
; The plant's saved state lives in %APPDATA%\Fernal and is deliberately not listed in [UninstallDelete], so
; uninstalling and reinstalling keeps the plant.
