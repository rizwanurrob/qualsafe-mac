; QualSafe Desktop -- Inno Setup script
;
;   python packaging/build_payload.py
;   iscc packaging\qualsafe.iss /DAppVersion=0.99.0
;
; Produces  build\QualSafe-Desktop-<version>-Setup.exe : one file, no admin
; rights, no Python required on the target machine.
;
; Requires Inno Setup 6:  https://jrsoftware.org/isdl.php
;
; ---------------------------------------------------------------------------
; Design decisions worth not re-litigating
; ---------------------------------------------------------------------------
; PER-USER INSTALL (PrivilegesRequired=lowest). Installs under
; %LOCALAPPDATA%\Programs, so a researcher on a managed university machine can
; install it without calling IT. RELEASE_READINESS.md §5 lists admin rights as
; explicitly not needed, and this is what makes that true.
;
; THE UNINSTALLER REMOVES THE PROGRAM AND NOTHING ELSE (§3.4). Projects, run
; outputs, and the ~1.8 GB model cache all live outside {app}. Deleting a
; researcher's coded projects because they uninstalled an app would be
; unforgivable, so [UninstallDelete] below is scoped to bytecode caches this
; install itself created, and the final page says in words what was kept.
;
; APPID IS FIXED FOREVER. It is how Windows knows an install is an upgrade
; rather than a second copy. Changing it strands the old install in Add/Remove
; Programs with no way to uninstall it.

#ifndef AppVersion
  #define AppVersion "0.99.0"
#endif

; A pre-release label ("0.99.11-ux1") is allowed in the visible version; the Windows
; file-version field must be numeric, so it gets the part before the dash.
#if Pos("-", AppVersion) > 0
  #define AppNumeric Copy(AppVersion, 1, Pos("-", AppVersion) - 1)
#else
  #define AppNumeric AppVersion
#endif

#define AppName        "QualSafe Desktop"
#define AppPublisher   "QualSafe"
#define AppExeName     "pythonw.exe"
#define PayloadDir     "..\build\payload"
#define IconFile       "..\qualsafe_qt\resources\qualsafe.ico"
; MUST match qualsafe_qt/main.py APP_USER_MODEL_ID. If the shortcut and the
; running process disagree, Windows treats them as two different apps: the
; pinned button never lights up, and launching opens a second button beside it.
; A test asserts the two stay equal.
#define AppUserId      "QualSafe.Desktop"

