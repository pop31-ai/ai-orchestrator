param(
    [string]$AppDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"

function Write-Step { Write-Host "[*] $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "[+] $($args[0])" -ForegroundColor Green }
function Write-Err  { Write-Host "[!] $($args[0])" -ForegroundColor Red }

# ---------- Python check ----------
Write-Step "Checking Python..."
try {
    $ver = python --version 2>&1
    if ($ver -match "3\.(1[0-9]|[2-9]\d)") {
        Write-OK "Python $($ver.Trim())"
    } else {
        Write-Err "Python 3.10+ required. Found: $($ver.Trim())"
        exit 1
    }
} catch {
    Write-Err "Python not found. Download from https://python.org"
    exit 1
}

# ---------- Create venv ----------
$venvPath = Join-Path $AppDir "venv"
$venvPython = Join-Path $venvPath "Scripts" "python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment..."
    python -m venv $venvPath
    Write-OK "Virtual environment created"
} else {
    Write-OK "Virtual environment exists"
}

# ---------- Install pip deps ----------
Write-Step "Installing Python dependencies..."
$pip = Join-Path $venvPath "Scripts" "pip.exe"
& $pip install --upgrade pip -q | Out-Null
& $pip install -e $AppDir -q
if ($LASTEXITCODE -eq 0) {
    Write-OK "Dependencies installed"
} else {
    Write-Err "Failed to install dependencies"
    exit 1
}

# ---------- Create data dirs ----------
$null = New-Item -ItemType Directory -Path (Join-Path $AppDir "data") -Force
$null = New-Item -ItemType Directory -Path (Join-Path $AppDir "logs") -Force
$null = New-Item -ItemType Directory -Path (Join-Path $AppDir "tools") -Force

# ---------- Test import ----------
Write-Step "Testing installation..."
$result = & $venvPython -c "from ai_orchestrator import AIOrchestrator; print('OK')" 2>&1
if ($result -eq "OK") {
    Write-OK "Installation verified"
} else {
    Write-Err "Verification failed: $result"
    exit 1
}

# ---------- Ollama check ----------
try {
    $ollamaVer = & ollama --version 2>&1
    Write-OK "Ollama $($ollamaVer.Trim())"
} catch {
    Write-Step "Ollama not installed. Download from https://ollama.com"
    Write-Step "  or run: winget install Ollama.Ollama"
}

Write-OK "Installation complete!"
Write-Host ""
Write-Host "  Quick start:" -ForegroundColor Yellow
Write-Host "    .\ai-orchestrator.bat chat              Interactive chat" -ForegroundColor Green
Write-Host "    .\ai-orchestrator.bat ask 'hello'       One question" -ForegroundColor Green
Write-Host "    .\ai-orchestrator.bat providers          List providers" -ForegroundColor Green
Write-Host ""
Write-Host "  If using Ollama:" -ForegroundColor Yellow
Write-Host "    ollama pull qwen2.5:1.5b                Pull free model" -ForegroundColor Green
Write-Host "    ollama serve                            Start Ollama server" -ForegroundColor Green