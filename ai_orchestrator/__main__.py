"""Main CLI application"""

import asyncio
import json
import logging
import os
import re
import sys
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from .config import Config, load_config, get_default_config_path, AIProviderConfig
from .orchestrator import AIOrchestrator
from .agent import AgentMessage, MessageRole, AgentConfig
from .providers import CompletionOptions

console = Console()
logger = logging.getLogger(__name__)

CMD_RE = re.compile(r'CMD:\s*(.+?)(?=\nCMD:|\Z)', re.DOTALL)
DELEGATE_RE = re.compile(r'DELEGATE:\s*(\w+)')
CHAR_MAP = {
    'assistant': 'local_tinyllama', 'speedy': 'local_tinyllama_q2',
    'thinker': 'local_tinyllama_q3', 'analyst': 'local_tinyllama_q5',
    'scholar': 'local_tinyllama_q8', 'mistral': 'local_mistral7b',
}


@click.group()
@click.option('--config', '-c', type=click.Path(exists=True), help='Config file path')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.pass_context
def cli(ctx, config: str, verbose: bool):
    """AI Orchestrator - Local AI agent with free models"""
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    ctx.obj['verbose'] = verbose

    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


@cli.command()
@click.option('--provider', '-p', help='AI provider to use')
@click.option('--model', '-m', help='Model to use')
@click.option('--system', '-s', help='System prompt')
@click.option('--session', help='Session ID to continue')
@click.pass_context
def chat(ctx, provider: str, model: str, system: str, session: str):
    """Start interactive chat session"""
    asyncio.run(_run_chat(ctx.obj['config_path'], provider, model, system, session))


