"""
Example Plugin — demonstrates all hooks.
Drop this file in the plugins/ directory.
It will be auto-loaded and hot-reloaded.
"""

from ai_orchestrator.plugin_system import Plugin


class ExamplePlugin(Plugin):
    name = "example"
    version = "1.0.0"
    description = "Example plugin that logs all messages and adds a timestamp"

    def on_load(self):
        print(f"[Plugin] {self.name} loaded!")

    def on_unload(self):
        print(f"[Plugin] {self.name} unloaded!")

    def on_message(self, agent: str, message: str, context: dict) -> str:
        """Pass through unchanged"""
        return message

    def on_response(self, agent: str, response: str, context: dict) -> str:
        """Simply pass through — no modification"""
        return response

    def get_tools(self) -> list:
        return [
            {
                "name": "plugin_info",
                "description": "Show information about currently loaded plugins",
                "handler": self._tool_plugin_info,
            }
        ]

    async def _tool_plugin_info(self, args: dict) -> dict:
        """Return info about loaded plugins"""
        pm = getattr(self, '_plugin_manager', None)
        if pm:
            return {"plugins": pm.list_plugins()}
        return {"plugins": [], "note": "plugin_manager not available"}
