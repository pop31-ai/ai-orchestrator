#Requires -Version 7.0
<#
.SYNOPSIS
    Build AI Orchestrator Windows installer package
.DESCRIPTION
    Generates icon, runs Inno Setup compiler, creates installer ZIP.
#>

param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "dist"),
    [switch]$SkipInno
)

$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$ProjectRoot = Resolve-Path (Join-Path $AppDir "..")

function Write-Step { Write-Host "[*] $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "[+] $($args[0])" -ForegroundColor Green }
function Write-Err  { Write-Host "[!] $($args[0])" -ForegroundColor Red }

$null = New-Item -ItemType Directory -Path $OutputDir -Force

# ---------- 1. Generate icon ----------
Write-Step "Generating icon..."
$iconPath = Join-Path $AppDir "icon.ico"
$iconPs1 = Join-Path $AppDir "generate-icon.ps1"
if (-not (Test-Path $iconPath)) {
    & $iconPs1
    if (Test-Path $iconPath) { Write-OK "Icon generated" }
    else { Write-Err "Failed to generate icon (will use default)" }
} else {
    Write-OK "Icon exists"
}

# ---------- 2. Check Inno Setup ----------
$isccPaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 5\ISCC.exe"
)

$iscc = $null
foreach ($p in $isccPaths) {
    if (Test-Path $p) { $iscc = $p; break }
}

if ($iscc -and -not $SkipInno) {
    Write-Step "Building installer with Inno Setup..."
    $issFile = Join-Path $AppDir "ai-orchestrator-installer.iss"
    
    $buildResult = & $iscc $issFile "/O$OutputDir" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Installer built in $OutputDir"
    } else {
        Write-Err "Inno Setup failed:"
        $buildResult | ForEach-Object { Write-Host "  $_" }
    }
} else {
    if (-not $SkipInno) {
        Write-Step "Inno Setup not found. Install from https://jrsoftware.org/isdl.php"
        Write-Step "  or use: winget install JRSoftware.InnoSetup"
    }
    Write-Step "Skipping Inno Setup build"
}

# ---------- 3. Create distribution ZIP ----------
Write-Step "Creating distribution package..."
$zipName = "AI-Orchestrator-1.0.0-Windows.zip"
$zipPath = Join-Path $OutputDir $zipName

$compressItems = @(
    @{Path = $AppDir; Recurse = $true },
    @{Path = (Join-Path $ProjectRoot "ai_orchestrator"); Recurse = $true },
    @{Path = (Join-Path $ProjectRoot "requirements.txt") },
    @{Path = (Join-Path $ProjectRoot "pyproject.toml") },
    @{Path = (Join-Path $ProjectRoot "README.md") }
)

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path ($compressItems.Path) -DestinationPath $zipPath -CompressionLevel Optimal
Write-OK "Distribution package: $zipPath"

# ---------- 4. Summary ----------
Write-Host ""
Write-Step "Build complete!"
Write-Host ""
Write-Host "  Outputs:" -ForegroundColor Yellow
Get-ChildItem $OutputDir | ForEach-Object {
    Write-Host "    $($_.Name) ($( '{0:N1} MB' -f ($_.Length / 1MB) ))" -ForegroundColor Green
}
Write-Host ""
Write-Host "  To publish:" -ForegroundColor Yellow
Write-Host "    Create GitHub Release with the files above" -ForegroundColor Green