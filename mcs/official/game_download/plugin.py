"""游戏下载插件入口。"""

from __future__ import annotations

from typing import Any

from .ui import build_page


class GameDownloadPlugin:
    def __init__(self) -> None:
        self.ctx: Any = None

    def on_load(self, ctx: Any) -> None:
        self.ctx = ctx
        ctx.add_page(
            "game_download",
            "下载游戏",
            lambda _context=None: build_page(ctx),
            icon="⬇",
            subtitle="安装原版与 Forge / NeoForge / Fabric / Quilt",
            order=30,
        )
        ctx.logger.info("游戏下载插件已就绪")


def setup(ctx: Any) -> GameDownloadPlugin:
    # 实例在 setup 返回后由宿主调用 on_load，这里不要重复初始化。
    return GameDownloadPlugin()
