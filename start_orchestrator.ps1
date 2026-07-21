# Restart orchestrator with all-core CPU affinity — kills any old process on port 8080
param()

# Kill any process already listening on 8080
$old = netstat -ano | Select-String ":8080" | Select-String "LISTEN"
if ($old) {
    $oldPid = ($old -split '\s+')[-1]
    taskkill /F /PID $oldPid 2>$null
    Start-Sleep 2
}

# Cleanup stale checkpoint/SOS flags
Remove-Item "$PSScriptRoot\.opencode\SOS.flg" -Force -ErrorAction SilentlyContinue
Remove-Item "$PSScriptRoot\.opencode\checkpoint.json" -Force -ErrorAction SilentlyContinue

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Clear old log
Remove-Item server_out.log -Force -ErrorAction SilentlyContinue

Write-Host "Starting TinyLlama Server..." -ForegroundColor Green

$pinfo = New-Object System.Diagnostics.ProcessStartInfo
$pinfo.FileName = "python"
$pinfo.Arguments = "-u ai_orchestrator/agentic_chat.py --port 8080 --host 0.0.0.0"
$pinfo.WorkingDirectory = $scriptPath
$pinfo.UseShellExecute = $false
$pinfo.RedirectStandardOutput = $true
$pinfo.RedirectStandardError = $true
$pinfo.CreateNoWindow = $true

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $pinfo
$proc.Start() | Out-Null

# Set affinity to all cores
$numCores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
$mask = [int]::Pow(2, $numCores) - 1
$proc.ProcessorAffinity = [IntPtr] $mask

Write-Host "PID: $($proc.Id) | Affinity: $numCores cores (0x$('{0:X}' -f $mask))"
Write-Host "URL: http://127.0.0.1:8080"
Write-Host "=== Press Ctrl+C to stop ==="

# Log output to file
$logFile = "$scriptPath\server_out.log"
$proc.StandardOutput | Out-File -FilePath $logFile -Encoding UTF8
$proc.WaitForExit()
