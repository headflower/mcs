"""游戏下载页面：原版与模组加载器。"""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mcs.ui.widgets import Card, Pill

from . import installer


class TaskPanel(QWidget):
    """统一的安装进度区。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.cancel = QPushButton("取消")
        self.cancel.setObjectName("Ghost")
        self.cancel.setFixedWidth(72)
        self.cancel.hide()
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.status, 0)
        layout.addWidget(self.cancel, 0)

    def reset(self) -> None:
        self.bar.hide()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.status.setText("")
        self.cancel.hide()

    def set_progress(self, done: int, total: int, message: str) -> None:
        self.bar.show()
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, int(done * 1000 / total)))
            self.status.setText(f"{message} · {done / 1048576:.1f}/{total / 1048576:.1f} MB")
        else:
            self.bar.setRange(0, 0)
            self.status.setText(message)

    def set_text(self, text: str) -> None:
        self.status.setText(text)


class VanillaTab(QWidget):
    def __init__(
        self,
        ctx: Any,
        on_status: Callable[[str], None],
        on_manifest: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        super().__init__()
        self.ctx = ctx
        self.on_status = on_status
        self.on_manifest = on_manifest
        self.manifest: dict[str, Any] | None = None
        self.rows: list[dict[str, Any]] = []
        self.task = None
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索版本号，例如 1.20.1")
        self.search.setClearButtonEnabled(True)
        self.kind = QComboBox()
        self.kind.addItem("正式版", "release")
        self.kind.addItem("快照", "snapshot")
        self.kind.addItem("全部版本", "all")
        self.refresh_btn = QPushButton("刷新清单")
        self.refresh_btn.setObjectName("Ghost")
        top.addWidget(self.search, 1)
        top.addWidget(self.kind)
        top.addWidget(self.refresh_btn)
        root.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["版本", "类型", "发布时间", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(lambda _: self.start_install())
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.hint = QLabel("选择版本后点击安装；首次安装会下载完整资源，耗时较长。")
        self.hint.setObjectName("Muted")
        self.install_btn = QPushButton("安装所选版本")
        self.install_btn.setEnabled(False)
        bottom.addWidget(self.hint, 1)
        bottom.addWidget(self.install_btn)
        root.addLayout(bottom)

        self.panel = TaskPanel()
        root.addWidget(self.panel)

        self.search.textChanged.connect(self._apply_filter)
        self.kind.currentIndexChanged.connect(self._apply_filter)
        self.refresh_btn.clicked.connect(lambda: self.reload(force=True))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.install_btn.clicked.connect(self.start_install)
        self.panel.cancel.clicked.connect(self._cancel)

    # ---------------------------------------------------------------- data
    def reload(self, *, force: bool = False) -> None:
        if self.task is not None:
            return
        self.refresh_btn.setEnabled(False)
        self.on_status("正在获取版本清单…")
        self.task = self.ctx.tasks.run(
            lambda task: installer.fetch_manifest(self.ctx, force=force),
            title="获取版本清单",
            on_done=self._loaded,
            on_error=self._failed,
            on_status=self.panel.set_text,
        )

    def _loaded(self, manifest: Any) -> None:
        self.task = None
        self.refresh_btn.setEnabled(True)
        if not isinstance(manifest, dict):
            self.on_status("版本清单格式异常")
            return
        self.manifest = manifest
        self.rows = list(manifest.get("versions") or [])
        self._apply_filter()
        if self.on_manifest is not None:
            self.on_manifest(self.rows)
        self.on_status(f"版本清单已更新，共 {len(self.rows)} 个版本")

    def _failed(self, exc: BaseException) -> None:
        self.task = None
        self.refresh_btn.setEnabled(True)
        self.panel.reset()
        self.on_status("获取版本清单失败")
        self.ctx.ui.notify("获取版本清单失败", str(exc), "error")

    def _filtered(self) -> list[dict[str, Any]]:
        text = self.search.text().strip().lower()
        kind = str(self.kind.currentData())
        result = []
        for row in self.rows:
            if kind != "all" and row.get("type") != kind:
                continue
            if text and text not in str(row.get("id", "")).lower():
                continue
            result.append(row)
        return result

    def _apply_filter(self) -> None:
        rows = self._filtered()
        self.table.setRowCount(0)
        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            version_id = str(row.get("id"))
            self.table.setItem(index, 0, QTableWidgetItem(version_id))
            type_name = {"release": "正式版", "snapshot": "快照", "old_beta": "旧 Beta", "old_alpha": "旧 Alpha"}.get(
                str(row.get("type")), str(row.get("type"))
            )
            self.table.setItem(index, 1, QTableWidgetItem(type_name))
            self.table.setItem(index, 2, QTableWidgetItem(str(row.get("releaseTime", ""))[:10]))
            installed = installer.is_installed(self.ctx, version_id)
            item = QTableWidgetItem("已安装" if installed else "未安装")
            if installed:
                item.setForeground(Qt.GlobalColor.green)
            self.table.setItem(index, 3, item)
        self._selection_changed()

    def _selected_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.text() if item else ""

    def _selection_changed(self) -> None:
        version_id = self._selected_id()
        self.install_btn.setEnabled(bool(version_id) and self.task is None)
        self.install_btn.setText(f"安装 {version_id}" if version_id else "安装所选版本")

    # --------------------------------------------------------------- install
    def start_install(self) -> None:
        if self.task is not None:
            return
        version_id = self._selected_id()
        if not version_id:
            return
        if installer.is_installed(self.ctx, version_id):
            if not self.ctx.ui.confirm("重新安装", f"{version_id} 已安装，仍要重新下载并覆盖吗？"):
                return
        self.task = self.ctx.tasks.run(
            lambda task: installer.install_vanilla(self.ctx, version_id, task),
            title=f"安装 {version_id}",
            on_done=self._installed,
            on_error=self._failed_install,
            on_progress=self.panel.set_progress,
            on_status=self.panel.set_text,
            on_cancelled=self._cancel_done,
        )
        self.panel.bar.show()
        self.panel.bar.setRange(0, 0)
        self.panel.cancel.show()
        self.install_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.on_status(f"正在安装 {version_id}…")

    def _installed(self, version_id: Any) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(bool(self._selected_id()))
        self.refresh_btn.setEnabled(True)
        self._apply_filter()
        self.on_status(f"{version_id} 已安装")
        self.ctx.ui.notify("安装完成", f"Minecraft {version_id} 已准备好，可以回到主页启动。", "success")

    def _failed_install(self, exc: BaseException) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(bool(self._selected_id()))
        self.refresh_btn.setEnabled(True)
        self.on_status("安装失败")
        self.ctx.ui.notify("安装失败", str(exc), "error")

    def _cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.panel.set_text("正在取消…")

    def _cancel_done(self) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(bool(self._selected_id()))
        self.refresh_btn.setEnabled(True)
        self.on_status("已取消安装")


class LoaderTab(QWidget):
    LOADERS = (
        ("Fabric", "fabric"),
        ("Forge", "forge"),
        ("NeoForge", "neoforge"),
        ("Quilt", "quilt"),
    )

    def __init__(self, ctx: Any, on_status: Callable[[str], None]) -> None:
        super().__init__()
        self.ctx = ctx
        self.on_status = on_status
        self.task = None
        self.version_task = None
        self._request = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro = QLabel(
            "选择 Minecraft 版本与加载器版本。安装时会自动补齐原版、依赖库和需要的 Java，"
            "Forge / NeoForge 的安装处理器也会自动执行。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        root.addWidget(intro)

        grid = QHBoxLayout()
        grid.setSpacing(10)
        self.mc = QComboBox()
        self.mc.setMinimumWidth(140)
        self.loader = QComboBox()
        for name, key in self.LOADERS:
            self.loader.addItem(name, key)
        self.loader_version = QComboBox()
        self.loader_version.setMinimumWidth(180)
        grid.addWidget(self._label("Minecraft"))
        grid.addWidget(self.mc, 1)
        grid.addWidget(self._label("加载器"))
        grid.addWidget(self.loader)
        grid.addWidget(self._label("加载器版本"))
        grid.addWidget(self.loader_version, 1)
        self.reload_btn = QPushButton("刷新")
        self.reload_btn.setObjectName("Ghost")
        grid.addWidget(self.reload_btn)
        root.addLayout(grid)

        self.info = QLabel("")
        self.info.setObjectName("Muted")
        root.addWidget(self.info)

        bottom = QHBoxLayout()
        self.install_btn = QPushButton("安装加载器")
        self.install_btn.setEnabled(False)
        bottom.addStretch(1)
        bottom.addWidget(self.install_btn)
        root.addLayout(bottom)
        root.addStretch(1)

        self.panel = TaskPanel()
        root.addWidget(self.panel)

        self.mc.currentIndexChanged.connect(self._refresh_loader_versions)
        self.loader.currentIndexChanged.connect(self._refresh_loader_versions)
        self.reload_btn.clicked.connect(self._refresh_loader_versions)
        self.install_btn.clicked.connect(self.start_install)
        self.panel.cancel.clicked.connect(self._cancel)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Muted")
        return label

    def set_versions(self, versions: list[dict[str, Any]]) -> None:
        current = self.mc.currentText()
        self.mc.blockSignals(True)
        self.mc.clear()
        for row in versions:
            if row.get("type") != "release":
                continue
            self.mc.addItem(str(row.get("id")))
        if current:
            index = self.mc.findText(current)
            if index >= 0:
                self.mc.setCurrentIndex(index)
        self.mc.blockSignals(False)
        self._refresh_loader_versions()

    def _refresh_loader_versions(self) -> None:
        mc = self.mc.currentText().strip()
        loader = str(self.loader.currentData())
        if not mc:
            return
        self._request += 1
        request = self._request
        self.loader_version.clear()
        self.loader_version.addItem("正在获取…", "")
        self.install_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.info.setText(f"正在查询 {loader} 支持的版本…")

        def work(task: Any) -> list[str]:
            if loader == "forge":
                return installer.forge_versions(self.ctx, mc)
            if loader == "fabric":
                return installer.fabric_loader_versions(self.ctx, mc)
            if loader == "quilt":
                return installer.quilt_loader_versions(self.ctx, mc)
            return installer.neoforge_versions(self.ctx, mc)

        self.version_task = self.ctx.tasks.run(
            work,
            title="查询加载器版本",
            on_done=lambda data: self._versions_loaded(request, loader, data),
            on_error=lambda exc: self._versions_failed(request, exc),
        )

    def _versions_loaded(self, request: int, loader: str, data: Any) -> None:
        if request != self._request:
            return
        self.version_task = None
        self.reload_btn.setEnabled(True)
        self.loader_version.clear()
        if not data:
            self.loader_version.addItem("没有可用版本", "")
            self.info.setText(f"{loader} 没有找到适配该 Minecraft 的版本。")
            return
        for version in data:
            self.loader_version.addItem(str(version), str(version))
        self.install_btn.setEnabled(True)
        self.info.setText(f"共 {len(data)} 个 {loader} 版本，默认选择最新版。")

    def _versions_failed(self, request: int, exc: BaseException) -> None:
        if request != self._request:
            return
        self.version_task = None
        self.reload_btn.setEnabled(True)
        self.loader_version.clear()
        self.loader_version.addItem("获取失败", "")
        self.info.setText(str(exc))
        self.install_btn.setEnabled(False)

    def start_install(self) -> None:
        if self.task is not None:
            return
        mc = self.mc.currentText().strip()
        loader = str(self.loader.currentData())
        version = str(self.loader_version.currentData() or "")
        if not mc or not version:
            return
        funcs = {
            "fabric": installer.install_fabric,
            "quilt": installer.install_quilt,
            "forge": installer.install_forge,
            "neoforge": installer.install_neoforge,
        }
        func = funcs[loader]
        self.task = self.ctx.tasks.run(
            lambda task: func(self.ctx, mc, version, task),
            title=f"安装 {loader} {version}",
            on_done=self._installed,
            on_error=self._failed,
            on_progress=self.panel.set_progress,
            on_status=self.panel.set_text,
            on_cancelled=self._cancel_done,
        )
        self.panel.bar.show()
        self.panel.bar.setRange(0, 0)
        self.panel.cancel.show()
        self.install_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.on_status(f"正在安装 {loader} {version}…")

    def _installed(self, version_id: Any) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.on_status(f"{version_id} 安装完成")
        self.ctx.ui.notify(
            "加载器安装完成",
            f"{version_id} 已准备好，可以在主页的版本下拉框中选择它。",
            "success",
        )

    def _failed(self, exc: BaseException) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.on_status("加载器安装失败")
        self.ctx.ui.notify("加载器安装失败", str(exc), "error")

    def _cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.panel.set_text("正在取消…")

    def _cancel_done(self) -> None:
        self.task = None
        self.panel.reset()
        self.install_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.on_status("已取消安装")


class GameDownloadPage(QWidget):
    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("下载与安装")
        title.setObjectName("H1")
        header.addWidget(title)
        header.addStretch(1)
        self.source = Pill("Mojang 官方源 · 可切换 BMCLAPI 镜像", "ok")
        header.addWidget(self.source)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.loader = LoaderTab(ctx, self._status)
        self.vanilla = VanillaTab(ctx, self._status, self.loader.set_versions)
        self.tabs.addTab(self.vanilla, "原版游戏")
        self.tabs.addTab(self.loader, "模组加载器")
        root.addWidget(self.tabs, 1)

        self.vanilla.reload()

    def _status(self, text: str) -> None:
        self.ctx.ui.set_status(text)


def build_page(ctx: Any) -> QWidget:
    return GameDownloadPage(ctx)
