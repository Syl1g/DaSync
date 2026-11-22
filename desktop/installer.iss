; Установщик DaSync (Inno Setup 6). Версия берётся из переменной окружения DASYNC_VERSION.
#define AppName "DaSync"
#define AppVersion GetEnv("DASYNC_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{B6E0F4D2-5A7C-4C1E-9D3A-DA5C0A1D0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DaSync
DefaultDirName={autopf}\DaSync
DefaultGroupName=DaSync
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=DaSync-Setup
SetupIconFile=assets\dasync.ico
UninstallDisplayIcon={app}\DaSync.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Запускать DaSync вместе с Windows"; GroupDescription: "Дополнительно:"
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "dist\DaSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DaSync"; Filename: "{app}\DaSync.exe"
Name: "{autodesktop}\DaSync"; Filename: "{app}\DaSync.exe"; Tasks: desktopicon

[Registry]
; то же значение, что включает переключатель «Запускать с Windows» в самом приложении
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LaptopHub"; ValueData: """{app}\DaSync.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
; Правило брандмауэра для домашней (частной) сети, чтобы Windows не спрашивала при первом запуске
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""DaSync"" dir=in action=allow program=""{app}\DaSync.exe"" profile=private protocol=TCP localport=8765"; Flags: runhidden; StatusMsg: "Настраиваю брандмауэр..."
Filename: "{app}\DaSync.exe"; Description: "Запустить DaSync"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DaSync"""; Flags: runhidden; RunOnceId: "DelFirewallRule"
