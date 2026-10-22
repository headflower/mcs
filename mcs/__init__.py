"""MCS Launcher —— 一个核心极简、功能全靠插件的 Minecraft 启动器。"""

from __future__ import annotations

APP_NAME = "MCS Launcher"
ORG_NAME = "MCS"
__version__ = "1.0.2"
API_VERSION = 1

# Minecraft 启动时写入的用户代理标识
MINECRAFT_USER_AGENT = f"MCSLauncher/{__version__}"

__all__ = ["APP_NAME", "ORG_NAME", "API_VERSION", "__version__", "MINECRAFT_USER_AGENT"]
