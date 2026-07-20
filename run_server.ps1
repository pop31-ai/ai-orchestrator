$env:PYTHONUNBUFFERED = "1"
Set-Location "C:\Users\e\Desktop\4a"
python -m ai_orchestrator.agentic_chat 2>&1 | Out-File "C:\Users\e\Desktop\4a\server_out.txt"
