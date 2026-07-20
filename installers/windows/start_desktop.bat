@echo off
title AI Orchestrator Desktop
cd /d "%~dp0..\.."

echo Starting AI Orchestrator backend...
start /min "AI-Orchestrator" cmd /c "python -m ai_orchestrator desktop --no-browser"

echo Waiting for backend...
:wait
timeout /t 3 /nobreak >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/providers' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 goto wait

echo Starting web UI...
start "" "http://127.0.0.1:8080"
echo All systems ready!
