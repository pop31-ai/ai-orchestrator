import sys
sys.path.insert(0, 'C:\\Users\\e\\Desktop\\4a')
from ai_orchestrator.agentic_chat import create_app
from aiohttp import web
web.run_app(create_app(), host='127.0.0.1', port=8080)
