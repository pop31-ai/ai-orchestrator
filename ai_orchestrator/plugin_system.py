"""
Plugin System with hot-reload.

Plugins are Python files in the `plugins/` directory.
Each plugin defines a class that inherits from `Plugin`.
The PluginManager watches for file changes and hot-reloads automatically.

Usage:
    from ai_orchestrator.plugin_system import PluginManager
    pm = PluginManager("plugins")
    pm.load_all()
    pm.reload("my_plugin")
    pm.unload("my_plugin")
"""

import ast
import importlib.util
import inspect
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class Plugin:
    """Base class for all plugins. Override hooks as needed."""

    name: str = ""
    version: str = "1.0.0"
    description: str = ""

    def __init__(self):
        self.loaded = False
        self._plugin_dir: Optional[Path] = None

    def on_load(self):
        """Called when plugin is loaded. Initialize resources here."""
        pass

    def on_unload(self):
        """Called when plugin is unloaded. Clean up resources here."""
        pass

    def on_message(self, agent: str, message: str, context: Dict) -> Optional[str]:
        """Intercept a message before processing. Return modified message or None."""
        return None

    def on_response(self, agent: str, response: str, context: Dict) -> Optional[str]:
        """Intercept a response before sending. Return modified response or None."""
        return None

    def on_tool(self, agent: str, tool: str, args: Dict, result: Any) -> Any:
        """Intercept tool execution. Return modified result or None."""
        return None

    def get_tools(self) -> List[Dict]:
        """Register additional tools. Each tool is a dict with:
        {"name": str, "description": str, "handler": callable}
        """
        return []


