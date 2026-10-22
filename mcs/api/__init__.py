"""MCS 插件 API（稳定接口层）。

Python 插件通过 manifest 声明依赖 ``mcs.api``，并在入口模块实现
``setup(context)`` / ``teardown()``。这里只定义接口与数据类型，
不包含任何启动器内部实现，因此该包本身可以被独立分发。
"""

from __future__ import annotations

from .hooks import (
    HOOK_ACCOUNT_CHANGED,
    HOOK_APP_CLOSING,
    HOOK_APP_READY,
    HOOK_GAME_VERSION_INSTALLED,
    HOOK_LAUNCH_FINISHED,
    HOOK_LAUNCH_LOG,
    HOOK_LAUNCH_PRE,
    HOOK_LAUNCH_STARTED,
    HOOK_MOD_INSTALLED,
    HOOK_SETTINGS_CHANGED,
    HOOKS,
    HookBus,
)
from .interfaces import (
    IAccountStore,
    IFileSystem,
    IHttpClient,
    ILauncher,
    IPlugin,
    IPluginContext,
    ISettings,
    ITaskHandle,
    ITaskRunner,
    IUiService,
)
from .types import (
    Account,
    DownloadItem,
    GameVersionInfo,
    InstalledVersion,
    JavaRuntimeInfo,
    LaunchOptions,
    ModFile,
    ModProject,
    PluginMeta,
    TaskError,
)

__all__ = [
    "Account",
    "DownloadItem",
    "GameVersionInfo",
    "InstalledVersion",
    "JavaRuntimeInfo",
    "LaunchOptions",
    "ModFile",
    "ModProject",
    "PluginMeta",
    "TaskError",
    "HookBus",
    "HOOKS",
    "HOOK_APP_READY",
    "HOOK_APP_CLOSING",
    "HOOK_ACCOUNT_CHANGED",
    "HOOK_LAUNCH_PRE",
    "HOOK_LAUNCH_STARTED",
    "HOOK_LAUNCH_LOG",
    "HOOK_LAUNCH_FINISHED",
    "HOOK_SETTINGS_CHANGED",
    "HOOK_GAME_VERSION_INSTALLED",
    "HOOK_MOD_INSTALLED",
    "ISettings",
    "IAccountStore",
    "ILauncher",
    "IFileSystem",
    "IHttpClient",
    "IUiService",
    "ITaskRunner",
    "ITaskHandle",
    "IPlugin",
    "IPluginContext",
]
