@echo off
title Orchestrator - ALL CORES
echo Starting AI Orchestrator with ALL CPU cores...
echo.

:: Set Python process to high priority
cd /d "%~dp0"

:: Start Python in background, then set its affinity
start /B /HIGH /WAIT python -u ai_orchestrator\agentic_chat.py
