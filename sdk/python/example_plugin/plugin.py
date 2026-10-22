"""最小 Python 插件示例：注册页面、钩子、后台任务与文件写入。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mcs.api import HOOK_APP_READY

PLUGIN_ID = "com.example.python"


class ExamplePlugin:
    def __init__(self) -> None:
        self.ctx: Any = None
        self.status: QLabel | None = None
        self.result: QLabel | None = None

    # 生命周期：setup() 返回实例后，宿主调用一次 on_load()。
    def on_load(self, ctx: Any) -> None:
        self.ctx = ctx
        ctx.register_hook(HOOK_APP_READY, self._on_app_ready, priority=500)
        ctx.add_page(
            "sdk_example",
            "插件示例",
            lambda _context=None: self._build_page(),
            icon="✦",
            subtitle="Python SDK · 页面、钩子、任务与文件读写",
            order=500,
        )
        ctx.logger.info("示例插件已加载，数据目录：%s", ctx.data_dir)

    def on_unload(self) -> None:
        if self.ctx:
            self.ctx.logger.info("示例插件已卸载")

    def _on_app_ready(self, **_kwargs: Any) -> None:
        self.ctx.logger.info("收到 app.ready 钩子")
        self.ctx.fs.write_text(
            self.ctx.data_dir / "app-ready.txt",
            "示例插件在界面就绪时写入了这个文件。\n",
        )

    # ---------------------------------------------------------------- UI
    def _build_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("这是一个完全由插件提供的页面")
        title.setObjectName("H2")
        layout.addWidget(title)

        hint = QLabel(
            "插件通过 ctx.add_page(...) 注册页面，通过 ctx.register_hook(...) 接收事件，"
            "并通过 ctx.tasks.run(...) 在后台执行耗时操作。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        self.status = QLabel("尚未执行操作")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        self.result = QLabel("")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)

        row = QHBoxLayout()
        fetch = QPushButton("检查版本清单")
        fetch.clicked.connect(self._fetch_status)
        write = QPushButton("写入插件数据目录")
        write.clicked.connect(self._write_file)
        open_dir = QPushButton("打开数据目录")
        open_dir.clicked.connect(lambda: self.ctx.ui.open_path(self.ctx.data_dir))
        row.addWidget(fetch)
        row.addWidget(write)
        row.addWidget(open_dir)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _fetch_status(self) -> None:
        self.status.setText("请求中…")
        self.ctx.tasks.run(
            self._request_status,
            title="示例插件：检查版本清单",
            on_done=self._show_status,
            on_error=lambda exc: self.status.setText(f"请求失败：{exc}"),
        )

    def _request_status(self, task: Any) -> dict[str, Any]:
        return self.ctx.http.get_json(
            "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
        )

    def _show_status(self, data: Any) -> None:
        self.status.setText("请求成功")
        if isinstance(data, dict):
            latest = data.get("latest") or {}
            self.result.setText(
                f"最新正式版：{latest.get('release', '?')}\n"
                f"最新快照：{latest.get('snapshot', '?')}\n"
                f"版本总数：{len(data.get('versions') or [])}"
            )
        else:
            self.result.setText(str(data))

    def _write_file(self) -> None:
        path = self.ctx.data_dir / "hello.txt"
        self.ctx.fs.write_text(path, "你好，这是插件写入的文件。\n")
        self.ctx.ui.notify("示例插件", f"已写入 {path}")


def setup(ctx: Any) -> ExamplePlugin:
    return ExamplePlugin()
