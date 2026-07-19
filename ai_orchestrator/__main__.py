"""Main CLI application"""

import asyncio
import json
import logging
import sys
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
        system_prompt=system or "You are a helpful AI assistant with access to tools.",
        model=model or orchestrator.config.default_model,
        enable_tools=True
    )

    agent = await orchestrator.create_agent(
        agent_type="chat",
        config=agent_config,
        system_prompt=system
    )

    console.print(Panel.fit(
        f"[bold cyan]AI Orchestrator Chat[/bold cyan]\n"
        f"Provider: {orchestrator.active_provider_name}\n"
        f"Model: {agent.config.model}\n"
        f"Agent: {agent.agent_id[:8]}\n"
        f"Type 'exit' or 'quit' to leave",
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

            console.print(f"\n[bold blue]Assistant[/bold blue]")
            full_response = ""

            async for response in orchestrator.send_message(agent.agent_id, message):
                if response.content:
                    full_response += response.content
                    console.print(response.content, end="", highlight=False)

            console.print()

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
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")


def _show_help():
    console.print(Panel("""
[bold]Commands:[/bold]
  /help, /h          Show this help
  /provider [name]   Switch AI provider
  /model [name]      Switch model
  /system [prompt]   Set system prompt
  /tools, /t         List available tools
  /history, /hist    Show recent sessions
  /clear, /cls       Clear screen
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

    agent = await orchestrator.create_agent(
        config=AgentConfig(model=model or orchestrator.config.default_model)
    )

    message = AgentMessage(role=MessageRole.USER, content=prompt, agent_id=agent.agent_id)
    full_response = ""

    console.print(f"[bold blue]Assistant[/bold blue]")
    async for response in orchestrator.send_message(agent.agent_id, message):
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
        status = "✓" if health.get(name) else "✗"
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
            async for response in orchestrator.send_message(agent.agent_id, message):
                if response.content:
                    console.print(response.content, end="", highlight=False)
            console.print()

        except KeyboardInterrupt:
            break
        except EOFError:
            break

    await orchestrator.shutdown()


if __name__ == '__main__':
    cli()