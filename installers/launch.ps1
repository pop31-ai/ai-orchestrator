param(
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step { Write-Host "[*] $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "[+] $($args[0])" -ForegroundColor Green }
function Write-Err  { Write-Host "[!] $($args[0])" -ForegroundColor Red }

# Python check
try {
    $pyVersion = python --version 2>&1 | Out-String
    if ($pyVersion -notmatch "3\.(1[0-9]|[2-9]\d)") {
        Write-Err "Python 3.10+ required. Found: $($pyVersion.Trim())"
        exit 1
    }
    Write-OK "Found $($pyVersion.Trim())"
} catch {
    Write-Err "Python not found. Install from python.org"
    exit 1
}

# VENV
$venvPython = Join-Path $AppDir "venv" "Scripts" "python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment..."
    python -m venv (Join-Path $AppDir "venv")
    Write-Step "Installing dependencies..."
    & (Join-Path $AppDir "venv" "Scripts" "pip.exe") install --upgrade pip -q
    & (Join-Path $AppDir "venv" "Scripts" "pip.exe") install -e $AppDir -q
    Write-OK "Dependencies installed"
}

# Launch
Write-Step "Starting AI Orchestrator..."
$process = Start-Process -FilePath $venvPython -WorkingDirectory $AppDir -NoNewWindow -PassThru -Wait `
    -ArgumentList @("-m", "ai_orchestrator") + $Arguments

exit $process.ExitCode