async def _run_chat(config_path: str, provider: str, model: str, system: str, session_id: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()

    # Switch provider if specified
    if provider:
        await orchestrator.switch_provider(provider)

    # Create agent
    agent_config = AgentConfig(
        allowed_tools=["shell", "file_read", "file_write", "file_edit", "web_search", "web_fetch"],
        max_steps=20
    )

    agent = await orchestrator.create_agent(
        agent_type="chat",
        system_prompt=system or "You are a helpful AI assistant with access to tools.",
        agent_config=asdict(agent_config) if hasattr(agent_config, '__dataclass_fields__') else agent_config
    )

    console.print(Panel.fit(
        f"[bold cyan]AI Orchestrator Chat[/bold cyan]\n"
        f"Provider: {orchestrator.active_provider_name}\n"
        f"Model: {agent.config.model}\n"
        f"Agent: {agent.agent_id[:8]}\n"
        f"Type 'exit' or 'quit' to leave | /help for commands",
        title="Welcome",
        border_style="cyan"
    ))

    current_session = session_id

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
            if user_input.lower() in ('exit', 'quit', 'q'):
                break

            if user_input.startswith('/'):
                await _handle_command(orchestrator, agent, user_input)
                continue

            message = AgentMessage(
                role=MessageRole.USER,
                content=user_input,
                agent_id=agent.agent_id
            )

            console.print(f"\n[bold blue]Assistant[/bold blue] [dim](generating...)[/dim]")
            full_response = ""
            token_count = 0

            async for response in orchestrator.send_message(content=message.content, agent_id=agent.agent_id):
                if response.content:
                    full_response += response.content
                    token_count += 1

            # Clear the "generating..." status and show response with markdown
            console.print(f"\r[bold blue]Assistant[/bold blue] [dim]({token_count} tokens)[/dim]")
            try:
                md = Markdown(full_response.strip())
                console.print(md)
            except Exception:
                console.print(full_response.strip())

        except KeyboardInterrupt:
            break
        except EOFError:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    await orchestrator.shutdown()
    console.print("\n[cyan]Goodbye![/cyan]")


async def _handle_command(orchestrator: AIOrchestrator, agent, command: str):
    """Handle slash commands"""
    parts = command[1:].split(' ', 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd in ('help', 'h'):
        _show_help()
    elif cmd in ('provider', 'p'):
        if args:
            try:
                await orchestrator.switch_provider(args.strip())
                console.print(f"[green]Switched to provider: {args}[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
        else:
            providers = list(orchestrator.providers.keys())
            current = orchestrator.active_provider_name
            for p in providers:
                marker = " *" if p == current else ""
                console.print(f"  {p}{marker}")
    elif cmd in ('model', 'm'):
        if args:
            agent.config.model = args.strip()
            console.print(f"[green]Model set to: {args}[/green]")
        else:
            models = await orchestrator.list_models()
            for m in models:
                console.print(f"  {m}")
    elif cmd in ('system', 'sys'):
        if args:
            agent.system_prompt = args
            console.print("[green]System prompt updated[/green]")
        else:
            console.print(f"Current system prompt:\n{agent.system_prompt}")
    elif cmd in ('tools', 't'):
        tools = agent.tool_executor.registry.get_all()
        table = Table(title="Available Tools")
        table.add_column("Name")
        table.add_column("Description")
        for tool in tools:
            table.add_row(tool.name, tool.description)
        console.print(table)
    elif cmd in ('history', 'hist'):
        sessions = await orchestrator.history_manager.list_sessions(limit=20)
        table = Table(title="Recent Sessions")
        table.add_column("Session ID")
        table.add_column("Messages")
        table.add_column("Tokens")
        table.add_column("Last Activity")
        for s in sessions:
            table.add_row(
                s.session_id,
                str(s.message_count),
                str(s.total_tokens),
                datetime.fromtimestamp(s.last_activity).strftime("%Y-%m-%d %H:%M")
            )
        console.print(table)
    elif cmd in ('clear', 'cls'):
        console.clear()
    elif cmd in ('info', 'i'):
        console.print(Panel(
            f"[bold]Session Info[/bold]\n"
            f"Provider: {orchestrator.active_provider_name}\n"
            f"Model: {agent.config.model}\n"
            f"Agent: {agent.agent_id[:8]}\n"
            f"Messages: {len(agent.context.messages)}",
            border_style="cyan"
        ))
    elif cmd in ('save',):
        filepath = args.strip() or f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filepath, 'w', encoding='utf-8') as f:
            for msg in agent.context.messages:
                role = msg.role.value.upper()
                f.write(f"**{role}**: {msg.content}\n\n")
            f.write(f"**ASSISTANT**: ... (conversation end)")
        console.print(f"[green]Saved to {filepath}[/green]")
    else:
        console.print(f"[red]Unknown command: {cmd}. Type /help[/red]")


def _show_help():
    console.print(Panel("""
[bold]Commands:[/bold]
  /help, /h          Show this help
  /provider [name]   Show providers or switch (e.g. /provider local_tinyllama)
  /model [name]      Show models or switch (e.g. /model tinyllama-1.1b-chat-v1.0.Q2_K.gguf)
  /system [prompt]   View or set system prompt
  /tools, /t         List available tools
  /history, /hist    Show recent sessions
  /clear, /cls       Clear screen
  /info, /i          Show session info
  /save [file]       Export conversation to file
  /exit, /quit       Exit chat
""", title="Help", border_style="cyan"))


@cli.command()
@click.option('--provider', '-p', help='AI provider')
@click.option('--model', '-m', help='Model to use')
@click.argument('prompt')
@click.pass_context
def ask(ctx, provider: str, model: str, prompt: str):
    """Ask a single question"""
    asyncio.run(_run_ask(ctx.obj['config_path'], provider, model, prompt))


async def _run_ask(config_path: str, provider: str, model: str, prompt: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()

    if provider:
        await orchestrator.switch_provider(provider)

    agent_config_obj = AgentConfig(model=model or orchestrator.config.default_model)
    agent = await orchestrator.create_agent(
        system_prompt="You are a helpful AI assistant with access to tools. You can run shell commands (dir, ls, cd, type, etc.), read/write files, search the web, and more. When asked to inspect the system, use shell tools. Answer concisely and accurately in Russian.",
        agent_config=asdict(agent_config_obj)
    )

    message = AgentMessage(role=MessageRole.USER, content=prompt, agent_id=agent.agent_id)
    full_response = ""

    console.print(f"[bold blue]Assistant[/bold blue]")
    async for response in orchestrator.send_message(content=message.content, agent_id=agent.agent_id):
        if response.content:
            full_response += response.content
            console.print(response.content, end="", highlight=False)

    console.print()
    await orchestrator.shutdown()


@cli.command()
@click.pass_context
def providers(ctx):
    """List available providers"""
    asyncio.run(_run_providers(ctx.obj['config_path']))


async def _run_providers(config_path: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()

    table = Table(title="AI Providers")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Model")
    table.add_column("Priority")
    table.add_column("Status")

    health = await orchestrator.health_check()

    for name, provider in orchestrator.orchestrator.providers.items():
        marker = " *" if name == orchestrator.active_provider_name else ""
        status = "[OK]" if health.get(name) else "[!]"
        table.add_row(
            f"{name}{marker}",
            provider.type,
            provider.config.model,
            str(provider.config.priority),
            status
        )

    console.print(table)
    await orchestrator.shutdown()


@cli.command()
@click.argument('provider')
@click.option('--model', '-m', help='Model to use')
@click.pass_context
def switch(ctx, provider: str, model: str):
    """Switch active provider"""
    asyncio.run(_run_switch(ctx.obj['config_path'], provider, model))


async def _run_switch(config_path: str, provider: str, model: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()
    await orchestrator.switch_provider(provider)
    if model:
        orchestrator.config.default_model = model
    console.print(f"[green]Active provider: {orchestrator.active_provider_name}[/green]")
    console.print(f"[green]Default model: {orchestrator.config.default_model}[/green]")
    await orchestrator.shutdown()


@cli.command()
@click.pass_context
def config(ctx):
    """Show current configuration"""
    config = load_config(ctx.obj['config_path'])

    console.print(Panel.fit(
        f"Config: {get_default_config_path()}\n"
        f"Data dir: {config.data_dir}\n"
        f"Active provider: {config.active_provider}\n"
        f"Default model: {config.default_model}\n"
        f"Log level: {config.log_level}",
        title="Configuration",
        border_style="cyan"
    ))


@cli.command()
@click.option('--provider', '-p', help='Provider to list models from')
@click.pass_context
def models(ctx, provider: str):
    """List available models"""
    asyncio.run(_run_models(ctx.obj['config_path'], provider))


async def _run_models(config_path: str, provider: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()
    models = await orchestrator.list_models(provider)

    table = Table(title=f"Models{' for ' + provider if provider else ''}")
    table.add_column("Model")
    for m in models:
        table.add_row(m)
    console.print(table)
    await orchestrator.shutdown()


@cli.command()
@click.option('--name', '-n', help='Session name')
@click.pass_context
def new_session(ctx, name: str):
    """Create new session"""
    session_id = str(uuid.uuid4())[:8]
    console.print(f"[green]Created session: {session_id}[/green]")


@cli.command()
@click.argument('session_id')
@click.pass_context
def resume(ctx, session_id: str):
    """Resume a session"""
    asyncio.run(_run_resume(ctx.obj['config_path'], session_id))


async def _run_resume(config_path: str, session_id: str):
    orchestrator = AIOrchestrator(config_path=config_path)
    await orchestrator.initialize()

    session = await orchestrator.history_manager.get_session(session_id)
    if not session:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return

    # Load history and continue
    messages = await orchestrator.history_manager.get_messages_for_context(session_id)

    agent = await orchestrator.create_agent()
    orchestrator.current_session_id = session_id

    console.print(Panel.fit(
        f"Resumed session: {session_id}\n"
        f"Messages: {session.message_count}\n"
        f"Tokens: {session.total_tokens}",
        title="Session Resumed",
        border_style="green"
    ))

    # Chat loop
    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
            if user_input.lower() in ('exit', 'quit', 'q'):
                break

            message = AgentMessage(role=MessageRole.USER, content=user_input, agent_id=agent.agent_id)
            async for response in orchestrator.send_message(content=message.content, agent_id=agent.agent_id):
                if response.content:
                    console.print(response.content, end="", highlight=False)
            console.print()

        except KeyboardInterrupt:
            break
        except EOFError:
            break

    await orchestrator.shutdown()



@cli.command()
@click.option('--host', default='0.0.0.0', help='Bind address')
@click.option('--port', default=8080, help='Port')
@click.option('--provider', '-p', help='Default provider')
@click.pass_context
def serve(ctx, host: str, port: int, provider: str):
    """Start HTTP API server for Android WebView"""
    asyncio.run(_run_serve(ctx.obj['config_path'], host, port, provider))


async def _run_serve(config_path: str, host: str, port: int, provider_name: str):
    from aiohttp import web

    orch = AIOrchestrator(config_path=config_path)
    await orch.initialize()

    if provider_name:
        await orch.switch_provider(provider_name)

    agent = await orch.create_agent(
        system_prompt="You are a helpful AI assistant.",
        agent_config={'enable_tools': False, 'max_tool_iterations': 0}
    )

    async def handle_health(request):
        return web.json_response({"status": "ok", "provider": orch.active_provider_name})

    async def handle_chat(request):
        try:
            data = await request.json()
            text = data.get('message', '')
            if not text:
                return web.json_response({"error": "empty message"}, status=400)

            response_text = ""
            async for chunk in orch.send_message(content=text, agent_id=agent.agent_id):
                if chunk.content:
                    response_text += chunk.content
            return web.json_response({"response": response_text})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_stream(request):
        try:
            data = await request.json()
            text = data.get('message', '')
            if not text:
                return web.json_response({"error": "empty message"}, status=400)

            response = web.StreamResponse(
                status=200,
                reason='OK',
                headers={'Content-Type': 'text/plain'}
            )
            await response.prepare(request)

            async for chunk in orch.send_message(content=text, agent_id=agent.agent_id):
                if chunk.content:
                    await response.write(chunk.content.encode('utf-8'))

            await response.write_eof()
            return response
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_providers(request):
        health = await orch.health_check()
        data = {}
        for name in health:
            prov = orch.orchestrator.providers.get(name)
            data[name] = {
                "active": name == orch.active_provider_name,
                "type": prov.type if prov else "unknown",
                "model": prov.config.model if prov else "",
                "healthy": health[name]
            }
        return web.json_response(data)

    async def handle_switch(request):
        try:
            data = await request.json()
            name = data.get('provider', '')
            if name not in orch.orchestrator.providers:
                return web.json_response({"error": f"provider not found: {name}"}, status=404)
            orch.orchestrator.active_provider = orch.orchestrator.providers[name]
            orch.orchestrator.active_provider_name = name
            return web.json_response({"status": "ok", "provider": name})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_get('/health', handle_health)
    app.router.add_post('/chat', handle_chat)
    app.router.add_post('/stream', handle_stream)
    app.router.add_get('/providers', handle_providers)
    app.router.add_post('/switch', handle_switch)

    logger.info(f"Starting API server on {host}:{port}")
    console.print(f"[green]API server running at http://{host}:{port}[/green]")
    console.print(f"[green]Provider: {orch.active_provider_name}[/green]")
    console.print("[dim]Endpoints: GET /health, POST /chat, POST /stream, GET /providers, POST /switch[/dim]")

    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await orch.shutdown()
        await runner.cleanup()


@cli.command()
@click.option('--host', default='127.0.0.1', help='Bind address')
@click.option('--port', default=8080, help='Port')
@click.option('--no-browser', is_flag=True, help="Don't open browser")
@click.option('--public', is_flag=True, help='Bind to 0.0.0.0 for guest access')
@click.pass_context
def desktop(ctx, host: str, port: int, no_browser: bool, public: bool):
    """Desktop mode: load all characters, start web UI"""
    if public:
        host = '0.0.0.0'
    asyncio.run(_run_desktop(ctx.obj['config_path'], host, port, no_browser))


async def _run_desktop(config_path: str, host: str, port: int, no_browser: bool):
    from aiohttp import web
    from huggingface_hub import HfApi, hf_hub_download

    orch = AIOrchestrator(config_path=config_path)
    await orch.initialize()

    console.print("[bold cyan]Loading AI characters...[/bold cyan]")

    # Check which models are already cached
    hf_api = HfApi()
    cached_models = set()
    for name, cfg in orch.config.providers.items():
        if cfg.type != 'local_ctransformers' or not cfg.enabled:
            continue
        repo = cfg.extra_params.get('hf_repo', '')
        file = cfg.extra_params.get('hf_file', '')
        if repo and file:
            try:
                cache_path = hf_hub_download(repo_id=repo, filename=file, local_files_only=True)
                if cache_path and Path(cache_path).exists():
                    cached_models.add(name)
                    console.print(f"  [green]Cached[/green] {name} ({file})")
                else:
                    console.print(f"  [yellow]Not cached[/yellow] {name} ({file})")
            except Exception:
                console.print(f"  [yellow]Not cached[/yellow] {name}")

    # Load only cached models
    loaded_agents = {}
    for name in cached_models:
        if name in orch.orchestrator.providers:
            continue
        ok = await orch.orchestrator._lazy_load_provider(name)
        if ok:
            console.print(f"  [green]Loaded[/green] {name}")

    # Also ensure the initially loaded provider is included
    for name in list(orch.orchestrator.providers.keys()):
        if name in cached_models or name == orch.config.active_provider:
            cached_models.add(name)

    # Create one agent per loaded provider
    agents = {}
    for name in list(orch.orchestrator.providers.keys()):
        await orch.switch_provider(name)
        agent = await orch.create_agent(
            system_prompt="""You manage this Windows PC via shell. Be terse. No introductions, no explanations.
To run a command, output ONLY a line: CMD: <command>
To hand off, output ONLY a line: DELEGATE: <name>
Then stop. Example:
User: install python
You: CMD: winget install -e --id Python.Python.3

Specialists: assistant, speedy, thinker, analyst, scholar, mistral.
Answer in Russian, but keep it short.""",
            agent_config={'enable_tools': True, 'max_tool_iterations': 10}
        )
        agents[name] = agent
        console.print(f"  [cyan]Agent ready[/cyan] {name}")

    # Restore active provider
    first = list(orch.orchestrator.providers.keys())[0]
    await orch.switch_provider(first)

    loaded_count = len(agents)
    console.print(f"\n[bold green]{loaded_count} characters online![/bold green]")
    if loaded_count < 5:
        console.print(f"[yellow]{5 - loaded_count} not cached yet — will download on first use[/yellow]")

    # HTML UI path
    ui_path = Path(__file__).parent / "desktop_ui.html"
    if not ui_path.exists():
        console.print("[red]desktop_ui.html not found![/red]")
        return

    # HTTP handlers
    async def handle_index(request):
        return web.FileResponse(ui_path)

    async def handle_api_providers(request):
        data = {}
        for name, prov in orch.orchestrator.providers.items():
            cfg = orch.config.providers.get(name)
            cached = name in cached_models
            data[name] = {
                "healthy": True,
                "model": prov.config.model if prov else "",
                "cached": cached,
                "name": cfg.name if cfg else name,
            }
        # Include not-yet-loaded providers
        for name, cfg in orch.config.providers.items():
            if cfg.type == 'local_ctransformers' and name not in data:
                data[name] = {
                    "healthy": False,
                    "model": cfg.model,
                    "cached": False,
                    "name": cfg.name if cfg else name,
                }
        return web.json_response(data)

    async def handle_download(request):
        try:
            body = await request.json()
            name = body.get('provider', '')
            cfg = orch.config.providers.get(name)
            if not cfg or cfg.type != 'local_ctransformers':
                return web.json_response({"error": "invalid provider"}, status=400)

            repo = cfg.extra_params.get('hf_repo', '')
            file = cfg.extra_params.get('hf_file', '')
            if not repo or not file:
                return web.json_response({"error": "no model configured"}, status=400)

            console.print(f"[yellow]Downloading {file}...[/yellow]")
            path = hf_hub_download(repo_id=repo, filename=file)
            console.print(f"[green]Downloaded {file}[/green]")

            # Load the provider
            ok = await orch.orchestrator._lazy_load_provider(name)
            if ok:
                old_active = orch.active_provider_name
                await orch.switch_provider(name)
                agent = await orch.create_agent(
                    system_prompt="""You manage this Windows PC via shell. Be terse. No introductions, no explanations.
To run a command, output ONLY a line: CMD: <command>
To hand off, output ONLY a line: DELEGATE: <name>
Then stop. Example:
User: install python
You: CMD: winget install -e --id Python.Python.3

Specialists: assistant, speedy, thinker, analyst, scholar, mistral.
Answer in Russian, but keep it short.""",
                    agent_config={'enable_tools': True, 'max_tool_iterations': 10}
                )
                agents[name] = agent
                if old_active:
                    await orch.switch_provider(old_active)
                cached_models.add(name)
                return web.json_response({"status": "ok", "path": str(path)})
            else:
                return web.json_response({"error": "failed to load model after download"}, status=500)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_chat(request):
        try:
            body = await request.json()
            text = body.get('message', '')
            provider = body.get('provider', orch.active_provider_name)
            if not text:
                return web.json_response({"error": "empty message"}, status=400)

            agent = agents.get(provider)
            if not agent:
                return web.json_response({"error": f"agent not loaded: {provider}"}, status=404)

            resp = web.StreamResponse(
                status=200,
                headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )

            async def streaming_response():
                response_text = ""
                MAX_ROUNDS = 6
                current_task = text
                current_agent = agent
                try:
                    await resp.prepare(request)
                    for rnd in range(MAX_ROUNDS):
                        round_text = ""
                        async for chunk in orch.send_message(content=current_task, agent_id=current_agent.agent_id):
                            if chunk.content:
                                round_text += chunk.content
                                await resp.write((json.dumps({"token": chunk.content}) + "\n").encode('utf-8'))

                        response_text += round_text

                        # Delegate to another character if requested
                        delegates = DELEGATE_RE.findall(round_text)
                        if delegates:
                            target = delegates[0].strip().lower()
                            pid = CHAR_MAP.get(target)
                            if pid and pid != provider and pid in agents:
                                current_agent = agents[pid]
                                current_task = f"[Handoff] Continue this task: {text}"
                                continue

                        # Execute any shell commands, then feed results back
                        cmds = CMD_RE.findall(round_text)
                        if not cmds:
                            break
                        results = []
                        import subprocess
                        for raw_cmd in cmds:
                            cmd = raw_cmd.strip().strip('`').strip()
                            if not cmd:
                                continue
                            try:
                                proc = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=60)
                                out = (proc.stdout or "") + (proc.stderr or "")
                            except Exception as e:
                                out = str(e)
                            results.append(f"CMD: {cmd}\n{out[:1500]}")
                            await resp.write((json.dumps({"cmd": cmd, "out": out[:1500]}) + "\n").encode('utf-8'))

                        current_task = "Command results:\n" + "\n".join(results) + \
                            "\n\nContinue with next steps if the task is incomplete, otherwise reply with a short summary (no CMD:)."
                        await resp.write((json.dumps({"round": rnd + 1, "status": "continuing"}) + "\n").encode('utf-8'))

                    await resp.write((json.dumps({"done": True, "response": response_text}) + "\n").encode('utf-8'))
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    try:
                        await resp.write((json.dumps({"error": str(e)}) + "\n").encode('utf-8'))
                    except Exception:
                        pass
                finally:
                    await resp.write_eof()

            asyncio.create_task(streaming_response())
            return resp
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_tool_document(request):
        try:
            body = await request.json()
            title = body.get('title', 'untitled')
            content = body.get('content', '')
            format = body.get('format', 'txt')
            ext = {'txt': '.txt', 'md': '.md', 'html': '.html'}.get(format, '.txt')
            path = Path.cwd() / f"{title}{ext}"
            path.write_text(content, encoding='utf-8')
            return web.json_response({"path": str(path)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_tool_email(request):
        try:
            body = await request.json()
            to = body.get('to', '')
            subject = body.get('subject', '')
            msg_body = body.get('body', '')

            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg.set_content(msg_body)
            msg['Subject'] = subject
            msg['To'] = to

            smtp_host = os.environ.get('SMTP_HOST', '')
            smtp_port = int(os.environ.get('SMTP_PORT', '587'))
            smtp_user = os.environ.get('SMTP_USER', '')
            smtp_pass = os.environ.get('SMTP_PASS', '')

            if not smtp_host:
                return web.json_response({"sent": False, "error": "SMTP not configured", "draft": f"To: {to}\nSubject: {subject}\n\n{msg_body}"})

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            return web.json_response({"sent": True, "to": to, "subject": subject})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_tool_shell(request):
        try:
            body = await request.json()
            cmd = body.get('command', '')
            timeout = body.get('timeout', 30)

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return web.json_response({"error": "timeout", "returncode": -1})

            return web.json_response({
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": proc.returncode
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_documents(request):
        import glob as gglob
        data = request.rel_url.query
        path = data.get('path', '')
        if not path:
            docs_dirs = [
                os.path.expanduser("~\\Documents"),
                os.path.expanduser("~\\Desktop"),
                os.path.expanduser("~\\Downloads"),
            ]
            files = []
            for d in docs_dirs:
                if os.path.isdir(d):
                    for f in sorted(os.listdir(d))[:50]:
                        fp = os.path.join(d, f)
                        files.append({"name": f, "path": fp, "size": os.path.getsize(fp) if os.path.isfile(fp) else 0, "dir": os.path.basename(d)})
            return web.json_response({"files": files})
        try:
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(50000)
                return web.json_response({"path": path, "content": content})
            return web.json_response({"error": "not a file"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/providers', handle_api_providers)
    app.router.add_post('/api/chat', handle_api_chat)
    app.router.add_post('/api/download', handle_download)
    app.router.add_get('/api/documents', handle_api_documents)
    app.router.add_post('/api/tool/document', handle_api_tool_document)
    app.router.add_post('/api/tool/email', handle_api_tool_email)
    app.router.add_post('/api/tool/shell', handle_api_tool_shell)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    url = f"http://{host}:{port}"
    console.print(f"\n[bold green]Desktop UI: {url}[/bold green]")
    if not no_browser:
        webbrowser.open(url)

    console.print("[dim]Press Ctrl+C to stop[/dim]")
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await orch.shutdown()
        await runner.cleanup()


if __name__ == '__main__':
    cli()