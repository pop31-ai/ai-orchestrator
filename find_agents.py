with open(r'C:\Users\e\Desktop\4a\ai_orchestrator\agentic_chat.py', 'r') as f:
    content = f.read()

import re
for m in re.finditer(r'"(\w+)": AgentConfig\(', open(r'C:\Users\e\Desktop\4a\ai_orchestrator\agentic_chat.py', 'r').read()):
    print(m.group(1))