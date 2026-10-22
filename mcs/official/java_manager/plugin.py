"""Java 运行时插件入口。

插件同时向宿主注册 `java` 服务，其它插件可以调用：
    service = ctx.services.get("java")
    runtime = service.ensure(21, task)
"""

from __future__ import annotations

from typing import Any

from .manager import JavaManager
from .ui import build_page


class JavaPlugin:
    def __init__(self) -> None:
        self.ctx: Any = None
        self.manager: JavaManager | None = None

    def on_load(self, ctx: Any) -> None:
        self.ctx = ctx
        self.manager = JavaManager(ctx)
        ctx.services.register("java", self.manager)
        ctx.add_page(
            "java",
            "Java 运行时",
            lambda _context=None: build_page(ctx),
            icon="☕",
            subtitle="发现本机 Java，或从 Adoptium 下载 Temurin",
            order=40,
        )
        ctx.logger.info("Java 插件已就绪")

    def ensure(self, major: int, task: Any) -> Any:
        if self.manager is None:
            raise RuntimeError("Java 插件尚未加载")
        return self.manager.ensure(major, task)

    def on_unload(self) -> None:
        if self.ctx is not None:
            self.ctx.services.unregister("java")


def setup(ctx: Any) -> JavaPlugin:
    # 实例在 setup 返回后由宿主调用 on_load，这里不要重复初始化。
    return JavaPlugin()
