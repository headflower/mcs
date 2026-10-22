"""插件 API 的公共数据类型（不依赖 PyQt）。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Account:
    """一个正版账户。令牌只保存在本地加密存储中。"""

    id: str
    name: str
    uuid: str
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    kind: str = "microsoft"
    skin_url: str = ""

    @property
    def expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at - 120

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("access_token", None)
        data.pop("refresh_token", None)
        return data


@dataclass
class InstalledVersion:
    """本地已安装的版本。"""

    id: str
    name: str = ""
    type: str = "release"
    loader: str = "vanilla"
    java_major: int = 0
    path: str = ""
    release_time: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id


@dataclass
class GameVersionInfo:
    """Mojang 版本清单中的一项。"""

    id: str
    type: str
    url: str
    release_time: str = ""
    sha1: str = ""


@dataclass
class JavaRuntimeInfo:
    path: str
    version: str = ""
    major: int = 0
    vendor: str = ""
    arch: str = ""
    managed: bool = False

    @property
    def label(self) -> str:
        vendor = f" · {self.vendor}" if self.vendor else ""
        return f"Java {self.major or '?'} ({self.version or 'unknown'}){vendor}"


@dataclass
class LaunchOptions:
    memory_mb: int = 4096
    jvm_args: str = ""
    game_args: str = ""
    width: int = 0
    height: int = 0
    fullscreen: bool = False
    demo: bool = False
    java_path: str = ""
    extra_jvm_args: list[str] = field(default_factory=list)
    extra_game_args: list[str] = field(default_factory=list)


@dataclass
class DownloadItem:
    url: str
    dest: str
    sha1: str = ""
    size: int = 0
    label: str = ""


@dataclass
class ModProject:
    """模组搜索结果的统一结构（Modrinth / CurseForge）。"""

    id: str
    title: str
    description: str = ""
    author: str = ""
    downloads: int = 0
    icon_url: str = ""
    source: str = "modrinth"
    url: str = ""
    categories: list[str] = field(default_factory=list)


@dataclass
class ModFile:
    """可安装的模组文件。"""

    id: str
    name: str
    version: str = ""
    download_url: str = ""
    filename: str = ""
    sha1: str = ""
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    release_type: str = "release"
    source: str = "modrinth"
    project_id: str = ""


@dataclass
class PluginMeta:
    id: str
    name: str
    version: str
    api: int = 1
    kind: str = "python"
    entry: str = ""
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    priority: int = 100
    enabled: bool = True
    builtin: bool = False
    path: str = ""
    abi: int = 0

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.version}"


class TaskError(RuntimeError):
    """插件任务中可展示给用户的错误。"""


class TaskCancelled(Exception):
    """任务被用户取消。"""
