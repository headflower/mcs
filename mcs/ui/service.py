"""IUiService 的具体实现：管理页面、导航、通知与跨线程调用。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from ..api.types import PluginMeta
from .errors import show_error as _show_error


@dataclass
class PageEntry:
    page_id: str
    title: str
    subtitle: str
    icon: str
    order: int
    owner: str
    widget: QWidget


class UiService(QObject):
    _call_requested = pyqtSignal(object)

    def __init__(self, window: Any, host: Any) -> None:
        super().__init__(window)
        self._window = window
        self._host = host
        self._pages: list[PageEntry] = []
        self._call_requested.connect(self._run_call, type=Qt.ConnectionType.QueuedConnection)

    # -------------------------------------------------------------- pages
    @property
    def main_window(self) -> Any:
        return self._window

    def pages(self) -> list[PageEntry]:
        return list(self._pages)

    def page(self, page_id: str) -> PageEntry | None:
        for entry in self._pages:
            if entry.page_id == page_id:
                return entry
        return None

    def add_core_page(
        self, page_id: str, title: str, widget: QWidget, *, subtitle: str = "", icon: str = "", order: int = 100
    ) -> None:
        self._insert(PageEntry(page_id, title, subtitle, icon, order, "core", widget))

    def add_page(
        self,
        page_id: str,
        title: str,
        factory: Callable[[Any], Any] | QWidget,
        *,
        icon: str = "",
        subtitle: str = "",
        order: int = 100,
    ) -> None:
        if not page_id or not str(page_id).strip():
            raise ValueError("page_id 不能为空")
        page_id = str(page_id).strip()
        if self.page(page_id) is not None:
            self.notify("页面未注册", f"页面 id「{page_id}」已存在。", "warning")
            return
        owner = getattr(self._host, "loading_plugin_id", "") or "unknown"
        context = None
        for loaded in self._host.loaded_plugins():
            if loaded.meta.id == owner:
                context = loaded.context
                break
        widget: QWidget
        try:
            if isinstance(factory, QWidget):
                widget = factory
            else:
                widget = factory(context)
            if not isinstance(widget, QWidget):
                raise TypeError("页面工厂必须返回 QWidget")
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("mcs.ui").exception("创建插件页面失败：%s", page_id)
            widget = self._error_widget(title, exc)
        self._insert(PageEntry(page_id, title, subtitle, icon, order, owner, widget))

    def _error_widget(self, title: str, exc: BaseException) -> QWidget:
        from .widgets import Card
        from PyQt6.QtWidgets import QLabel, QVBoxLayout

        frame = QWidget()
        layout = QVBoxLayout(frame)
        card = Card()
        heading = QLabel(f"{title} 页面加载失败")
        heading.setObjectName("SectionTitle")
        detail = QLabel(str(exc))
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        card.body.addWidget(heading)
        card.body.addWidget(detail)
        layout.addWidget(card)
        layout.addStretch(1)
        return frame

    def _insert(self, entry: PageEntry) -> None:
        self._pages.append(entry)
        self._pages.sort(key=lambda p: (p.order, p.title))
        self._window.add_page_widget(entry.page_id, entry.widget)
        self._window.rebuild_nav()

    def remove_page(self, page_id: str) -> None:
        entry = self.page(page_id)
        if entry is None:
            return
        self._pages.remove(entry)
        self._window.remove_page_widget(page_id)
        self._window.rebuild_nav()

    def remove_pages_of(self, owner: str) -> None:
        for entry in [p for p in self._pages if p.owner == owner]:
            self.remove_page(entry.page_id)

    def open_page(self, page_id: str) -> None:
        self._window.show_page(page_id)

    # ------------------------------------------------------------ feedback
    def notify(self, title: str, message: str, level: str = "info") -> None:
        self._window.show_toast(title, message, level)

    def show_error(self, title: str, message: str, details: str = "", *, hint: str = "") -> Any:
        return _show_error(self._window, title, message, details, hint=hint)

    def set_status(self, text: str) -> None:
        self._window.set_status(text)

    def confirm(self, title: str, text: str) -> bool:
        result = QMessageBox.question(
            self._window,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def open_path(self, path: str | Path) -> None:
        text = str(path)
        if text.lower().startswith(("http://", "https://")):
            if not QDesktopServices.openUrl(QUrl(text)):
                self.notify("无法打开", f"系统拒绝了打开链接：{text}", "warning")
            return
        target = Path(path)
        if not target.exists() and not target.suffix:
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        url = QUrl.fromLocalFile(str(target))
        if not QDesktopServices.openUrl(url):
            self.notify("无法打开", f"系统拒绝了打开操作：{target}", "warning")

    def open_login(self) -> None:
        self._window.open_login_dialog()

    # --------------------------------------------------------- thread hop
    def call_on_ui(self, fn: Callable[[], Any]) -> None:
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            fn()
        else:
            self._call_requested.emit(fn)

    def _run_call(self, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import logging

            if isinstance(exc, RuntimeError) and "deleted" in str(exc):
                # 插件页面已卸载，排队中的回调晚于控件销毁到达；静默丢弃即可。
                logging.getLogger("mcs.ui").debug("忽略已卸载控件的回调：%s", exc)
                return
            logging.getLogger("mcs.ui").exception("UI 回调执行失败")
