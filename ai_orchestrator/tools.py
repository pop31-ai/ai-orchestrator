"""Tool registration and built-in tools"""

from .tools import (
    ShellTool,
    FileReadTool,
    FileWriteTool,
    FileEditTool,
    FileListTool,
    FileGlobTool,
    FileGrepTool,
)


def register_builtin_tools(registry):
    """Register all built-in tools"""
    tools = [
        ShellTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        FileListTool(),
        FileGlobTool(),
        FileGrepTool(),
    ]

    for tool in tools:
        registry.register(tool, category="builtin")

    # Additional tools could be registered here
    return tools