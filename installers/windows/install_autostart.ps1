# AI Orchestrator - auto-start registration
$scriptPath = "C:\Users\e\Desktop\4a\installers\windows\start_desktop.bat"
$taskName = "AIOrchestratorDesktop"

# Create scheduled task for logon
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "✅ Auto-start registered: $taskName" -ForegroundColor Green
Write-Host "   Starts automatically when you log in." -ForegroundColor Cyan

# Also add to Run registry as backup
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $runKey -Name "AIOrchestrator" -Value "cmd.exe /c `"$scriptPath`""
Write-Host "✅ Registry Run key added (backup)" -ForegroundColor Green
