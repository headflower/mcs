"""插件管理页面：启用/禁用、安装 ZIP、移除、查看加载错误。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..api.types import PluginMeta
from ..core.paths import plugins_dir
from ..plugins_host.installer import PluginInstallError, install_zip, uninstall_plugin
from .widgets import Card, Divider, Pill, SectionHeader

log = logging.getLogger("mcs.ui.plugins")


class PluginPage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self._metas: list[PluginMeta] = []
        self._selected_id = ""
        self._suspend = False
        self._build()
        self.host.plugins_changed.connect(self.refresh)
        self.host.plugin_failed.connect(lambda *_args: self.refresh())
        self.refresh()

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        toolbar = Card()
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(
            SectionHeader("插件", "启用、安装或移除扩展；核心启动、设置与登录不依赖插件"),
            1,
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索插件名称或 id…")
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self._fill_table)
        row.addWidget(self.search)
        install = QPushButton("安装 ZIP 插件")
        install.clicked.connect(self._install)
        row.addWidget(install)
        reload_button = QPushButton("重新加载")
        reload_button.setObjectName("Ghost")
        reload_button.clicked.connect(lambda: self._reload_all())
        row.addWidget(reload_button)
        open_dir = QPushButton("打开插件目录")
        open_dir.setObjectName("Ghost")
        open_dir.clicked.connect(lambda: self.host.ui.open_path(plugins_dir()))
        row.addWidget(open_dir)
        toolbar.body.addLayout(row)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_total = Pill("0 个插件")
        self.stat_enabled = Pill("0 个启用", "ok")
        self.stat_failed = Pill("0 个失败")
        self.stat_user = Pill("0 个用户插件")
        for pill in (self.stat_total, self.stat_enabled, self.stat_failed, self.stat_user):
            stats.addWidget(pill)
        stats.addStretch(1)
        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        stats.addWidget(self.hint)
        toolbar.body.addLayout(stats)
        layout.addWidget(toolbar)

        self.error_card = Card(accent="#FF6B6B")
        error_row = QHBoxLayout()
        self.error_label = QLabel("")
        self.error_label.setObjectName("Muted")
        self.error_label.setWordWrap(True)
        error_row.addWidget(self.error_label, 1)
        detail_button = QPushButton("查看详情")
        detail_button.setObjectName("Ghost")
        detail_button.clicked.connect(self._show_discovery_errors)
        error_row.addWidget(detail_button)
        self.error_card.body.addLayout(error_row)
        self.error_card.setVisible(False)
        layout.addWidget(self.error_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        table_card = Card()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["插件", "版本", "类型", "状态", "页面"])
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMinimumWidth(440)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        table_card.body.addWidget(self.table, 1)
        splitter.addWidget(table_card)

        self.detail_card = Card()
        self.detail_card.setMinimumWidth(320)
        detail_head = QHBoxLayout()
        detail_head.addWidget(SectionHeader("插件详情"), 1)
        self.detail_status = Pill("未选择")
        detail_head.addWidget(self.detail_status)
        self.detail_card.body.addLayout(detail_head)

        self.detail_name = QLabel("从左侧列表选择一个插件")
        self.detail_name.setObjectName("SectionTitle")
        self.detail_name.setWordWrap(True)
        self.detail_card.body.addWidget(self.detail_name)
        self.detail_id = QLabel("")
        self.detail_id.setObjectName("Hint")
        self.detail_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_card.body.addWidget(self.detail_id)
        self.detail_desc = QLabel("")
        self.detail_desc.setObjectName("Muted")
        self.detail_desc.setWordWrap(True)
        self.detail_desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_card.body.addWidget(self.detail_desc)
        self.detail_card.body.addWidget(Divider())
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("Muted")
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_card.body.addWidget(self.detail_meta)
        self.detail_pages = QLabel("")
        self.detail_pages.setObjectName("Hint")
        self.detail_pages.setWordWrap(True)
        self.detail_card.body.addWidget(self.detail_pages)

        self.detail_error = QLabel("")
        self.detail_error.setObjectName("ErrorText")
        self.detail_error.setWordWrap(True)
        self.detail_error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_error.setVisible(False)
        self.detail_card.body.addWidget(self.detail_error)

        self.detail_card.body.addStretch(1)
        self.enable_box = QCheckBox("启用此插件")
        self.enable_box.setEnabled(False)
        self.enable_box.toggled.connect(self._toggle_enabled)
        self.detail_card.body.addWidget(self.enable_box)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.open_button = QPushButton("打开目录")
        self.open_button.setObjectName("Ghost")
        self.open_button.clicked.connect(self._open_selected)
        self.open_button.setEnabled(False)
        actions.addWidget(self.open_button)
        self.remove_button = QPushButton("移除")
        self.remove_button.setObjectName("Danger")
        self.remove_button.clicked.connect(self._remove_selected)
        self.remove_button.setEnabled(False)
        actions.addWidget(self.remove_button)
        self.detail_card.body.addLayout(actions)
        splitter.addWidget(self.detail_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    # --------------------------------------------------------------- data
    def refresh(self) -> None:
        self._metas = sorted(self.host.manifests(), key=lambda m: (not m.builtin, m.name.lower()))
        self._fill_table()
        self._update_stats()
        self._update_errors()
        if self._selected_id:
            if not self._select_id(self._selected_id):
                self._selected_id = ""
                self._clear_details()
        elif self.table.rowCount():
            self.table.selectRow(0)

    def _update_stats(self) -> None:
        total = len(self._metas)
        enabled = sum(1 for meta in self._metas if meta.enabled)
        failed = sum(
            1
            for meta in self._metas
            if (loaded := self.host.loaded_plugin(meta.id)) is not None and loaded.error
        )
        user = sum(1 for meta in self._metas if not meta.builtin)
        self.stat_total.setText(f"{total} 个插件")
        self.stat_enabled.setText(f"{enabled} 个启用")
        self.stat_failed.setText(f"{failed} 个失败")
        self.stat_failed.set_kind("danger" if failed else "normal")
        self.stat_user.setText(f"{user} 个用户插件")
        failed_enabled = [
            meta.id
            for meta in self._metas
            if meta.enabled and (loaded := self.host.loaded_plugin(meta.id)) is not None and loaded.error
        ]
        self.hint.setText(("加载失败：" + "、".join(failed_enabled[:3]) + ("…" if len(failed_enabled) > 3 else "")) if failed_enabled else "")

    def _update_errors(self) -> None:
        errors = self.host.discovery_errors()
        self.error_card.setVisible(bool(errors))
        if errors:
            names = "、".join(name for name, _message in errors[:4])
            more = "…" if len(errors) > 4 else ""
            self.error_label.setText(f"有 {len(errors)} 个插件目录无法读取清单：{names}{more}")

    def _show_discovery_errors(self) -> None:
        errors = self.host.discovery_errors()
        if not errors:
            return
        details = "\n\n".join(f"{name}\n{message}" for name, message in errors)
        self.host.ui.show_error(
            "插件清单错误",
            f"有 {len(errors)} 个插件目录被跳过，启动器仍可正常使用。",
            details,
            hint=f"插件目录：{plugins_dir()}",
        )

    def _fill_table(self) -> None:
        selected = self._selected_id
        query = self.search.text().strip().lower()
        rows = [
            meta
            for meta in self._metas
            if not query or query in meta.name.lower() or query in meta.id.lower() or query in meta.description.lower()
        ]
        self.table.setRowCount(len(rows))
        self.table.clearSelection()
        for row, meta in enumerate(rows):
            loaded = self.host.loaded_plugin(meta.id)
            if not meta.enabled:
                status, color = "已禁用", "#7D8799"
            elif loaded is not None and loaded.error:
                status, color = "加载失败", "#FF8D8D"
            elif loaded is not None:
                status, color = "运行中", "#5BE7B0"
            else:
                status, color = "未加载", "#F5C06B"
            pages = sum(1 for page in self.host.ui.pages() if page.owner == meta.id)
            values = [meta.name, meta.version, "内置" if meta.builtin else "用户", status, str(pages)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, meta.id)
                if column == 3:
                    item.setForeground(QColor(color))
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        if selected:
            if not self._select_id(selected):
                self._selected_id = ""
                self.table.clearSelection()
                self._clear_details()
        elif not rows:
            self._selected_id = ""
            self._clear_details()

    def _select_id(self, plugin_id: str) -> bool:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == plugin_id:
                self.table.selectRow(row)
                return True
        return False

    def _clear_details(self) -> None:
        self.detail_name.setText("从左侧列表选择一个插件")
        self.detail_id.setText("")
        self.detail_desc.setText("")
        self.detail_meta.setText("")
        self.detail_pages.setText("")
        self.detail_error.setVisible(False)
        self.detail_status.setText("未选择")
        self.detail_status.set_kind("normal")
        self._suspend = True
        self.enable_box.setChecked(False)
        self._suspend = False
        self.enable_box.setEnabled(False)
        self.open_button.setEnabled(False)
        self.remove_button.setEnabled(False)

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self._clear_details()
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        plugin_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        meta = next((m for m in self._metas if m.id == plugin_id), None)
        if meta is None:
            return
        self._selected_id = meta.id
        loaded = self.host.loaded_plugin(meta.id)
        pages = [page.title for page in self.host.ui.pages() if page.owner == meta.id]
        self.detail_name.setText(meta.name)
        self.detail_id.setText(meta.id)
        self.detail_desc.setText(meta.description or "这个插件没有提供描述。")
        deps = "、".join(meta.dependencies) if meta.dependencies else "无"
        self.detail_meta.setText(
            f"版本：{meta.version}\n"
            f"作者：{meta.author or '未提供'}\n"
            f"类型：{'内置插件' if meta.builtin else '用户插件'} · {meta.kind}"
            + (f" · ABI {meta.abi}" if meta.abi else "")
            + f"\nAPI：v{meta.api}\n"
            f"依赖：{deps}\n"
            f"路径：{meta.path}"
        )
        self.detail_pages.setText(f"注册页面：{'、'.join(pages) if pages else '无'}")
        if not meta.enabled:
            self.detail_status.setText("已禁用")
            self.detail_status.set_kind("normal")
        elif loaded is not None and loaded.error:
            self.detail_status.setText("加载失败")
            self.detail_status.set_kind("danger")
        elif loaded is not None:
            self.detail_status.setText("运行中")
            self.detail_status.set_kind("ok")
        else:
            self.detail_status.setText("未加载")
            self.detail_status.set_kind("busy")
        error = loaded.error if loaded is not None else ""
        self.detail_error.setVisible(bool(error))
        self.detail_error.setText(f"错误：{error}" if error else "")
        self._suspend = True
        self.enable_box.setChecked(meta.enabled)
        self._suspend = False
        self.enable_box.setEnabled(True)
        self.open_button.setEnabled(True)
        self.remove_button.setEnabled(not meta.builtin)

    # ------------------------------------------------------------ actions
    def _toggle_enabled(self, checked: bool) -> None:
        if self._suspend or not self._selected_id:
            return
        plugin_id = self._selected_id
        self.host.set_plugin_enabled(plugin_id, checked)
        self.window.show_toast("插件", f"已{'启用' if checked else '禁用'} {plugin_id}，正在重新加载…")
        QTimer.singleShot(0, lambda: self._reload_all(keep=plugin_id, quiet=True))

    def _reload_all(self, keep: str = "", quiet: bool = False) -> None:
        plugin_id = keep or self._selected_id
        self.host.reload()
        self.refresh()
        if plugin_id:
            self._select_id(plugin_id)
        self.window.report_plugin_failures()
        if not quiet:
            self.window.show_toast("插件", "插件已重新加载。")

    def _install(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择插件压缩包", str(Path.home()), "插件压缩包 (*.zip)")
        if not path:
            return
        try:
            meta = install_zip(path)
        except PluginInstallError as exc:
            if "已存在" in str(exc) and self.host.ui.confirm("覆盖安装", f"{exc}\n\n是否删除旧目录并覆盖安装？"):
                try:
                    meta = install_zip(path, overwrite=True)
                except PluginInstallError as retry_exc:
                    self.host.ui.show_error("安装插件失败", str(retry_exc), hint="请确认压缩包内包含有效的 plugin.json。")
                    return
            else:
                self.host.ui.show_error("安装插件失败", str(exc), hint="请确认压缩包内包含有效的 plugin.json。")
                return
        self.host.reload()
        self._selected_id = meta.id
        self.refresh()
        self._select_id(meta.id)
        self.window.show_toast("插件", f"已安装 {meta.name} {meta.version}。")
        self.window.report_plugin_failures()

    def _remove_selected(self) -> None:
        meta = next((m for m in self._metas if m.id == self._selected_id), None)
        if meta is None:
            return
        if not self.host.ui.confirm("移除插件", f"确定移除「{meta.name}」吗？\n\n{meta.path}"):
            return
        try:
            uninstall_plugin(meta)
        except PluginInstallError as exc:
            self.host.ui.show_error("移除插件失败", str(exc))
            return
        self._selected_id = ""
        self.host.reload()
        self.refresh()
        self.window.show_toast("插件", f"已移除 {meta.name}。")

    def _open_selected(self) -> None:
        meta = next((m for m in self._metas if m.id == self._selected_id), None)
        if meta is not None:
            self.host.ui.open_path(meta.path)
