@echo off
title AI Orchestrator
cd /d "%~dp0"

REM Find python in venv or system
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM Forward args
%PYTHON% -m ai_orchestrator %*
exit /b %errorlevel%