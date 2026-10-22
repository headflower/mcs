"""模组下载插件入口。"""

from __future__ import annotations

from typing import Any

from .ui import build_page


class ModDownloadPlugin:
    def __init__(self) -> None:
        self.ctx: Any = None

    def on_load(self, ctx: Any) -> None:
        self.ctx = ctx
        ctx.add_page(
            "mod_download",
            "模组下载",
            lambda _context=None: build_page(ctx),
            icon="▦",
            subtitle="Modrinth / CurseForge · 自动处理前置依赖",
            order=35,
        )
        ctx.logger.info("模组下载插件已就绪")


def setup(ctx: Any) -> ModDownloadPlugin:
    return ModDownloadPlugin()
