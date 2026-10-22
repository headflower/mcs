"""插件宿主：发现、依赖排序、加载 Python / 原生插件、卸载。"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

from ..api.hooks import (
    HOOK_ACCOUNT_CHANGED,
    HOOK_SETTINGS_CHANGED,
    HookBus,
)
from ..api.types import PluginMeta
from ..core.fs import SafeFileSystem
from ..core.net import HttpClient
from ..core.paths import official_plugins_dir, plugins_dir
from ..core.tasks import TaskRunner
from .context import PluginContext
from .manifest import ManifestError, load_manifest
from .services import ServiceRegistry

log = logging.getLogger("mcs.plugins")


@dataclass
class LoadedPlugin:
    meta: PluginMeta
    context: PluginContext | None = None
    module: Any = None
    instance: Any = None
    error: str = ""
    pages: list[str] = field(default_factory=list)


class PluginHost(QObject):
    plugins_changed = pyqtSignal()
    plugin_failed = pyqtSignal(str, str)

    def __init__(self, settings: Any, accounts: Any, launcher: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.accounts = accounts
        self.launcher = launcher
        self.hooks = HookBus()
        self.services = ServiceRegistry()
        self.http = HttpClient(settings)
        self.fs = SafeFileSystem(settings)
        self.tasks = TaskRunner()
        self.ui: Any = None
        self._manifests: list[PluginMeta] = []
        self._loaded: dict[str, LoadedPlugin] = {}
        self._pending_native: list[PluginMeta] = []
        self._kind_handlers: dict[str, Callable[[PluginMeta], Any]] = {}
        self._discovered = False
        self._loading_id: str = ""
        self._discovery_errors: list[tuple[str, str]] = []
        self._plugin_tasks: dict[str, list[Any]] = {}

        launcher.hooks = self.hooks
        launcher.accounts = accounts
        settings.changed.connect(self._on_setting_changed)
        accounts.current_changed.connect(self._on_account_changed)

    @property
    def loading_plugin_id(self) -> str:
        return self._loading_id

    # ------------------------------------------------------------------ ui
    def attach_ui(self, ui: Any) -> None:
        self.ui = ui
        self.tasks.set_dispatch(ui.call_on_ui)

    def _on_setting_changed(self, key: str, value: Any) -> None:
        self.hooks.emit(HOOK_SETTINGS_CHANGED, key=key, value=value)

    def _on_account_changed(self, account: Any) -> None:
        self.hooks.emit(HOOK_ACCOUNT_CHANGED, account=account)

    # ------------------------------------------------------------ discovery
    def discover(self) -> list[PluginMeta]:
        seen: dict[str, PluginMeta] = {}
        disabled = set(self.settings.get("disabled_plugins") or [])
        self._discovery_errors = []
        roots = [(official_plugins_dir(), True), (plugins_dir(), False)]
        for root, builtin in roots:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir() or not (child / "plugin.json").is_file():
                    continue
                try:
                    meta = load_manifest(child, builtin=builtin)
                except ManifestError as exc:
                    log.warning("跳过插件 %s：%s", child.name, exc)
                    self._discovery_errors.append((child.name, str(exc)))
                    self.plugin_failed.emit(child.name, str(exc))
                    continue
                meta.enabled = meta.id not in disabled
                if meta.id in seen:
                    message = f"插件 id 重复：{meta.id}，已忽略 {child}"
                    log.warning(message)
                    self._discovery_errors.append((child.name, message))
                    continue
                seen[meta.id] = meta
        self._manifests = list(seen.values())
        self._discovered = True
        return list(self._manifests)

    def discovery_errors(self) -> list[tuple[str, str]]:
        return list(self._discovery_errors)

    def loaded_plugin(self, plugin_id: str) -> LoadedPlugin | None:
        return self._loaded.get(plugin_id)

    def register_plugin_task(self, plugin_id: str, handle: Any) -> None:
        handles = [item for item in self._plugin_tasks.get(plugin_id, []) if not item.done]
        handles.append(handle)
        self._plugin_tasks[plugin_id] = handles

    def cancel_plugin_tasks(self, plugin_id: str) -> None:
        for handle in self._plugin_tasks.pop(plugin_id, []):
            try:
                handle.mute()
            except Exception:
                pass

    def cancel_all_tasks(self) -> None:
        for plugin_id in list(self._plugin_tasks):
            self.cancel_plugin_tasks(plugin_id)

    def manifests(self) -> list[PluginMeta]:
        if not self._discovered:
            self.discover()
        return list(self._manifests)

    def loaded_plugins(self) -> list[LoadedPlugin]:
        return list(self._loaded.values())

    # --------------------------------------------------------------- loading
    def load_all(self) -> None:
        if not self._discovered:
            self.discover()
        ordered = self._order(self._manifests)
        # 先加载 Python 插件，让“原生接口插件”有机会注册 native loader
        for meta in [m for m in ordered if m.kind == "python" and m.enabled]:
            self._load_python(meta)
        self._pending_native = [m for m in ordered if m.kind == "native" and m.enabled]
        self._load_pending_native()
        self.plugins_changed.emit()

    def _order(self, manifests: list[PluginMeta]) -> list[PluginMeta]:
        by_id = {m.id: m for m in manifests}
        result: list[PluginMeta] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(meta: PluginMeta) -> None:
            if meta.id in visited:
                return
            if meta.id in visiting:
                log.warning("插件依赖循环：%s", meta.id)
                return
            visiting.add(meta.id)
            for dep in meta.dependencies:
                if dep in by_id:
                    visit(by_id[dep])
                elif not dep.startswith("mcs.api"):
                    log.warning("插件 %s 依赖不存在的插件 %s", meta.id, dep)
            visiting.discard(meta.id)
            visited.add(meta.id)
            result.append(meta)

        for meta in sorted(manifests, key=lambda m: (0 if m.builtin else 1, m.priority, m.id)):
            visit(meta)
        return result

    def _module_name(self, plugin_id: str) -> str:
        return "mcs_plugin_" + re.sub(r"[^A-Za-z0-9_]", "_", plugin_id)

    def _load_python(self, meta: PluginMeta) -> None:
        plugin_dir = Path(meta.path)
        entry = plugin_dir / meta.entry
        if not entry.is_file():
            self._fail(meta, f"入口文件不存在：{entry}")
            return
        module_name = self._module_name(meta.id)
        self._loading_id = meta.id
        try:
            if str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))
            # 把插件目录作为一个包加载，入口作为其子模块，这样入口里可以写
            # ``from .installer import ...`` 之类的相对导入。
            import types

            if module_name not in sys.modules:
                package = types.ModuleType(module_name)
                package.__path__ = [str(plugin_dir)]
                package.__package__ = module_name
                sys.modules[module_name] = package
            submodule_name = f"{module_name}.{entry.stem}"
            spec = importlib.util.spec_from_file_location(submodule_name, entry)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载模块：{entry}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[submodule_name] = module
            spec.loader.exec_module(module)
            context = PluginContext(self, meta)
            instance = None
            if hasattr(module, "setup"):
                instance = module.setup(context)
            elif hasattr(module, "Plugin"):
                instance = module.Plugin()
            else:
                raise RuntimeError("插件入口必须提供 setup(context) 或 Plugin 类")
            if instance is not None and hasattr(instance, "on_load"):
                instance.on_load(context)
            loaded = LoadedPlugin(meta=meta, context=context, module=module, instance=instance)
            self._loaded[meta.id] = loaded
            log.info("已加载插件：%s %s", meta.id, meta.version)
        except Exception as exc:
            log.exception("加载插件失败：%s", meta.id)
            self._fail(meta, str(exc))
        finally:
            self._loading_id = ""

    def _load_pending_native(self) -> None:
        still: list[PluginMeta] = []
        for meta in self._pending_native:
            if meta.id in self._loaded:
                continue
            handler = self._kind_handlers.get(meta.kind)
            if handler is None:
                still.append(meta)
                continue
            self._loading_id = meta.id
            try:
                context = PluginContext(self, meta)
                instance = handler(meta)
                if instance is None:
                    raise RuntimeError("原生插件加载器返回空对象")
                if hasattr(instance, "on_load"):
                    instance.on_load(context)
                self._loaded[meta.id] = LoadedPlugin(meta=meta, context=context, instance=instance)
                log.info("已加载原生插件：%s %s", meta.id, meta.version)
            except Exception as exc:
                log.exception("加载原生插件失败：%s", meta.id)
                self._fail(meta, str(exc))
            finally:
                self._loading_id = ""
        self._pending_native = still
        for meta in still:
            self._fail(meta, "未找到可用的原生插件加载器。请启用官方“原生接口”插件。")

    def _fail(self, meta: PluginMeta, message: str) -> None:
        self.cancel_plugin_tasks(meta.id)
        self.services.unregister_owner(meta.id)
        self._loaded[meta.id] = LoadedPlugin(meta=meta, error=message)
        self.plugin_failed.emit(meta.id, message)

    def register_kind_handler(self, kind: str, factory: Callable[[PluginMeta], Any]) -> None:
        self._kind_handlers[kind] = factory
        self._load_pending_native()

    # --------------------------------------------------------------- unload
    def unload_all(self) -> None:
        for loaded in reversed(list(self._loaded.values())):
            meta = loaded.meta
            self.cancel_plugin_tasks(meta.id)
            try:
                if loaded.instance is not None and hasattr(loaded.instance, "on_unload"):
                    loaded.instance.on_unload()
                if loaded.module is not None and hasattr(loaded.module, "teardown"):
                    loaded.module.teardown()
            except Exception:
                log.exception("卸载插件失败：%s", meta.id)
            if loaded.context is not None and self.ui is not None:
                try:
                    self.ui.remove_pages_of(meta.id)
                except Exception:
                    pass
            self.hooks.unregister_plugin(meta.id)
        self.cancel_all_tasks()
        self._loaded.clear()
        self._pending_native.clear()
        self.plugins_changed.emit()

    def reload(self) -> None:
        """重新扫描并加载所有插件（用于开发调试）。"""
        self.unload_all()
        self._discovered = False
        self._manifests = []
        self.discover()
        self.load_all()

    # -------------------------------------------------------------- helpers
    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        disabled = set(self.settings.get("disabled_plugins") or [])
        if enabled:
            disabled.discard(plugin_id)
        else:
            disabled.add(plugin_id)
        self.settings.set("disabled_plugins", sorted(disabled))
        self.plugins_changed.emit()
