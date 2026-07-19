# build-apk.ps1 — сборка APK для Android 8 и 11
param(
    [string]$OutputDir = (Join-Path $PSScriptRoot "dist"),
    [switch]$Release,
    [switch]$Install,
    [string[]]$Flavors = @("android8", "android11")
)

$ErrorActionPreference = "Stop"

function Write-Step { Write-Host "[*] $($args[0])" -ForegroundColor Cyan }
function Write-OK   { Write-Host "[+] $($args[0])" -ForegroundColor Green }
function Write-Err  { Write-Host "[!] $($args[0])" -ForegroundColor Red }

$ProjectDir = $PSScriptRoot
$null = New-Item -ItemType Directory -Path $OutputDir -Force

# --- 1. Проверка Gradle ---
$gradlePaths = @(
    Join-Path $ProjectDir "gradlew.bat",
    Join-Path $ProjectDir "gradlew",
    "gradle"
)

$gradle = $null
foreach ($p in $gradlePaths) {
    if (Test-Path $p) { $gradle = $p; break }
}

if (-not $gradle) {
    Write-Step "Gradle wrapper not found. Downloading..."
    Set-Location $ProjectDir
    gradle wrapper --gradle-version 8.5 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Manual download
        $url = "https://services.gradle.org/distributions/gradle-8.5-bin.zip"
        $zipPath = "$env:TEMP\gradle-8.5-bin.zip"
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
        Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\gradle-8.5" -Force
        $gradle = "$env:TEMP\gradle-8.5\gradle-8.5\bin\gradle.bat"
    }
}

# --- 2. ANDROID_HOME ---
if (-not $env:ANDROID_HOME) {
    $possiblePaths = @(
        "$env:LOCALAPPDATA\Android\Sdk",
        "$env:ProgramFiles\Android\AndroidSdk",
        "$env:ProgramFiles(x86)\Android\AndroidSdk",
        "$env:USERPROFILE\Android\Sdk"
    )
    foreach ($p in $possiblePaths) {
        if (Test-Path $p) { $env:ANDROID_HOME = $p; break }
    }
}

if (-not $env:ANDROID_HOME) {
    Write-Err "ANDROID_HOME not set. Install Android SDK or set environment variable."
    Write-Err "  Download: https://developer.android.com/studio#command-tools"
    exit 1
}
Write-OK "Android SDK: $env:ANDROID_HOME"

# --- 3. Сборка ---
$buildType = if ($Release) { "release" } else { "debug" }

foreach ($flavor in $Flavors) {
    Write-Step "Building $flavor ($buildType)..."
    
    $task = "assemble${flavor^}$($buildType.Substring(0,1).ToUpper())${buildType.Substring(1)}"
    
    if ($gradle.EndsWith(".bat") -or $gradle.EndsWith(".exe")) {
        & $gradle -p $ProjectDir $task --daemon
    } else {
        & $gradle -p $ProjectDir $task --daemon
    }

    if ($LASTEXITCODE -eq 0) {
        # Copy APK
        $apkDir = Join-Path $ProjectDir "app" "build" "outputs" "apk"
        $pattern = "*$flavor*$buildType*.apk"
        $apks = Get-ChildItem -Path $apkDir -Filter $pattern -Recurse
        
        foreach ($apk in $apks) {
            $destName = "AI-Orchestrator-$flavor-$buildType.apk"
            Copy-Item $apk.FullName (Join-Path $OutputDir $destName) -Force
            Write-OK "$destName ($([math]::Round($apk.Length/1MB, 1)) MB)"
        }
    } else {
        Write-Err "Build failed for $flavor"
    }
}

# --- 4. Install ---
if ($Install -and $Release) {
    foreach ($flavor in $Flavors) {
        $apk = Get-ChildItem $OutputDir -Filter "*$flavor-release*" | Select-Object -First 1
        if ($apk) {
            Write-Step "Installing $flavor..."
            adb install -r $apk.FullName
        }
    }
}

Write-Step "Done! APK files in: $OutputDir"
Get-ChildItem $OutputDir -Filter "*.apk" | ForEach-Object {
    Write-Host "  $($_.Name) ($([math]::Round($_.Length/1MB, 1)) MB)" -ForegroundColor Green
}