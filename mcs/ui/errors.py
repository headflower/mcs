"""统一的错误对话框与全局异常钩子。"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from typing import Any

from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.logging import log_path
from ..core.paths import logs_dir

log = logging.getLogger("mcs.errors")
_OPEN_DIALOGS: list["ErrorDialog"] = []


def format_exception(exc_type: type[BaseException], exc: BaseException, tb: Any) -> str:
    return "".join(traceback.format_exception(exc_type, exc, tb)).strip()


class ErrorDialog(QDialog):
    """可展开详情的错误对话框。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "发生错误",
        message: str = "",
        details: str = "",
        hint: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(760)

        self._title = title
        self._message = message
        self._details = details

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        badge = QLabel("!")
        badge.setObjectName("ErrorBadge")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("DialogTitle")
        heading.setWordWrap(True)
        titles.addWidget(heading)
        if message:
            body = QLabel(message)
            body.setObjectName("Muted")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            titles.addWidget(body)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        self.details_edit = QPlainTextEdit()
        self.details_edit.setObjectName("Details")
        self.details_edit.setReadOnly(True)
        self.details_edit.setPlainText(details)
        self.details_edit.setMaximumHeight(280)
        self.details_edit.setVisible(False)
        layout.addWidget(self.details_edit)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("Muted")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if details:
            self.toggle_button = QPushButton("显示详细信息")
            self.toggle_button.setObjectName("Ghost")
            self.toggle_button.setCheckable(True)
            self.toggle_button.toggled.connect(self._toggle_details)
            buttons.addWidget(self.toggle_button)
        buttons.addStretch(1)
        copy_button = QPushButton("复制详情")
        copy_button.setObjectName("Ghost")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        if details:
            log_button = QPushButton("打开日志")
            log_button.setObjectName("Ghost")
            log_button.clicked.connect(self._open_logs)
            buttons.addWidget(log_button)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _toggle_details(self, checked: bool) -> None:
        self.details_edit.setVisible(checked)
        self.toggle_button.setText("隐藏详细信息" if checked else "显示详细信息")
        self.adjustSize()

    def _copy(self) -> None:
        text = f"{self._title}\n\n{self._message}"
        if self._details:
            text += f"\n\n{self._details}"
        QApplication.clipboard().setText(text)

    def _open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir())))


def show_error(
    parent: QWidget | None,
    title: str,
    message: str,
    details: str = "",
    *,
    hint: str = "",
    modal: bool = True,
) -> ErrorDialog | None:
    """显示错误对话框。modal=False 时立即返回，供启动阶段批量报错使用。"""
    app = QApplication.instance()
    if app is None:
        text = f"{title}: {message}"
        if details:
            text += f"\n{details}"
        stream = sys.stderr or sys.stdout
        if stream is not None:
            try:
                print(text, file=stream)
            except OSError:
                pass
        return None
    dialog = ErrorDialog(parent, title=title, message=message, details=details, hint=hint)
    dialog.setModal(modal)
    if modal:
        dialog.exec()
        return dialog
    _OPEN_DIALOGS.append(dialog)

    def forget(_result: int) -> None:
        if dialog in _OPEN_DIALOGS:
            _OPEN_DIALOGS.remove(dialog)

    dialog.finished.connect(forget)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def install_qt_message_handler() -> None:
    """把 Qt 自身的警告/错误写入日志，便于排查渲染与插件界面问题。"""
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    def handler(mode: Any, context: Any, message: str) -> None:
        if mode == QtMsgType.QtFatalMsg:
            log.critical("Qt: %s", message)
        elif mode == QtMsgType.QtCriticalMsg:
            log.error("Qt: %s", message)
        elif mode == QtMsgType.QtWarningMsg:
            log.warning("Qt: %s", message)
        else:
            log.debug("Qt: %s", message)

    qInstallMessageHandler(handler)


def install_exception_hooks() -> None:
    """安装主线程/Qt 异常钩子：先写日志，再弹出统一错误框。"""
    previous = sys.excepthook
    guard = {"active": False}

    def hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if guard["active"]:
            previous(exc_type, exc, tb)
            return
        guard["active"] = True
        try:
            details = format_exception(exc_type, exc, tb)
            log.critical("未捕获异常", exc_info=(exc_type, exc, tb))
            QTimer.singleShot(
                0,
                lambda: show_error(
                    None,
                    "启动器内部错误",
                    f"{exc_type.__name__}: {exc}",
                    details,
                    hint=f"日志文件：{log_path()}",
                ),
            )
        except Exception:  # noqa: BLE001
            previous(exc_type, exc, tb)
        finally:
            QTimer.singleShot(500, lambda: guard.update(active=False))

    sys.excepthook = hook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        log.critical(
            "线程 %s 未捕获异常",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = thread_hook
