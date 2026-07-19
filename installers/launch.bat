@echo off
title AI Orchestrator
cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ not found. Install from python.org
    pause
    exit /b 1
)

REM Check if venv exists, create if not
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo [*] Installing dependencies...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip -q
    pip install -e . -q
) else (
    call venv\Scripts\activate.bat
)

echo [*] Starting AI Orchestrator...
python -m ai_orchestrator %*
if %errorlevel% neq 0 (
    echo [ERROR] Application exited with error code %errorlevel%
    pause
)
deactivate