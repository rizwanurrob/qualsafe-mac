; QualSafe Web -- Inno Setup script
;
;   python packaging/build_payload_web.py
;   iscc packaging\qualsafe_web.iss /DAppVersion=4.13.0-ux3
;
; Produces  build\QualSafe-Web-<version>-Setup.exe : one file, no admin rights, no Python required on the
; target machine. It installs the WEB app (Streamlit) only; the desktop app is a separate installer
; (qualsafe.iss), which carries no web server.
;
; Requires Inno Setup 6:  https://jrsoftware.org/isdl.php
;
; Design decisions, the same as the desktop installer's:
;   * PER-USER INSTALL (PrivilegesRequired=lowest): no UAC prompt, no IT call.
;   * THE UNINSTALLER REMOVES THE PROGRAM AND NOTHING ELSE. Settings and saved progress live in
;     %LOCALAPPDATA%\QualSafe Web; coded projects and run outputs live in {app}\output_streamlit, and the
;     samples folder {app}\data may hold the researcher's own files, so neither is deleted.
;   * APPID IS FIXED FOREVER: it is how Windows tells an upgrade from a second copy.
;
; What it runs: `launch_web.py` starts the app on this computer only (127.0.0.1, the first free port from
; 8501) and opens it in the browser; running it again opens the page that is already running.

#ifndef AppVersion
  #define AppVersion "4.13.0"
#endif

; A pre-release label ("4.13.0-ux3") is allowed in the visible version; the Windows file-version field must
; be numeric, so it gets the part before the dash.
#if Pos("-", AppVersion) > 0
  #define AppNumeric Copy(AppVersion, 1, Pos("-", AppVersion) - 1)
#else
  #define AppNumeric AppVersion
#endif

#define AppName        "QualSafe Web"
#define AppPublisher   "QualSafe"
#define AppExeName     "pythonw.exe"
#define PayloadDir     "..\build\payload_web"
#define IconFile       "..\qualsafe_qt\resources\qualsafe.ico"

[Setup]
AppId={{9E1B7C42-5A3D-4F0B-8C6E-2D4A91B7E053}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppNumeric}
VersionInfoProductName={#AppName}

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\build
OutputBaseFilename=QualSafe-Web-{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\resources\qualsafe.ico
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

DisableReadyPage=no
ShowLanguageDialog=no

LicenseFile=..\LICENSE

; Unsigned, as the desktop installer is: see qualsafe.iss for why signing matters and how to turn it on.
; SignTool=standard
; SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; pythonw.exe, not python.exe: no console window sits behind the app.
Name: "{group}\{#AppName}"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: """{app}\launch_web.py"" start"; WorkingDir: "{app}"; \
    IconFilename: "{app}\resources\qualsafe.ico"; \
    Comment: "Open QualSafe in your browser (it runs on this computer only)"
Name: "{group}\Stop {#AppName}"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: """{app}\launch_web.py"" stop"; WorkingDir: "{app}"; \
    IconFilename: "{app}\resources\qualsafe.ico"; \
    Comment: "Stop QualSafe running in the background"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: """{app}\launch_web.py"" start"; WorkingDir: "{app}"; \
    IconFilename: "{app}\resources\qualsafe.ico"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\python\{#AppExeName}"; Parameters: """{app}\launch_web.py"" start"; \
    WorkingDir: "{app}"; Description: "Open {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the server first, or its files are in use and cannot be removed. --quiet: no message box, which
; nobody could answer during an unattended uninstall.
Filename: "{app}\python\{#AppExeName}"; Parameters: """{app}\launch_web.py"" stop --quiet"; \
    WorkingDir: "{app}"; RunOnceId: "StopQualSafeWeb"; Flags: runhidden

[UninstallDelete]
; Python writes a .pyc beside every module it imports, so running the program scatters __pycache__ through the
; tree and Inno does not track them. These entries remove whole directories the installer created and that
; only ever contain what it put there.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\analysis"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\exports"
Type: filesandordirs; Name: "{app}\interview"
Type: filesandordirs; Name: "{app}\privacy"
Type: filesandordirs; Name: "{app}\prompts"
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\resources"
Type: filesandordirs; Name: "{app}\.streamlit"
Type: filesandordirs; Name: "{app}\__pycache__"

; NOT {app}\data, NOT {app}\output_streamlit, and NOT {app} itself: the researcher's own files may be there.
; `dirifempty` removes each only when nothing of theirs is left.
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}\output_streamlit"
Type: dirifempty; Name: "{app}"

[Messages]
FinishedLabel=%1 is installed.%n%nIt opens in your web browser and runs on this computer only. Your text is never uploaded, and there is no account to create.%n%nUse "Stop QualSafe Web" in the Start menu to stop it running in the background.

[Code]

{ ---------------------------------------------------------------------------
  MAX_PATH. Same reason and same limit as the desktop installer (qualsafe.iss): the payload's deepest internal
  path is about 120 characters (scikit-learn and numpy nest hard), Windows caps a path at 259 unless long-path
  support is on, and that cannot be assumed on a managed machine. PrepareToInstall also runs during a silent
  install, which is when nobody is watching.
  --------------------------------------------------------------------------- }
const
  MaxInstallDirLength = 130;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if Length(ExpandConstant('{app}')) > MaxInstallDirLength then
    Result :=
      'The chosen folder path is too long for Windows.' + #13#10 + #13#10 +
      'QualSafe stores some files in deeply nested folders, and Windows ' +
      'limits how long a full path may be. Please install to a shorter ' +
      'path -- the default location works.' + #13#10 + #13#10 +
      'Chosen folder is ' + IntToStr(Length(ExpandConstant('{app}'))) +
      ' characters; the limit is ' + IntToStr(MaxInstallDirLength) + '.';
end;

{ ---------------------------------------------------------------------------
  Say plainly what uninstalling does and does not remove. SuppressibleMsgBox, not MsgBox, so an unattended
  uninstall (/VERYSILENT) takes the default instead of hanging on an invisible window.
  --------------------------------------------------------------------------- }
function InitializeUninstall(): Boolean;
begin
  Result := SuppressibleMsgBox(
    'Remove QualSafe Web from this computer?' + #13#10 + #13#10 +
    'This removes the program only.' + #13#10 + #13#10 +
    'Your coded projects and analysis output (the output_streamlit folder inside the ' +
    'program folder), any files you added under data, and your saved settings and ' +
    'progress (in AppData\Local\QualSafe Web) are left exactly where they are.',
    mbConfirmation, MB_YESNO, IDYES) = IDYES;
end;
