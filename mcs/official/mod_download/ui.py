"""模组下载页面：搜索、筛选、选择文件并安装到 mods/。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mcs.api.types import ModFile, ModProject
from mcs.ui.widgets import Card, Pill

from . import installer
from .api import CurseForgeClient, ModApiError, client_for

POPULAR_VERSIONS = ["1.21.1", "1.21", "1.20.6", "1.20.1", "1.19.2", "1.18.2", "1.16.5", "1.12.2"]
LOADERS = [("全部加载器", ""), ("Fabric", "fabric"), ("Forge", "forge"), ("NeoForge", "neoforge"), ("Quilt", "quilt")]
RELEASE_LABEL = {"release": "正式版", "beta": "Beta", "alpha": "Alpha"}


def _short(text: str, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _installed_mc_versions(ctx: Any) -> list[str]:
    result: list[str] = []
    try:
        for version in ctx.launcher.versions():
            match = re.match(r"(\d+\.\d+(?:\.\d+)?)", version.id)
            if match and match.group(1) not in result:
                result.append(match.group(1))
    except Exception:  # noqa: BLE001
        pass
    return result


class ModDownloadPage(QWidget):
    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        self.projects: list[ModProject] = []
        self.selected: ModProject | None = None
        self.files: list[ModFile] = []
        self.total = 0
        self.search_task = None
        self.files_task = None
        self.install_task = None
        self._search_token = 0
        self._files_token = 0
        self._build()
        self._populate_versions()
        self._source_changed()

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        search_card = Card()
        head = QHBoxLayout()
        heading = QLabel("发现模组")
        heading.setObjectName("H2")
        self.source_badge = Pill("Modrinth", "ok")
        head.addWidget(heading)
        head.addStretch(1)
        head.addWidget(self.source_badge)
        search_card.body.addLayout(head)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索模组名称、功能或作者…")
        self.query.setClearButtonEnabled(True)
        self.source = QComboBox()
        self.source.addItem("Modrinth", "modrinth")
        self.source.addItem("CurseForge", "curseforge")
        self.source.setMinimumWidth(130)
        self.game_version = QComboBox()
        self.game_version.setEditable(True)
        self.game_version.setMinimumWidth(130)
        self.game_version.lineEdit().setPlaceholderText("游戏版本")
        self.loader = QComboBox()
        for label, value in LOADERS:
            self.loader.addItem(label, value)
        self.loader.setMinimumWidth(130)
        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("Primary")
        controls.addWidget(self.query, 1)
        controls.addWidget(self.source)
        controls.addWidget(self.game_version)
        controls.addWidget(self.loader)
        controls.addWidget(self.search_btn)
        search_card.body.addLayout(controls)

        self.cf_hint = QLabel("")
        self.cf_hint.setObjectName("Muted")
        self.cf_hint.setWordWrap(True)
        self.cf_hint.hide()
        search_card.body.addWidget(self.cf_hint)
        root.addWidget(search_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        results_card = Card()
        rhead = QHBoxLayout()
        result_title = QLabel("搜索结果")
        result_title.setObjectName("H2")
        self.count_label = QLabel("尚未搜索")
        self.count_label.setObjectName("Muted")
        rhead.addWidget(result_title)
        rhead.addStretch(1)
        rhead.addWidget(self.count_label)
        results_card.body.addLayout(rhead)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["模组", "作者", "下载量", "来源"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setMinimumWidth(430)
        results_card.body.addWidget(self.table, 1)

        more_row = QHBoxLayout()
        self.more_btn = QPushButton("加载更多")
        self.more_btn.setObjectName("Ghost")
        self.more_btn.setEnabled(False)
        more_row.addStretch(1)
        more_row.addWidget(self.more_btn)
        results_card.body.addLayout(more_row)
        splitter.addWidget(results_card)

        detail = Card(accent=True)
        detail.setMinimumWidth(320)
        detail.setMaximumWidth(390)
        dhead = QHBoxLayout()
        self.icon = QLabel("?")
        self.icon.setFixedSize(56, 56)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setStyleSheet(
            "background: #241C46; color: #C9B8FF; border-radius: 14px;"
            "font-size: 24px; font-weight: 700;"
        )
        self.detail_title = QLabel("选择一个模组")
        self.detail_title.setObjectName("H2")
        self.detail_title.setWordWrap(True)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self.detail_title)
        self.detail_author = QLabel("从左侧结果中选择项目查看详情")
        self.detail_author.setObjectName("Muted")
        text_col.addWidget(self.detail_author)
        dhead.addWidget(self.icon)
        dhead.addLayout(text_col, 1)
        detail.body.addLayout(dhead)

        self.detail_desc = QLabel("")
        self.detail_desc.setObjectName("Muted")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setMinimumHeight(48)
        detail.body.addWidget(self.detail_desc)

        self.open_btn = QPushButton("在浏览器中打开项目页")
        self.open_btn.setObjectName("Ghost")
        self.open_btn.setEnabled(False)
        detail.body.addWidget(self.open_btn)

        file_label = QLabel("可用文件")
        file_label.setObjectName("SectionTitle")
        detail.body.addWidget(file_label)
        self.file_combo = QComboBox()
        self.file_combo.setMinimumHeight(36)
        self.file_combo.addItem("选择模组后加载", None)
        self.file_combo.setEnabled(False)
        detail.body.addWidget(self.file_combo)

        self.deps = QCheckBox("自动安装必需的前置依赖")
        self.deps.setChecked(True)
        detail.body.addWidget(self.deps)

        install_row = QHBoxLayout()
        self.install_btn = QPushButton("安装到 mods")
        self.install_btn.setObjectName("Primary")
        self.install_btn.setEnabled(False)
        self.open_mods_btn = QPushButton("打开 mods")
        self.open_mods_btn.setObjectName("Ghost")
        install_row.addWidget(self.install_btn, 1)
        install_row.addWidget(self.open_mods_btn)
        detail.body.addLayout(install_row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        self.file_status = QLabel("")
        self.file_status.setObjectName("Muted")
        self.file_status.setWordWrap(True)
        detail.body.addWidget(self.bar)
        detail.body.addWidget(self.file_status)
        detail.body.addStretch(1)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.search_btn.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.more_btn.clicked.connect(self._load_more)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.file_combo.currentIndexChanged.connect(self._file_changed)
        self.install_btn.clicked.connect(self._install)
        self.open_btn.clicked.connect(self._open_project)
        self.open_mods_btn.clicked.connect(self._open_mods)

    def _populate_versions(self) -> None:
        values = _installed_mc_versions(self.ctx)
        if not values:
            values = list(POPULAR_VERSIONS)
        self.game_version.clear()
        for value in values:
            self.game_version.addItem(value)
        if "1.20.1" in values:
            self.game_version.setCurrentText("1.20.1")

    def _source(self) -> str:
        return str(self.source.currentData() or "modrinth")

    def _loader(self) -> str:
        return str(self.loader.currentData() or "")

    def _version(self) -> str:
        return self.game_version.currentText().strip()

    # -------------------------------------------------------------- searching
    def _source_changed(self, *_: Any) -> None:
        source = self._source()
        self.source_badge.setText("CurseForge" if source == "curseforge" else "Modrinth")
        if source == "curseforge" and not str(self.ctx.settings.get("curseforge_api_key") or "").strip():
            self.cf_hint.setText(
                "CurseForge 需要 API Key。请先在「设置 → 网络与下载」中填写，再回来搜索。"
            )
            self.cf_hint.show()
        else:
            self.cf_hint.hide()

    def _search(self) -> None:
        if self.search_task is not None:
            return
        self._search_token += 1
        token = self._search_token
        self.projects = []
        self.table.setRowCount(0)
        self.total = 0
        self.more_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.count_label.setText("正在搜索…")
        self._clear_detail()
        query = self.query.text().strip()
        source = self._source()
        game_version = self._version()
        loader = self._loader()
        self.search_task = self.ctx.tasks.run(
            lambda _task: client_for(self.ctx, source).search(
                query, game_version=game_version, loader=loader, offset=0, limit=25
            ),
            title="搜索模组",
            on_done=lambda result: self._search_done(token, result),
            on_error=lambda exc: self._search_failed(token, exc),
        )

    def _load_more(self) -> None:
        if self.search_task is not None or not self.projects:
            return
        self._search_token += 1
        token = self._search_token
        source = self._source()
        offset = len(self.projects)
        game_version = self._version()
        loader = self._loader()
        self.more_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.count_label.setText("正在加载更多…")
        self.search_task = self.ctx.tasks.run(
            lambda _task: client_for(self.ctx, source).search(
                self.query.text().strip(),
                game_version=game_version,
                loader=loader,
                offset=offset,
                limit=25,
            ),
            title="加载更多模组",
            on_done=lambda result: self._search_done(token, result, append=True),
            on_error=lambda exc: self._search_failed(token, exc),
        )

    def _search_done(self, token: int, result: Any, append: bool = False) -> None:
        if token != self._search_token:
            return
        self.search_task = None
        self.search_btn.setEnabled(True)
        if not isinstance(result, tuple) or len(result) != 2:
            self._search_failed(token, RuntimeError("搜索接口返回格式异常"))
            return
        projects, total = result
        self.total = int(total or 0)
        if append:
            self.projects.extend(projects)
        else:
            self.projects = list(projects)
        if append:
            self._append_rows(projects)
        else:
            self._fill_rows()
        self.count_label.setText(
            f"已显示 {len(self.projects)} / {self.total} 个结果" if self.total else "没有匹配结果"
        )
        self.more_btn.setEnabled(len(self.projects) < self.total)
        self.ctx.ui.set_status(f"找到 {self.total} 个模组")

    def _search_failed(self, token: int, exc: BaseException) -> None:
        if token != self._search_token:
            return
        self.search_task = None
        self.search_btn.setEnabled(True)
        self.count_label.setText("搜索失败")
        self.more_btn.setEnabled(bool(self.projects))
        message = str(exc)
        self.ctx.ui.notify("模组搜索失败", message, "error")
        if isinstance(exc, ModApiError):
            self.file_status.setText(message)

    def _fill_rows(self) -> None:
        self.table.setRowCount(0)
        self._append_rows(self.projects)

    def _append_rows(self, projects: list[ModProject]) -> None:
        for project in projects:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title = QTableWidgetItem(project.title)
            title.setData(Qt.ItemDataRole.UserRole, project)
            title.setToolTip(_short(project.description, 320))
            self.table.setItem(row, 0, title)
            self.table.setItem(row, 1, QTableWidgetItem(project.author or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{project.downloads:,}"))
            source = "Modrinth" if project.source == "modrinth" else "CurseForge"
            self.table.setItem(row, 3, QTableWidgetItem(source))
            self.table.setRowHeight(row, 38)
        if projects and self.table.currentRow() < 0:
            self.table.selectRow(0)

    # --------------------------------------------------------------- details
    def _clear_detail(self) -> None:
        self.selected = None
        self.files = []
        self.detail_title.setText("选择一个模组")
        self.detail_author.setText("从左侧结果中选择项目查看详情")
        self.detail_desc.setText("")
        self.icon.setText("?")
        self.open_btn.setEnabled(False)
        self.file_combo.clear()
        self.file_combo.addItem("选择模组后加载", None)
        self.file_combo.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.file_status.setText("")

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        project = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(project, ModProject):
            return
        self.selected = project
        self.icon.setText((project.title or "?")[:1].upper())
        self.detail_title.setText(project.title)
        self.detail_author.setText(project.author or project.source)
        self.detail_desc.setText(_short(project.description, 300))
        self.open_btn.setEnabled(bool(project.url))
        self.file_combo.clear()
        self.file_combo.addItem("正在获取文件列表…", None)
        self.file_combo.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.file_status.setText("")
        self._load_files()

    def _load_files(self) -> None:
        project = self.selected
        if project is None:
            return
        self._files_token += 1
        token = self._files_token
        source = project.source
        game_version = self._version()
        loader = self._loader()
        self.files_task = self.ctx.tasks.run(
            lambda _task: client_for(self.ctx, source).versions(
                project.id, game_version=game_version, loader=loader
            ),
            title=f"获取 {project.title} 的文件",
            on_done=lambda files: self._files_done(token, files),
            on_error=lambda exc: self._files_failed(token, exc),
        )

    def _files_done(self, token: int, files: Any) -> None:
        if token != self._files_token:
            return
        self.files_task = None
        self.files = list(files or [])
        self.file_combo.clear()
        if not self.files:
            self.file_combo.addItem("没有适配当前版本/加载器的文件", None)
            self.file_combo.setEnabled(False)
            self.install_btn.setEnabled(False)
            self.file_status.setText("尝试切换游戏版本或加载器，或到项目页面查看全部文件。")
            return
        for file in self.files:
            release = RELEASE_LABEL.get(file.release_type, file.release_type)
            versions = ", ".join(file.game_versions[:3])
            label = f"{file.version or file.name} · {release}"
            if versions:
                label += f" · {versions}"
            if not file.download_url:
                label += "（无直链）"
            self.file_combo.addItem(label, file)
        self.file_combo.setEnabled(True)
        self.install_btn.setEnabled(any(f.download_url for f in self.files))
        first_available = next((i for i, f in enumerate(self.files) if f.download_url), 0)
        self.file_combo.setCurrentIndex(first_available)
        self.file_status.setText(f"共 {len(self.files)} 个可用文件")

    def _files_failed(self, token: int, exc: BaseException) -> None:
        if token != self._files_token:
            return
        self.files_task = None
        self.files = []
        self.file_combo.clear()
        self.file_combo.addItem("获取文件失败", None)
        self.install_btn.setEnabled(False)
        self.file_status.setText(str(exc))

    def _file_changed(self, *_: Any) -> None:
        file = self.file_combo.currentData()
        self.install_btn.setEnabled(isinstance(file, ModFile) and bool(file.download_url) and self.install_task is None)

    # ---------------------------------------------------------------- install
    def _install(self) -> None:
        if self.install_task is not None:
            return
        project = self.selected
        file = self.file_combo.currentData()
        if project is None or not isinstance(file, ModFile):
            return
        if not file.download_url:
            self.ctx.ui.notify(
                "无法下载",
                "CurseForge 作者关闭了第三方下载。请打开项目页手动下载后放进 mods 文件夹。",
                "warning",
            )
            return
        target = installer.mods_dir(self.ctx) / installer._filename(file)
        if target.exists():
            if not self.ctx.ui.confirm("文件已存在", f"{target.name} 已存在，要覆盖吗？"):
                return
        game_version = self._version()
        loader = self._loader()
        include_deps = self.deps.isChecked()
        self.install_task = self.ctx.tasks.run(
            lambda task: installer.install(
                self.ctx,
                project,
                file,
                task,
                game_version=game_version,
                loader=loader,
                include_dependencies=include_deps,
            ),
            title=f"安装 {project.title}",
            on_done=self._install_done,
            on_error=self._install_failed,
            on_progress=self._install_progress,
            on_status=self._install_status,
            on_cancelled=self._install_cancelled,
        )
        self.bar.show()
        self.bar.setRange(0, 0)
        self.install_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.file_status.setText("准备下载…")
        self.ctx.ui.set_status(f"正在安装 {project.title}…")

    def _install_progress(self, done: int, total: int, message: str) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, int(done * 1000 / total)))
            self.file_status.setText(f"{message} · {done / 1048576:.1f}/{total / 1048576:.1f} MB")
        else:
            self.bar.setRange(0, 0)
            self.file_status.setText(message)

    def _install_status(self, message: str) -> None:
        self.file_status.setText(message)

    def _install_done(self, paths: Any) -> None:
        self.install_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        count = len(paths or [])
        self.file_status.setText(f"已安装 {count} 个文件到 mods 文件夹")
        self.ctx.ui.notify(
            "模组安装完成",
            f"已安装 {count} 个文件。启动游戏前请确认加载器版本与模组匹配。",
            "success",
        )
        self.ctx.ui.set_status("模组已安装")

    def _install_failed(self, exc: BaseException) -> None:
        self.install_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.file_status.setText(str(exc))
        self.ctx.ui.notify("模组安装失败", str(exc), "error")

    def _install_cancelled(self) -> None:
        self.install_task = None
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.file_status.setText("已取消安装")

    # ------------------------------------------------------------------ misc
    def _open_project(self) -> None:
        if self.selected and self.selected.url:
            self.ctx.ui.open_path(self.selected.url)

    def _open_mods(self) -> None:
        self.ctx.ui.open_path(str(installer.mods_dir(self.ctx)))


def build_page(ctx: Any) -> QWidget:
    return ModDownloadPage(ctx)
