"""启动器目录布局。

所有可写数据默认放在 %APPDATA%/MCSLauncher（可用环境变量 MCS_DATA_DIR 覆盖），
游戏文件放在数据目录下的 game/ 中，也可以由用户在设置里改到任意位置。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "MCSLauncher"


def data_root() -> Path:
    override = os.environ.get("MCS_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "mcs-launcher"


def default_game_dir() -> Path:
    return data_root() / "game"


def logs_dir() -> Path:
    return data_root() / "logs"


def plugins_dir() -> Path:
    """用户插件目录（可写）。"""
    return data_root() / "plugins"


def plugin_data_dir(plugin_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in plugin_id)
    return data_root() / "plugin-data" / safe


def java_dir() -> Path:
    """官方 Java 插件安装运行时的目录。"""
    return data_root() / "java"


def cache_dir() -> Path:
    return data_root() / "cache"


def official_plugins_dir() -> Path:
    """随启动器分发的官方插件目录（只读）。"""
    return Path(__file__).resolve().parent.parent / "official"


def ensure_layout(game_dir: Path | None = None) -> None:
    for path in (data_root(), logs_dir(), plugins_dir(), java_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
    (game_dir or default_game_dir()).mkdir(parents=True, exist_ok=True)
