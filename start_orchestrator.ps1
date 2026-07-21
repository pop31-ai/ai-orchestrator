# Start orchestrator with all-core CPU affinity
# Run as Administrator!
param()

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

Write-Host "Starting Orchestrator..." -ForegroundColor Green

# Start Python process
$pinfo = New-Object System.Diagnostics.ProcessStartInfo
$pinfo.FileName = "python"
$pinfo.Arguments = "-u ai_orchestrator/agentic_chat.py"
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

Write-Host "Python PID: $($proc.Id)"
Write-Host "CPU affinity: $numCores cores (mask 0x$('{0:X}' -f $mask))"
Write-Host "Server: http://127.0.0.1:8080"
Write-Host "Press Ctrl+C to stop"

# Print output
$proc.StandardOutput.ReadToEnd()
$proc.WaitForExit()
