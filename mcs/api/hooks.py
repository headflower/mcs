"""插件钩子总线。"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger("mcs.hooks")

HOOK_APP_READY = "app.ready"
HOOK_APP_CLOSING = "app.closing"
HOOK_ACCOUNT_CHANGED = "account.changed"
HOOK_LAUNCH_PRE = "launch.pre"
HOOK_LAUNCH_STARTED = "launch.started"
HOOK_LAUNCH_LOG = "launch.log"
HOOK_LAUNCH_FINISHED = "launch.finished"
HOOK_SETTINGS_CHANGED = "settings.changed"
HOOK_GAME_VERSION_INSTALLED = "game.version_installed"
HOOK_MOD_INSTALLED = "mod.installed"

HOOKS: dict[str, str] = {
    HOOK_APP_READY: "界面就绪，插件可以注册页面/启动后台任务。参数：host, window",
    HOOK_APP_CLOSING: "启动器即将退出。参数：host",
    HOOK_ACCOUNT_CHANGED: "当前账户改变。参数：account（可能为 None）",
    HOOK_LAUNCH_PRE: "构建启动命令后、进程启动前。参数：context（可修改 command/env）",
    HOOK_LAUNCH_STARTED: "游戏进程已启动。参数：context, pid",
    HOOK_LAUNCH_LOG: "游戏输出一行日志。参数：line",
    HOOK_LAUNCH_FINISHED: "游戏进程结束。参数：exit_code",
    HOOK_SETTINGS_CHANGED: "设置项改变。参数：key, value",
    HOOK_GAME_VERSION_INSTALLED: "插件安装完一个游戏版本。参数：version_id",
    HOOK_MOD_INSTALLED: "插件安装完一个模组。参数：path, project",
}

HookCallback = Callable[..., Any]


class HookBus:
    """按优先级调用回调；单个插件抛异常不会影响其它插件。"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[int, int, str, HookCallback]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._seq = 0

    def register(
        self,
        hook: str,
        callback: HookCallback,
        *,
        plugin_id: str = "",
        priority: int = 100,
    ) -> int:
        with self._lock:
            self._seq += 1
            token = self._seq
            self._hooks[hook].append((priority, token, plugin_id, callback))
            self._hooks[hook].sort(key=lambda item: (item[0], item[1]))
        return token

    def unregister(self, token: int) -> None:
        with self._lock:
            for items in self._hooks.values():
                for i, (_, tok, _, _) in enumerate(items):
                    if tok == token:
                        items.pop(i)
                        return

    def unregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for items in self._hooks.values():
                items[:] = [item for item in items if item[2] != plugin_id]

    def emit(self, hook: str, **kwargs: Any) -> list[Any]:
        with self._lock:
            callbacks = [(pid, cb) for _, _, pid, cb in self._hooks.get(hook, [])]
        results: list[Any] = []
        for plugin_id, callback in callbacks:
            try:
                results.append(callback(**kwargs))
            except Exception:
                log.exception("插件 %s 的钩子 %s 执行失败", plugin_id or "<anonymous>", hook)
        return results

    def count(self, hook: str | None = None) -> int:
        with self._lock:
            if hook is None:
                return sum(len(v) for v in self._hooks.values())
            return len(self._hooks.get(hook, []))
