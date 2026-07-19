<#
.SYNOPSIS
    AI Orchestrator — Windows установка в одно касание
.DESCRIPTION
    - Проверяет/устанавливает Python 3.10+
    - Создаёт venv и ставит зависимости
    - Добавляет в PATH и контекстное меню
    - Опционально устанавливает Ollama и скачивает модель
.NOTES
    Запускать от имени администратора для добавления в PATH
#>

param(
    [string]$InstallDir = "$env:LOCALAPPDATA\AI-Orchestrator",
    [switch]$NoPath,
    [switch]$NoContextMenu,
    [switch]$InstallOllama,
    [switch]$PullModel,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AI Orchestrator Installer"

function Write-Title   { Write-Host "`n=== $($args[0]) ===" -ForegroundColor Cyan }
function Write-Step   { Write-Host " >> $($args[0])" -ForegroundColor Yellow }
function Write-OK     { Write-Host " [+] $($args[0])" -ForegroundColor Green }
function Write-Err    { Write-Host " [!] $($args[0])" -ForegroundColor Red }
function Write-Info   { Write-Host "    $($args[0])" }

if ($Help) {
    Write-Host @"

AI Orchestrator Installer
=========================

Usage:
  .\install.ps1                              # Interactive install
  .\install.ps1 -InstallOllama               # With Ollama
  .\install.ps1 -InstallDir "D:\AI"          # Custom path
  .\install.ps1 -NoPath -NoContextMenu       # Minimal install

"@ -ForegroundColor Cyan
    exit 0
}

# ========== ADMIN CHECK ==========
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and (-not $NoPath)) {
    Write-Info "Tip: Run as Administrator to enable system PATH integration"
}

# ========== 1. Python ==========
Write-Title "Checking Python"
try {
    $ver = python --version 2>&1
    if ($ver -match "3\.(1[0-9]|[2-9]\d)") {
        Write-OK "Python $($ver.Trim())"
    } else {
        throw "Version mismatch"
    }
} catch {
    Write-Step "Python 3.10+ not found. Installing..."
    try {
        # Try to install via winget
        winget install Python.Python.3.12 --accept-package-agreements --silent 2>&1 | Out-Null
        # Refresh PATH
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        python --version 2>&1 | Out-Null
        Write-OK "Python installed via winget"
    } catch {
        Write-Step "Downloading Python installer..."
        $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
        $pyInstaller = "$env:TEMP\python-installer.exe"
        Invoke-WebRequest -Uri $url -OutFile $pyInstaller -UseBasicParsing
        Write-Step "Running Python installer..."
        Start-Process -Wait -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1"
        Remove-Item $pyInstaller -Force
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $ver = python --version 2>&1
        Write-OK "Python $($ver.Trim()) installed"
    }
}

# ========== 2. Create directory ==========
Write-Title "Setting up directories"
$null = New-Item -ItemType Directory -Path $InstallDir -Force
$null = New-Item -ItemType Directory -Path "$InstallDir\data" -Force
$null = New-Item -ItemType Directory -Path "$InstallDir\logs" -Force
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-OK "Install directory: $InstallDir"

# ========== 3. Copy files ==========
Write-Step "Copying application files..."
Copy-Item "$repoDir\*" "$InstallDir\" -Recurse -Force -Exclude "venv", ".git", "__pycache__", "*.pyc"
Write-OK "Files copied"

# ========== 4. Virtual environment ==========
Write-Title "Creating virtual environment"
$venvPython = "$InstallDir\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    python -m venv "$InstallDir\venv"
    Write-OK "Virtual environment created"
} else {
    Write-OK "Virtual environment exists"
}

# ========== 5. Install dependencies ==========
Write-Step "Installing Python packages..."
$pip = "$InstallDir\venv\Scripts\pip.exe"
& $pip install --upgrade pip -q | Out-Null
& $pip install -e "$InstallDir" -q
if ($LASTEXITCODE -eq 0) {
    Write-OK "Dependencies installed"
} else {
    Write-Err "Failed to install dependencies"
    exit 1
}

# ========== 6. Test ==========
Write-Step "Verifying installation..."
$test = & $venvPython -c "from ai_orchestrator import AIOrchestrator; print('OK')" 2>&1
if ($test -eq "OK") {
    Write-OK "Installation verified!"
} else {
    Write-Err "Verification failed: $test"
    exit 1
}

# ========== 7. PATH ==========
if (-not $NoPath) {
    Write-Title "Adding to PATH"
    $scope = if ($isAdmin) { "Machine" } else { "User" }
    $paths = [Environment]::GetEnvironmentVariable("Path", $scope) -split ";"
    if ($paths -notcontains $InstallDir) {
        $newPath = [Environment]::GetEnvironmentVariable("Path", $scope) + ";$InstallDir"
        [Environment]::SetEnvironmentVariable("Path", $newPath, $scope)
        Write-OK "Added to system PATH (restart terminal to apply)"
    } else {
        Write-OK "Already in PATH"
    }
}

# ========== 8. Context menu ==========
if (-not $NoContextMenu) {
    Write-Title "Adding context menu"
    $key = "HKCU:\Software\Classes\Directory\Background\shell\AIOrchestrator"
    if (-not (Test-Path $key)) {
        $null = New-Item -Path $key -Force -Value "AI Orchestrator chat"
        $null = New-ItemProperty -Path $key -Name "Icon" -Value "$InstallDir\icon.ico" -PropertyType String
        $cmdKey = "HKCU:\Software\Classes\Directory\Background\shell\AIOrchestrator\command"
        $null = New-Item -Path $cmdKey -Force -Value "`"$InstallDir\ai-orchestrator.bat`" chat --cwd `"%V`""
        Write-OK "Right-click context menu added"
    } else {
        Write-OK "Context menu already exists"
    }
}

# ========== 9. Ollama ==========
if ($InstallOllama) {
    Write-Title "Ollama"
    try {
        $ov = & ollama --version 2>&1
        Write-OK "Ollama $($ov.Trim())"
    } catch {
        Write-Step "Installing Ollama..."
        $url = "https://ollama.com/download/OllamaSetup.exe"
        $setupPath = "$env:TEMP\OllamaSetup.exe"
        Invoke-WebRequest -Uri $url -OutFile $setupPath -UseBasicParsing
        Start-Process -Wait -FilePath $setupPath -ArgumentList "/S"
        Remove-Item $setupPath -Force
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        Write-OK "Ollama installed"
    }

    if ($PullModel) {
        Write-Step "Pulling recommended free model (qwen2.5:1.5b)..."
        Start-Process -NoNewWindow -Wait -FilePath "ollama" -ArgumentList "pull", "qwen2.5:1.5b"
        Write-OK "Model downloaded"
    }
}

# ========== 10. Done ==========
Write-Title "Installation Complete!"
Write-Host @"

AI Orchestrator installed to: $InstallDir
"@ -ForegroundColor Green

Write-Host @"
Quick start:

  ai-orchestrator chat              Interactive chat
  ai-orchestrator ask "hello"       Ask one question
  ai-orchestrator providers         List AI providers
  ai-orchestrator config            Show configuration

Or right-click any folder → "AI Orchestrator chat"

Make sure Ollama is running:
  ollama serve

For cloud providers (Groq, OpenRouter, etc.):
  set GROQ_API_KEY=your_key

Documentation: https://github.com/pop31-ai/ai-orchestrator
"@ -ForegroundColor Yellow