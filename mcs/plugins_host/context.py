"""注入给每个插件的上下文对象。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .. import API_VERSION, __version__
from ..api.types import PluginMeta
from .services import PluginServiceView


class PluginTaskRunner:
    """把插件启动的后台任务登记到宿主，卸载插件时可以统一取消。"""

    def __init__(self, host: Any, plugin_id: str) -> None:
        self._host = host
        self._plugin_id = plugin_id

    def run(self, fn: Any, **kwargs: Any) -> Any:
        handle = self._host.tasks.run(fn, **kwargs)
        self._host.register_plugin_task(self._plugin_id, handle)
        return handle

    def __getattr__(self, name: str) -> Any:
        return getattr(self._host.tasks, name)


class PluginContext:
    def __init__(self, host: Any, meta: PluginMeta) -> None:
        self._host = host
        self.meta = meta
        self.plugin_id = meta.id
        self.plugin_dir = Path(meta.path)
        self.data_dir = host.fs.plugin_data(meta.id)
        self.logger = logging.getLogger(f"mcs.plugin.{meta.id}")
        self.settings = host.settings
        self.accounts = host.accounts
        self.launcher = host.launcher
        self.fs = host.fs
        self.http = host.http
        self.ui = host.ui
        self.tasks = PluginTaskRunner(host, meta.id)
        self.services = PluginServiceView(host.services, meta.id)
        self.api_version = API_VERSION
        self.launcher_version = __version__
        self.java = host.launcher.java
        self.host = host

    def register_hook(
        self, hook: str, callback: Callable[..., Any], *, priority: int = 100
    ) -> int:
        return self._host.hooks.register(
            hook, callback, plugin_id=self.plugin_id, priority=priority
        )

    def add_page(self, *args: Any, **kwargs: Any) -> None:
        if self.ui is None:
            raise RuntimeError("界面尚未就绪，无法注册页面")
        self.ui.add_page(*args, **kwargs)
