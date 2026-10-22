"""插件可见的服务接口。

这些 Protocol 仅用于文档与类型提示；插件拿到的是启动器注入的具体对象。
所有跨线程 UI 操作必须通过 ``IUiService.call_on_ui``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from .types import Account, DownloadItem, InstalledVersion, JavaRuntimeInfo, LaunchOptions, PluginMeta


@runtime_checkable
class ISettings(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def all(self) -> dict[str, Any]: ...
    @property
    def game_dir(self) -> Path: ...


@runtime_checkable
class IAccountStore(Protocol):
    @property
    def current(self) -> Account | None: ...
    @property
    def accounts(self) -> list[Account]: ...
    def set_current(self, account_id: str) -> None: ...
    def remove(self, account_id: str) -> None: ...
    def open_login(self) -> None:
        """打开正版登录窗口（由界面层实现）。"""
        ...


@runtime_checkable
class ILauncher(Protocol):
    def versions(self, refresh: bool = False) -> list[InstalledVersion]: ...
    def refresh_versions(self) -> list[InstalledVersion]: ...
    def launch(self, version_id: str, options: LaunchOptions | None = None) -> bool: ...
    def stop(self) -> None: ...
    @property
    def running(self) -> bool: ...
    def build_command(self, version_id: str, options: LaunchOptions | None = None) -> list[str]:
        """只构建命令而不启动，便于插件调试。"""
        ...


@runtime_checkable
class IFileSystem(Protocol):
    """读取权限覆盖整个磁盘；写入仅限游戏目录与启动器数据目录。"""

    @property
    def game_dir(self) -> Path: ...
    @property
    def data_dir(self) -> Path: ...

    def read_text(self, path: str | Path, encoding: str = "utf-8") -> str: ...
    def read_bytes(self, path: str | Path) -> bytes: ...
    def read_json(self, path: str | Path) -> Any: ...
    def write_text(self, path: str | Path, text: str, encoding: str = "utf-8") -> Path: ...
    def write_bytes(self, path: str | Path, data: bytes) -> Path: ...
    def write_json(self, path: str | Path, obj: Any) -> Path: ...
    def ensure_dir(self, path: str | Path) -> Path: ...
    def exists(self, path: str | Path) -> bool: ...
    def delete(self, path: str | Path, recursive: bool = False) -> None: ...
    def list_dir(self, path: str | Path) -> list[Path]: ...
    def plugin_data(self, plugin_id: str) -> Path: ...


@runtime_checkable
class IHttpClient(Protocol):
    def get_json(self, url: str, **params: Any) -> Any: ...
    def get_text(self, url: str, **params: Any) -> str: ...
    def download(
        self,
        url: str,
        dest: str | Path,
        *,
        sha1: str = "",
        expected_size: int = 0,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Any = None,
    ) -> Path: ...
    def download_many(
        self,
        items: Iterable[DownloadItem],
        *,
        workers: int = 6,
        progress: Callable[[int, int, str], None] | None = None,
        cancel: Any = None,
    ) -> list[Path]: ...


@runtime_checkable
class IUiService(Protocol):
    @property
    def main_window(self) -> Any: ...
    def add_page(
        self,
        page_id: str,
        title: str,
        factory: Callable[[IPluginContext], Any],
        *,
        icon: str = "",
        subtitle: str = "",
        order: int = 100,
    ) -> None: ...
    def remove_page(self, page_id: str) -> None: ...
    def open_page(self, page_id: str) -> None: ...
    def notify(self, title: str, message: str, level: str = "info") -> None: ...
    def show_error(self, title: str, message: str, details: str = "", *, hint: str = "") -> Any: ...
    def call_on_ui(self, fn: Callable[[], Any]) -> None: ...
    def open_path(self, path: str | Path) -> None: ...
    def confirm(self, title: str, text: str) -> bool: ...
    def open_login(self) -> None: ...
    def set_status(self, text: str) -> None: ...


@runtime_checkable
class ITaskHandle(Protocol):
    @property
    def cancel_event(self) -> Any: ...
    def cancel(self) -> None: ...
    @property
    def cancelled(self) -> bool: ...


@runtime_checkable
class ITaskRunner(Protocol):
    def run(
        self,
        fn: Callable[[ITaskHandle], Any],
        *,
        title: str = "",
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ITaskHandle: ...


@runtime_checkable
class IPluginContext(Protocol):
    plugin_id: str
    plugin_dir: Path
    data_dir: Path
    logger: Any
    settings: ISettings
    accounts: IAccountStore
    launcher: ILauncher
    fs: IFileSystem
    http: IHttpClient
    ui: IUiService
    tasks: ITaskRunner
    services: dict[str, Any]
    api_version: int
    launcher_version: str
    meta: PluginMeta
    java: Any

    def register_hook(self, hook: str, callback: Callable[..., Any], *, priority: int = 100) -> int: ...
    def add_page(self, *args: Any, **kwargs: Any) -> None:
        """IUiService.add_page 的快捷方式。"""
        ...


@runtime_checkable
class IPlugin(Protocol):
    def on_load(self, context: IPluginContext) -> None: ...
    def on_unload(self) -> None: ...


class PluginBase:
    """Python 插件可选的基类。"""

    def on_load(self, context: IPluginContext) -> None:  # noqa: D401
        self.context = context

    def on_unload(self) -> None:
        pass