[Setup]
AppId={{6C2105F4-1540-4526-A8BD-3461ABD01B44}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppNumeric}
VersionInfoProductName={#AppName}

; Per-user. No UAC prompt, no admin account needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; The payload is a 64-bit CPython.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\build
OutputBaseFilename=QualSafe-Desktop-{#AppVersion}-Setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\qualsafe_qt\resources\qualsafe.ico
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; Thousands of small files; without this the progress bar looks frozen.
DisableReadyPage=no
ShowLanguageDialog=no

LicenseFile=..\LICENSE

; --- CODE SIGNING ----------------------------------------------------------
; Unsigned, every download triggers a SmartScreen "unrecognised app" warning --
; close to fatal for a tool asking researchers to trust it with interview data
; (RELEASE_READINESS.md §1.4). Once a certificate exists, configure a sign tool
; in the Inno IDE and uncomment BOTH lines. Signing the uninstaller matters too:
; it is what the user runs later, when they trust the app least.
;
; SignTool=standard
; SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The whole prepared tree: interpreter, dependencies, app, and sample data.
; recursesubdirs+createallsubdirs because the payload is deeply nested.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; pythonw.exe, not python.exe: no console window sits behind the app for its
; whole life (RELEASE_READINESS.md §1.3).
Name: "{group}\{#AppName}"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: "-m qualsafe_qt"; WorkingDir: "{app}"; \
    IconFilename: "{app}\qualsafe_qt\resources\qualsafe.ico"; \
    AppUserModelID: "{#AppUserId}"; \
    Comment: "Read, code, and analyse qualitative data on this computer"
; Same AppUserModelID as the main shortcut, deliberately: this launches the
; same program, so it must land in the same taskbar group rather than opening a
; second, iconless one.
Name: "{group}\User guide"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: "-m qualsafe_qt"; WorkingDir: "{app}"; \
    IconFilename: "{app}\qualsafe_qt\resources\qualsafe.ico"; \
    AppUserModelID: "{#AppUserId}"; \
    Comment: "Opens the program; press F1 for the guide"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\{#AppExeName}"; \
    Parameters: "-m qualsafe_qt"; WorkingDir: "{app}"; \
    IconFilename: "{app}\qualsafe_qt\resources\qualsafe.ico"; \
    AppUserModelID: "{#AppUserId}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\python\{#AppExeName}"; Parameters: "-m qualsafe_qt"; \
    WorkingDir: "{app}"; Description: "Start {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python writes a .pyc beside every module it imports, so running the program
; scatters __pycache__ through the whole tree -- the standard library, every
; dependency, every package. Inno does not track files created after install,
; so it removes what it copied and leaves the bytecode behind.
;
; An earlier version of this section listed individual __pycache__ paths. That
; is whack-a-mole: a measured uninstall left 716 .pyc files and the install
; folder standing. These entries remove whole directories instead.
;
; Every directory named here is one the installer created and only ever
; contains what it put there, so a recursive delete is safe.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\qualsafe_qt"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\analysis"
Type: filesandordirs; Name: "{app}\engines"
Type: filesandordirs; Name: "{app}\exports"
Type: filesandordirs; Name: "{app}\interview"
Type: filesandordirs; Name: "{app}\privacy"
Type: filesandordirs; Name: "{app}\prompts"
Type: filesandordirs; Name: "{app}\config"

; NOT {app}\data, and NOT {app} itself.
;
; The Help walkthrough tells a new user to import from the `data` folder inside
; the installation, so that is a folder they may well have added their own
; transcripts to. Inno removes the sample files it installed; anything the user
; put there stays. `dirifempty` then removes the folder only when nothing of
; theirs is left -- and the same for the installation directory itself.
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}"

[Messages]
; Shown on the final wizard page.
FinishedLabel=%1 is installed.%n%nEverything runs on this computer. Your text is never uploaded, and there is no account to create.%n%nPress F1 inside the program for the guide -- start with "Start here", which walks you through coding a sample transcript in about five minutes.

[Code]

{ ---------------------------------------------------------------------------
  MAX_PATH.

  The payload's deepest internal path is 120 characters -- scikit-learn and
  numpy both nest hard, e.g.
    python\Lib\site-packages\sklearn\metrics\_pairwise_distances_reduction\...
  Windows caps a path at 259 characters unless long-path support is on, which
  cannot be assumed on a managed machine. So an install directory longer than
  about 138 characters makes some files unwritable.

  This is not hypothetical: a first test install into a deeply nested folder
  failed exactly here, with "MoveFile failed; code 3" (ERROR_PATH_NOT_FOUND)
  part-way through `cryptography\hazmat\bindings\_rust\`, and rolled back. The
  rollback worked correctly -- but the user saw a failure with no explanation
  of the cause, which is the part worth fixing.

  The default directory is ~54 characters, so this fires only for someone who
  chose an unusually deep location. 130 rather than 138 leaves room for the
  payload to grow a little without silently reintroducing the failure.

  PrepareToInstall is the right hook: unlike NextButtonClick it also runs
  during a silent install, which is precisely when nobody is watching.
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
  Say plainly what uninstalling does and does not remove. A researcher's
  projects are the whole point of the tool; they must not have to guess.

  SuppressibleMsgBox, NOT MsgBox. A plain MsgBox ignores /SUPPRESSMSGBOXES and
  blocks forever with no visible window under /VERYSILENT, which makes an
  unattended uninstall impossible -- it hangs rather than fails. Found by
  running it. With this form, a silent uninstall takes the default (IDYES) and
  proceeds, while an ordinary interactive uninstall still shows the message.
  --------------------------------------------------------------------------- }
function InitializeUninstall(): Boolean;
begin
  Result := SuppressibleMsgBox(
    'Remove QualSafe Desktop from this computer?' + #13#10 + #13#10 +
    'This removes the program only.' + #13#10 + #13#10 +
    'Your project files (.qnw), any analysis output you saved, and the ' +
    'downloaded language models are stored outside the program folder and ' +
    'will be left exactly where they are.',
    mbConfirmation, MB_YESNO, IDYES) = IDYES;
end;
