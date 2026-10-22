"""Java 页面。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mcs.ui.widgets import Card, Pill

from . import manager


class JavaPage(QWidget):
    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        self.download_task = None
        self._build()
        self.refresh()
        self._load_releases()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        installed = Card()
        head = QHBoxLayout()
        name = QLabel("已检测到的 Java")
        name.setObjectName("H2")
        self.badge = Pill("自动发现本机运行时", "ok")
        self.scan_btn = QPushButton("重新扫描")
        self.scan_btn.setObjectName("Ghost")
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(self.badge)
        head.addWidget(self.scan_btn)
        installed.body.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["版本", "供应商", "路径", "来源"])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(190)
        installed.body.addWidget(self.table)

        actions = QHBoxLayout()
        self.use_btn = QPushButton("设为默认 Java")
        self.use_btn.setEnabled(False)
        actions.addStretch(1)
        actions.addWidget(self.use_btn)
        installed.body.addLayout(actions)
        root.addWidget(installed)

        download = Card(accent=True)
        dhead = QHBoxLayout()
        dname = QLabel("下载 Java 运行时")
        dname.setObjectName("H2")
        dhead.addWidget(dname)
        dhead.addStretch(1)
        self.source = Pill("Eclipse Adoptium · Temurin JRE", "ok")
        dhead.addWidget(self.source)
        download.body.addLayout(dhead)

        note = QLabel(
            "自动下载会安装到启动器的数据目录，不会修改系统环境变量。"
            "游戏下载插件缺少 Java 时也会调用这里的自动安装服务。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        download.body.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.major = QComboBox()
        self.major.setMinimumWidth(180)
        self.major.addItem("正在获取可用版本…", 0)
        self.install_btn = QPushButton("下载并安装")
        self.install_btn.setEnabled(False)
        row.addWidget(QLabel("Java 版本"))
        row.addWidget(self.major, 1)
        row.addWidget(self.install_btn)
        download.body.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        download.body.addWidget(self.bar)
        download.body.addWidget(self.status)
        root.addWidget(download)
        root.addStretch(1)

        self.scan_btn.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.use_btn.clicked.connect(self._use_selected)
        self.install_btn.clicked.connect(self._install)
        self.major.currentIndexChanged.connect(
            lambda _: self.install_btn.setEnabled(
                int(self.major.currentData() or 0) > 0 and self.download_task is None
            )
        )

    # ----------------------------------------------------------------- data
    def refresh(self) -> None:
        runtimes = self.ctx.java.scan(force=True)
        self.table.setRowCount(0)
        for runtime in sorted(runtimes, key=lambda r: (r.major, r.version), reverse=True):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"Java {runtime.major}（{runtime.version}）"))
            self.table.setItem(row, 1, QTableWidgetItem(runtime.vendor or "未知"))
            path_item = QTableWidgetItem(runtime.path)
            path_item.setToolTip(runtime.path)
            self.table.setItem(row, 2, path_item)
            self.table.setItem(row, 3, QTableWidgetItem("启动器下载" if runtime.managed else "系统安装"))
        if runtimes:
            self.badge.setText(f"已找到 {len(runtimes)} 个运行时")
            self.badge.set_kind("ok")
        else:
            self.badge.setText("尚未找到 Java")
            self.badge.set_kind("busy")
        self.ctx.ui.set_status(f"已检测到 {len(runtimes)} 个 Java 运行时")
        self._selection_changed()

    def _load_releases(self) -> None:
        self.ctx.tasks.run(
            lambda _task: manager.available_releases(self.ctx),
            title="获取 Java 版本列表",
            on_done=self._releases_loaded,
            on_error=lambda exc: self.status.setText(str(exc)),
        )

    def _releases_loaded(self, releases: Any) -> None:
        self.major.clear()
        for value in releases:
            label = f"Java {value}" + ("（LTS）" if value in (8, 11, 17, 21, 25) else "")
            self.major.addItem(label, int(value))
        preferred = self.major.findData(21)
        if preferred < 0:
            preferred = max(
                (i for i in range(self.major.count()) if int(self.major.itemData(i) or 0) <= 21),
                default=0,
            )
        self.major.setCurrentIndex(preferred)
        self.install_btn.setEnabled(bool(releases))

    def _selected_runtime(self) -> Any:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 2)
        return item.text() if item else None

    def _selection_changed(self) -> None:
        self.use_btn.setEnabled(bool(self._selected_runtime()))

    def _use_selected(self) -> None:
        path = self._selected_runtime()
        if not path:
            return
        self.ctx.settings.set("java_path", path)
        runtime = self.ctx.java.get(path)
        self.ctx.ui.notify(
            "已设为默认 Java",
            runtime.label if runtime else path,
            "success",
        )
        self.ctx.ui.set_status(f"默认 Java：{path}")

    # -------------------------------------------------------------- download
    def _install(self) -> None:
        if self.download_task is not None:
            return
        major = int(self.major.currentData() or 0)
        if not major:
            return
        existing = self.ctx.java.find(major)
        if existing is not None:
            if not self.ctx.ui.confirm("已存在 Java", f"已找到 {existing.label}，仍要再下载一份吗？"):
                return
        self.download_task = self.ctx.tasks.run(
            lambda task: manager.install_java(self.ctx, major, task),
            title=f"下载 Java {major}",
            on_done=self._done,
            on_error=self._failed,
            on_progress=self._progress,
            on_status=self.status.setText,
            on_cancelled=self._cancelled,
        )
        self.bar.show()
        self.bar.setRange(0, 0)
        self.install_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.status.setText(f"正在安装 Java {major}…")

    def _progress(self, done: int, total: int, message: str) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, int(done * 1000 / total)))
            self.status.setText(f"{message} · {done / 1048576:.1f}/{total / 1048576:.1f} MB")
        else:
            self.bar.setRange(0, 0)
            self.status.setText(message)

    def _done(self, runtime: Any) -> None:
        self.download_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.refresh()
        label = getattr(runtime, "label", str(runtime))
        self.status.setText(f"已安装 {label}")
        self.ctx.ui.notify("Java 安装完成", f"{label}\n已添加到启动器的 Java 列表。", "success")

    def _failed(self, exc: BaseException) -> None:
        self.download_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.status.setText("安装失败")
        self.ctx.ui.notify("Java 安装失败", str(exc), "error")

    def _cancelled(self) -> None:
        self.download_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.status.setText("已取消")


def build_page(ctx: Any) -> QWidget:
    return JavaPage(ctx)
