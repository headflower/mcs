"""MCS Launcher 入口。

核心只包含：启动游戏、基础设置、正版登录。
其它功能（游戏下载、模组下载、Java 管理、插件 API 等）全部以插件形式加载。
"""
from __future__ import annotations

import ctypes
import logging
import sys
import traceback


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mcs.launcher")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _set_app_user_model_id()

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from mcs import APP_NAME, __version__
    from mcs.api import HOOK_APP_READY
    from mcs.core.auth import AccountStore
    from mcs.core.launcher import LaunchService
    from mcs.core.logging import setup_logging
    from mcs.core.paths import ensure_layout
    from mcs.core.settings import Settings
    from mcs.plugins_host import PluginHost
    from mcs.ui.errors import install_exception_hooks, install_qt_message_handler, show_error
    from mcs.ui.main_window import MainWindow
    from mcs.ui.theme import apply_theme

    ensure_layout()
    setup_logging()
    log = logging.getLogger("mcs")
    log.info("MCS Launcher %s 启动", __version__)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("MCS")
    app.setDesktopFileName("mcs-launcher")

    install_qt_message_handler()
    install_exception_hooks()

    settings = Settings()
    apply_theme(app, str(settings.get("accent", "") or ""))
    accounts = AccountStore()
    launcher = LaunchService(settings)
    host = PluginHost(settings, accounts, launcher)

    try:
        window = MainWindow(host)
    except Exception as exc:  # noqa: BLE001
        log.exception("主窗口初始化失败")
        show_error(
            None,
            "启动器无法启动",
            f"{type(exc).__name__}: {exc}",
            traceback.format_exc(),
            hint="请把本窗口的详细信息反馈给开发者。",
        )
        return 1

    window.show()
    host.discover()
    host.load_all()
    host.hooks.emit(HOOK_APP_READY, host=host, window=window)

    last_page = str(settings.get("last_page", "") or "")
    if last_page:
        window.show_page(last_page)
    QTimer.singleShot(200, window.report_plugin_failures)
    app.aboutToQuit.connect(lambda: log.info("MCS Launcher 退出"))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
