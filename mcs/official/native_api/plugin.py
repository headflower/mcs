"""原生插件接口（C / C++）——以普通 Python 插件的形式提供。"""

from __future__ import annotations

from typing import Any

from .native_loader import NativePluginLoader


class NativeApiPlugin:
    def __init__(self) -> None:
        self.ctx: Any = None

    def on_load(self, ctx: Any) -> None:
        self.ctx = ctx
        ctx.host.register_kind_handler("native", NativePluginLoader)
        ctx.logger.info("原生插件接口已注册（C ABI 1）")


def setup(ctx: Any) -> NativeApiPlugin:
    return NativeApiPlugin()