class PluginWrapper:
    """Wraps a plugin module with reload tracking."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem
        self.module = None
        self.instance: Optional[Plugin] = None
        self._mtime: float = 0
        self._spec = None
        self.error: Optional[str] = None

    def is_dirty(self) -> bool:
        return self.path.stat().st_mtime > self._mtime + 0.5

    def load(self) -> bool:
        try:
            # Read the source to find the Plugin subclass
            source = self.path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            # Find all classes that inherit from Plugin
            plugin_classes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == "Plugin":
                            plugin_classes.append(node.name)
                        elif isinstance(base, ast.Attribute) and base.attr == "Plugin":
                            plugin_classes.append(node.name)

            if not plugin_classes:
                self.error = f"No Plugin subclass found in {self.name}"
                logger.warning(self.error)
                return False

            # Import the module
            self._spec = importlib.util.spec_from_file_location(
                f"plugin_{self.name}", self.path
            )
            if self.module:
                # Unload old module
                for cls_name in plugin_classes:
                    if hasattr(self.module, cls_name):
                        old_cls = getattr(self.module, cls_name)
                        if hasattr(old_cls, '_instance'):
                            old_cls._instance.on_unload()

            self.module = importlib.util.module_from_spec(self._spec)
            # Don't add to sys.modules to avoid conflicts
            self._spec.loader.exec_module(self.module)

            # Instantiate the first Plugin subclass found
            for cls_name in plugin_classes:
                cls = getattr(self.module, cls_name)
                if inspect.isclass(cls) and issubclass(cls, Plugin) and cls is not Plugin:
                    self.instance = cls()
                    self.instance.name = self.instance.name or self.name
                    self.instance._plugin_dir = self.path.parent
                    self.instance.on_load()
                    self.instance.loaded = True
                    self._mtime = self.path.stat().st_mtime
                    self.error = None
                    logger.info(f"Plugin loaded: {self.instance.name} v{self.instance.version}")
                    return True

            self.error = f"No valid Plugin subclass instantiated in {self.name}"
            return False

        except Exception as e:
            self.error = f"Failed to load {self.name}: {e}"
            logger.error(self.error)
            return False

    def unload(self):
        if self.instance:
            try:
                self.instance.on_unload()
            except Exception as e:
                logger.error(f"Error unloading {self.name}: {e}")
            self.instance.loaded = False
            self.instance = None
        self.module = None
        logger.info(f"Plugin unloaded: {self.name}")


class PluginManager:
    """Manages all plugins: load, unload, reload, watch."""

    def __init__(self, plugins_dir: str = None):
        self.plugins_dir = Path(plugins_dir or (Path.cwd() / "plugins"))
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._plugins: Dict[str, PluginWrapper] = {}
        self._watcher_thread: Optional[threading.Thread] = None
        self._watching = False
        self._hooks: Dict[str, List[PluginWrapper]] = {
            "message": [],
            "response": [],
            "tool": [],
        }

    # --- Public API ---

    def load_all(self) -> int:
        """Load all .py files from plugins directory. Returns count loaded."""
        count = 0
        for f in sorted(self.plugins_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue  # skip __init__.py, _helpers etc
            if self.load(f.stem):
                count += 1
        return count

    def load(self, name: str) -> bool:
        """Load a single plugin by name."""
        path = self.plugins_dir / f"{name}.py"
        if not path.exists():
            logger.warning(f"Plugin not found: {name}")
            return False

        # Unload existing
        if name in self._plugins:
            self.unload(name)

        wrapper = PluginWrapper(path)
        if wrapper.load():
            self._plugins[name] = wrapper
            self._register_hooks(wrapper)
            return True
        return False

    def unload(self, name: str):
        """Unload a plugin by name."""
        wrapper = self._plugins.pop(name, None)
        if wrapper:
            self._unregister_hooks(wrapper)
            wrapper.unload()

    def reload(self, name: str) -> bool:
        """Reload a single plugin. Returns True if successful."""
        if name in self._plugins:
            self.unload(name)
        return self.load(name)

    def reload_all(self) -> int:
        """Reload all dirty plugins. Returns count reloaded."""
        count = 0
        for name, wrapper in list(self._plugins.items()):
            if wrapper.is_dirty():
                if self.reload(name):
                    count += 1
        return count

    def get_plugin(self, name: str) -> Optional[Plugin]:
        wrapper = self._plugins.get(name)
        return wrapper.instance if wrapper else None

    def list_plugins(self) -> List[Dict]:
        return [
            {
                "name": p.instance.name if p.instance else p.name,
                "version": p.instance.version if p.instance else "?",
                "description": p.instance.description if p.instance else p.error or "?",
                "loaded": p.instance is not None and p.instance.loaded,
                "error": p.error,
            }
            for p in self._plugins.values()
        ]

    def total_plugins(self) -> int:
        return len(self._plugins)

    # --- Hot-reload watcher ---

    def start_watcher(self, interval_sec: float = 3.0):
        """Start background thread that checks for dirty plugins and reloads them."""
        if self._watching:
            return
        self._watching = True

        def _watch():
            while self._watching:
                try:
                    self.reload_all()
                except Exception as e:
                    logger.error(f"Watcher error: {e}")
                time.sleep(interval_sec)

        self._watcher_thread = threading.Thread(target=_watch, daemon=True)
        self._watcher_thread.start()
        logger.info(f"Plugin watcher started (interval={interval_sec}s)")

    def stop_watcher(self):
        self._watching = False

    # --- Hook dispatch ---

    def dispatch_message(self, agent: str, message: str, context: Dict = None) -> str:
        """Run all message hooks. First plugin to return a string wins."""
        for wrapper in self._hooks["message"]:
            if wrapper.instance and wrapper.instance.loaded:
                try:
                    result = wrapper.instance.on_message(agent, message, context or {})
                    if result is not None:
                        return result
                except Exception as e:
                    logger.error(f"Plugin {wrapper.name} on_message error: {e}")
        return message

    def dispatch_response(self, agent: str, response: str, context: Dict = None) -> str:
        """Run all response hooks. First plugin to return a string wins."""
        for wrapper in self._hooks["response"]:
            if wrapper.instance and wrapper.instance.loaded:
                try:
                    result = wrapper.instance.on_response(agent, response, context or {})
                    if result is not None:
                        return result
                except Exception as e:
                    logger.error(f"Plugin {wrapper.name} on_response error: {e}")
        return response

    def dispatch_tool(self, agent: str, tool: str, args: Dict, result: Any) -> Any:
        """Run all tool hooks. First plugin to return non-None wins."""
        for wrapper in self._hooks["tool"]:
            if wrapper.instance and wrapper.instance.loaded:
                try:
                    modified = wrapper.instance.on_tool(agent, tool, args, result)
                    if modified is not None:
                        result = modified
                except Exception as e:
                    logger.error(f"Plugin {wrapper.name} on_tool error: {e}")
        return result

    def get_tools(self) -> List[Dict]:
        """Collect all tools registered by plugins."""
        tools = []
        for wrapper in self._plugins.values():
            if wrapper.instance and wrapper.instance.loaded:
                try:
                    tools.extend(wrapper.instance.get_tools())
                except Exception as e:
                    logger.error(f"Plugin {wrapper.name} get_tools error: {e}")
        return tools

    # --- Internal ---

    def _register_hooks(self, wrapper: PluginWrapper):
        if not wrapper.instance:
            return
        # Check which hooks are implemented (not the default no-op)
        for hook_name, hook_list in self._hooks.items():
            method = getattr(wrapper.instance, f"on_{hook_name}", None)
            if method and self._is_overridden(wrapper.instance, f"on_{hook_name}"):
                hook_list.append(wrapper)

    def _unregister_hooks(self, wrapper: PluginWrapper):
        for hook_list in self._hooks.values():
            if wrapper in hook_list:
                hook_list.remove(wrapper)

    @staticmethod
    def _is_overridden(instance: Plugin, method_name: str) -> bool:
        """Check if the method is actually overridden (not the base class default)."""
        base_fn = Plugin.__dict__.get(method_name)
        inst_fn = instance.__class__.__dict__.get(method_name)
        if base_fn and inst_fn:
            return base_fn is not inst_fn
        return False

    def cleanup(self):
        self.stop_watcher()
        for name in list(self._plugins.keys()):
            self.unload(name)
