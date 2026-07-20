import asyncio, time
from ai_orchestrator.orchestrator import AIOrchestrator
from ai_orchestrator.config import Config

async def main():
    cfg = Config()
    cfg.active_provider = 'local_tinyllama_q2'
    orch = AIOrchestrator(config_path=None)
    # minimal config with one provider
    cfg.providers = {}
    cfg.providers['local_tinyllama_q2'] = type('P', (), {
        'name': 'Speedy', 'type': 'local_ctransformers',
        'model': 'tinyllama-1.1b-chat-v1.0.Q2_K.gguf', 'enabled': True, 'priority': 10,
        'extra_params': {'hf_repo': 'TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF',
                         'hf_file': 'tinyllama-1.1b-chat-v1.0.Q2_K.gguf',
                         'model_type': 'llama', 'template': 'llama', 'n_threads': 5}
    })()
    orch = AIOrchestrator(config_path=None)
    orch.config = cfg
    await orch.initialize()
    agent = await orch.create_agent(system_prompt='You are terse. Answer shortly.', agent_config={'enable_tools': True, 'max_tool_iterations': 10})
    t0 = time.time()
    n = 0
    async for chunk in orch.send_message(content='what is 2+2? one sentence', agent_id=agent.agent_id):
        if chunk.content:
            n += 1
    print(f'send_message took {time.time()-t0:.0f}s, {n} chunks')

asyncio.run(main())
