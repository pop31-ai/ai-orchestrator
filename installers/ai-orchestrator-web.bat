@echo off
title AI Orchestrator Web Server
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [*] Starting AI Orchestrator Web Server...
echo [*] Open http://localhost:8080 in your browser
echo [*] Press Ctrl+C to stop
echo.

%PYTHON% -c "
import uvicorn
from ai_orchestrator.api import create_app
app = create_app()
uvicorn.run(app, host='127.0.0.1', port=8080, log_level='info')
"
pause