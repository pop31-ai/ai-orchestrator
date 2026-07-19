; AI Orchestrator — Inno Setup Installer
; https://github.com/pop31-ai/ai-orchestrator

#define MyAppName "AI Orchestrator"
#define MyAppShortName "ai-orchestrator"
#define MyAppPublisher "pop31-ai"
#define MyAppURL "https://github.com/pop31-ai/ai-orchestrator"
#define MyAppExeName "ai-orchestrator.bat"

[Setup]
AppId={{B3F7C2B1-8A94-4E0D-9C6F-5A2E7D1F8C4B}
AppName={#MyAppName}
AppVersion=1.0.0
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppShortName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableWelcomePage=no
OutputDir=.
OutputBaseFilename=AI-Orchestrator-1.0.0-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName="{#MyAppName}"
SetupLogging=yes
ChangesEnvironment=yes
DirExistsWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Create Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "addtopath"; Description: "Add to system PATH (for ai-orchestrator CLI)"; GroupDescription: "System integration:"
Name: "installollama"; Description: "Install Ollama (local AI backend, ~800MB)"; GroupDescription: "Components:"
Name: "pullmodels"; Description: "Pull recommended free models (~3GB total)"; GroupDescription: "Components:"; Flags: unchecked

[Dirs]
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\logs"; Permissions: users-modify
Name: "{app}\scripts"; Permissions: users-modify

[Files]
; Application core
Source: "..\ai_orchestrator\*.py"; DestDir: "{app}\ai_orchestrator"; Flags: ignoreversion recursesubdirs
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

; Scripts and launchers
Source: "launch.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "launch.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "ai-orchestrator.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "install_deps.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "windows-integration.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "terminal-profile.json"; DestDir: "{app}"; Flags: ignoreversion

; NSSM for Windows service (for web server mode)
Source: "tools\nssm.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Check: NssmExists

; Icons
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Interactive chat"
Name: "{group}\{#MyAppName} (Web Server)"; Filename: "{app}\ai-orchestrator-web.bat"; WorkingDir: "{app}"; Comment: "Start web UI server"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Interactive chat"

[Run]
Filename: "{app}\install_deps.ps1"; Parameters: "-AppDir ""{app}"""; WorkingDir: "{app}"; Flags: runhidden; StatusMsg: "Installing Python dependencies..."
Filename: "{app}\windows-integration.ps1"; Parameters: "-AppDir ""{app}"" -AddToPath"; WorkingDir: "{app}"; Flags: runhidden; Tasks: addtopath; StatusMsg: "Adding to system PATH..."

; Ollama installation (optional)
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/S"; WorkingDir: "{app}"; StatusMsg: "Installing Ollama..."; Tasks: installollama; Check: not IsOllamaInstalled

; Show welcome message after install
Filename: "{cmd}"; Parameters: "/C echo. & echo ======================================== & echo  AI Orchestrator installed successfully! & echo ======================================== & echo. & echo  Quick start: & echo    ai-orchestrator chat              - interactive session & echo    ai-orchestrator ask "hi"          - one question & echo    ai-orchestrator providers          - list providers & echo. & echo  Make sure Ollama is running (ollama serve) & echo  or configure a cloud provider in config. & echo. & pause"; Flags: postinstall; Description: "Show installation summary"

[UninstallRun]
Filename: "{app}\windows-integration.ps1"; Parameters: "-RemoveFromPath"; WorkingDir: "{app}"; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\ai_orchestrator\__pycache__"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\logs"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nAI Orchestrator is a local AI agent orchestration system that works with free AI models.%n%nRequirements:%n- Windows 10/11 64-bit%n- Python 3.10 or later (will be checked)%n- Optional: Ollama for local models (can install during setup)

[Code]
var
  PythonVersion: String;
  PythonInstalled: Boolean;

function IsOllamaInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Ollama') or
            RegKeyExists(HKCU, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Ollama');
  if not Result then
    Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) or
              FileExists(ExpandConstant('{commonappdata}\Ollama\ollama.exe'));
end;

function NssmExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\tools\nssm.exe'));
end;

procedure CheckPython;
var
  ResultCode: Integer;
  Output: String;
begin
  PythonInstalled := False;
  if Exec(ExpandConstant('{cmd}'), '/c python --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
      PythonInstalled := True;
  end;
end;

function InitializeSetup: Boolean;
begin
  CheckPython;
  if not PythonInstalled then
  begin
    if MsgBox('Python 3.10+ is required but not found.'#13#13'Do you want to continue installation anyway?'#13'You will need to install Python manually from python.org', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    Log('Starting installation...');
    Log('Python installed: ' + BoolToStr(PythonInstalled, True));
    Log('Ollama installed: ' + BoolToStr(IsOllamaInstalled, True));
  end;
  if CurStep = ssPostInstall then
  begin
    Log('Installation completed.');
  end;
end;