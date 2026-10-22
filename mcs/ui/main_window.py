"""主窗口：侧边导航 + 页面栈。"""

from __future__ import annotations

import base64
from typing import Any

from PyQt6.QtCore import QByteArray, Qt, QTimer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..api import HOOK_APP_CLOSING
from .errors import show_error
from .login_dialog import LoginDialog
from .logs_page import LogsPage
from .pages import AccountPage, HomePage, SettingsPage, VersionsPage
from .plugin_page import PluginPage
from .service import UiService
from .theme import DEFAULT_ACCENT, app_icon
from .widgets import Avatar, Pill, Toast


class MainWindow(QMainWindow):
    def __init__(self, host: Any) -> None:
        super().__init__()
        self.host = host
        self.settings = host.settings
        self.accounts = host.accounts
        self._widgets: dict[str, QWidget] = {}
        self._current_page = ""

        self.setWindowTitle("MCS Launcher")
        self.setMinimumSize(1020, 680)
        self.resize(1240, 800)
        self._refresh_icon()

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ------------------------------------------------------------ sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 18)
        side.setSpacing(14)

        brand = QHBoxLayout()
        brand.setSpacing(11)
        logo = QLabel("M")
        logo.setObjectName("Logo")
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("MCS")
        name.setObjectName("BrandName")
        sub = QLabel("MINECRAFT LAUNCHER")
        sub.setObjectName("BrandSub")
        brand_text.addWidget(name)
        brand_text.addWidget(sub)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        side.addLayout(brand)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        side.addWidget(divider)

        self.nav_widget = QWidget()
        self.nav_layout = QVBoxLayout(self.nav_widget)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        side.addWidget(self.nav_widget)
        side.addStretch(1)

        self.account_button = QPushButton("●  未登录")
        self.account_button.setObjectName("NavButton")
        self.account_button.setToolTip("账户管理")
        self.account_button.clicked.connect(lambda: self.show_page("account"))
        side.addWidget(self.account_button)

        footer = QLabel(f"MCS Launcher {__version__}")
        footer.setObjectName("Hint")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(footer)

        root_layout.addWidget(sidebar)

        # ------------------------------------------------------------- main
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(30, 22, 30, 24)
        main_layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = QLabel("主页")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.status = Pill("就绪", "ok")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, 1)
        root_layout.addWidget(main, 1)

        self.toast = Toast(root)
        self._toast_level = "info"

        self.ui_service = UiService(self, host)
        host.attach_ui(self.ui_service)
        self.ui_service.add_core_page(
            "home", "主页", HomePage(host, self), subtitle="启动游戏、查看运行状态", icon="⌂", order=0
        )
        self.ui_service.add_core_page(
            "versions", "版本", VersionsPage(host, self), subtitle="本地已安装的 Minecraft 版本", icon="❖", order=10
        )
        self.ui_service.add_core_page(
            "account", "账户", AccountPage(host, self), subtitle="Microsoft 正版登录与账户切换", icon="●", order=20
        )
        self.ui_service.add_core_page(
            "plugins", "插件", PluginPage(host, self), subtitle="启停、安装与排查扩展", icon="◈", order=25
        )
        self.ui_service.add_core_page(
            "logs", "日志", LogsPage(host, self), subtitle="实时日志、错误与诊断信息", icon="▤", order=45
        )
        self.ui_service.add_core_page(
            "settings", "设置", SettingsPage(host, self), subtitle="游戏、Java 与下载源", icon="≡", order=900
        )

        self.accounts.accounts_changed.connect(self._refresh_account_chip)
        self.accounts.current_changed.connect(lambda _acc: self._refresh_account_chip())
        self._refresh_account_chip()
        if self.ui_service.pages():
            self.show_page(self.ui_service.pages()[0].page_id)
        self._restore_geometry()

    # --------------------------------------------------------------- pages
    def add_page_widget(self, page_id: str, widget: QWidget) -> None:
        self._widgets[page_id] = widget
        self.stack.addWidget(widget)

    def remove_page_widget(self, page_id: str) -> None:
        widget = self._widgets.pop(page_id, None)
        if widget is not None:
            self.stack.removeWidget(widget)
            widget.deleteLater()
        if self._current_page == page_id and self.ui_service.pages():
            self.show_page(self.ui_service.pages()[0].page_id)

    def rebuild_nav(self) -> None:
        for button in list(self.nav_group.buttons()):
            self.nav_group.removeButton(button)
            button.hide()
            button.setParent(None)
            button.deleteLater()
        while self.nav_layout.count():
            item = self.nav_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for entry in self.ui_service.pages():
            button = QPushButton(f"{entry.icon or '•'}    {entry.title}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("pageId", entry.page_id)
            button.clicked.connect(lambda _=False, pid=entry.page_id: self.show_page(pid))
            self.nav_group.addButton(button)
            self.nav_layout.addWidget(button)
            if entry.page_id == self._current_page:
                button.setChecked(True)
        self.nav_layout.addStretch(1)

    def show_page(self, page_id: str) -> bool:
        entry = self.ui_service.page(page_id)
        if entry is None:
            return False
        widget = self._widgets.get(page_id)
        if widget is None:
            return False
        self.stack.setCurrentWidget(widget)
        self._current_page = page_id
        self.page_title.setText(entry.title)
        self.page_subtitle.setText(entry.subtitle)
        for button in self.nav_group.buttons():
            button.setChecked(button.property("pageId") == page_id)
        self.settings.set("last_page", page_id, save=False)
        return True

    # ------------------------------------------------------------ services
    def set_status(self, text: str, kind: str = "normal") -> None:
        self.status.setText(text)
        self.status.set_kind(kind)

    def show_toast(self, title: str, message: str = "", level: str = "info") -> None:
        color = {"error": "#FF8D8D", "warning": "#F5C06B"}.get(level, "#FFFFFF")
        self.toast.title.setStyleSheet(f"color: {color};")
        self.toast.show_toast(title, message)
        self.toast._reposition()

    def open_login_dialog(self) -> None:
        dialog = LoginDialog(self.host, self)
        dialog.exec()

    def report_plugin_failures(self) -> None:
        """把插件发现/加载错误汇总成一个可展开的错误弹窗。"""
        failures: list[tuple[str, str, str]] = []
        for name, message in self.host.discovery_errors():
            failures.append((name, "插件清单无法读取", message))
        for loaded in self.host.loaded_plugins():
            if loaded.error:
                failures.append((loaded.meta.display_name, loaded.meta.id, loaded.error))
        if not failures:
            return
        details = "\n\n".join(f"{name}（{identity}）\n{message}" for name, identity, message in failures)
        show_error(
            self,
            "部分插件未能加载",
            f"有 {len(failures)} 个插件出现问题；其他功能仍可正常使用。",
            details,
            hint="可以到「插件」页面查看状态、启用/禁用或移除插件。",
            modal=False,
        )
        self._refresh_account_chip()

    # -------------------------------------------------------------- account
    def _refresh_account_chip(self) -> None:
        account = self.accounts.current
        if account is None:
            self.account_button.setText("●   未登录")
        else:
            self.account_button.setText(f"●   {account.name}")

    # --------------------------------------------------------------- window
    def _refresh_icon(self) -> None:
        accent = str(self.settings.get("accent", DEFAULT_ACCENT) or DEFAULT_ACCENT)
        self.setWindowIcon(app_icon(accent))

    def refresh_icon(self) -> None:
        self._refresh_icon()

    def _restore_geometry(self) -> None:
        raw = str(self.settings.get("window_geometry", "") or "")
        if not raw:
            return
        try:
            data = QByteArray.fromBase64(raw.encode("ascii"))
            self.restoreGeometry(data)
        except Exception:  # noqa: BLE001
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast._reposition()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.settings.set(
                "window_geometry",
                base64.b64encode(bytes(self.saveGeometry().toBase64())).decode("ascii"),
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            self.host.hooks.emit(HOOK_APP_CLOSING, window=self)
        except Exception:  # noqa: BLE001
            pass
        self.host.unload_all()
        super().closeEvent(event)
