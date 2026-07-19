param(
    [string]$AppDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$AddToPath,
    [switch]$RemoveFromPath,
    [switch]$AddContextMenu,
    [switch]$RemoveContextMenu,
    [switch]$AddTerminalProfile
)

$ErrorActionPreference = "Stop"

function Write-Step { Write-Host "[*] $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "[+] $($args[0])" -ForegroundColor Green }
function Write-Err  { Write-Host "[!] $($args[0])" -ForegroundColor Red }

$batPath = Join-Path $AppDir "ai-orchestrator.bat"

# ---------- PATH ----------
function Add-ToPath {
    $scope = "User"
    $paths = [Environment]::GetEnvironmentVariable("Path", $scope) -split ";"
    if ($paths -contains $AppDir) {
        Write-OK "Already in PATH"
        return
    }
    $newPath = [Environment]::GetEnvironmentVariable("Path", $scope) + ";$AppDir"
    [Environment]::SetEnvironmentVariable("Path", $newPath, $scope)
    Write-OK "Added $AppDir to user PATH"
    Write-Step "Restart terminal to apply, or run: `$env:Path += ';$AppDir'"
}

function Remove-FromPath {
    $scope = "User"
    $paths = [Environment]::GetEnvironmentVariable("Path", $scope) -split ";"
    $newPaths = $paths | Where-Object { $_ -ne $AppDir }
    [Environment]::SetEnvironmentVariable("Path", ($newPaths -join ";"), $scope)
    Write-OK "Removed $AppDir from user PATH"
}

# ---------- Context menu ----------
function Add-ContextMenu {
    $key = "HKCU:\Software\Classes\Directory\Background\shell\AIOrchestrator"
    if (Test-Path $key) {
        Write-OK "Context menu already registered"
        return
    }
    $null = New-Item -Path $key -Force -Value "Open AI Orchestrator here" -ErrorAction Stop
    $null = New-ItemProperty -Path $key -Name "Icon" -Value "$batPath" -PropertyType String -ErrorAction Stop
    $cmdKey = "HKCU:\Software\Classes\Directory\Background\shell\AIOrchestrator\command"
    $null = New-Item -Path $cmdKey -Force -Value "`"$batPath`" chat --cwd `"%V`"" -ErrorAction Stop
    Write-OK "Context menu added (right-click in any folder)"
}

function Remove-ContextMenu {
    $key = "HKCU:\Software\Classes\Directory\Background\shell\AIOrchestrator"
    if (Test-Path $key) {
        Remove-Item -Path $key -Recurse -Force
        Write-OK "Context menu removed"
    }
}

# ---------- Terminal profile ----------
function Add-TerminalProfile {
    $settingsPath = "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json"
    $backupPath = "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.backup.json"

    if (-not (Test-Path $settingsPath)) {
        Write-Err "Windows Terminal settings not found"
        return
    }

    # Backup
    Copy-Item $settingsPath $backupPath -Force

    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    $profileName = "AI Orchestrator"

    # Check if already exists
    $existing = $settings.profiles.list | Where-Object { $_.name -eq $profileName }
    if ($existing) {
        Write-OK "Terminal profile already exists"
        return
    }

    $newProfile = @{
        name = $profileName
        commandline = "cmd.exe /k `"$batPath`" chat"
        icon = "$batPath"
        startingDirectory = $AppDir
        colorScheme = "Campbell"
        font = @{
            face = "Cascadia Code"
            size = 10
        }
    }

    $settings.profiles.list += $newProfile
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
    Write-OK "Terminal profile added: '$profileName'"
}

# ---------- Main ----------
if ($AddToPath) { Add-ToPath }
if ($RemoveFromPath) { Remove-FromPath }
if ($AddContextMenu) { Add-ContextMenu }
if ($RemoveContextMenu) { Remove-ContextMenu }
if ($AddTerminalProfile) { Add-TerminalProfile }

if (-not $AddToPath -and -not $RemoveFromPath -and -not $AddContextMenu -and -not $RemoveContextMenu -and -not $AddTerminalProfile) {
    Write-Host ""
    Write-Host "Windows Integration Script" -ForegroundColor Cyan
    Write-Host "=========================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\windows-integration.ps1 -AddToPath           Add to PATH"
    Write-Host "  .\windows-integration.ps1 -AddContextMenu      Add right-click menu"
    Write-Host "  .\windows-integration.ps1 -AddTerminalProfile  Add Windows Terminal profile"
    Write-Host ""
    Write-Host "  .\windows-integration.ps1 -RemoveFromPath      Remove from PATH"
    Write-Host "  .\windows-integration.ps1 -RemoveContextMenu   Remove context menu"
    Write-Host ""
}