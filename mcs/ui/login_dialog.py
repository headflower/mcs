"""微软正版登录（设备码流程）对话框。"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.auth import AuthError, MicrosoftAuth


class LoginDialog(QDialog):
    _code_ready = pyqtSignal(object)
    _status_changed = pyqtSignal(str)
    _succeeded = pyqtSignal(object)
    _failed = pyqtSignal(str)

    def __init__(self, host: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self.settings = host.settings
        self.accounts = host.accounts
        self._task = None
        self._finished = False

        self.setWindowTitle("微软正版登录")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)

        title = QLabel("使用微软账户登录")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        intro = QLabel(
            "启动器不会接触你的密码。点击下方按钮后，在浏览器中打开微软登录页并输入显示的代码即可。"
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.code_label = QLabel("------")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; font-size: 34px;"
            "font-weight: 800; letter-spacing: 8px; color: #FFFFFF;"
            "background: #0F131B; border: 1px solid #252C3A; border-radius: 12px; padding: 18px;"
        )
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.code_label)

        self.url_label = QLabel("")
        self.url_label.setObjectName("Muted")
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_label.setOpenExternalLinks(True)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(self.url_label)

        self.status = QLabel("准备就绪。")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("复制代码")
        self.copy_button.setObjectName("Ghost")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_code)
        buttons.addWidget(self.copy_button)

        self.browser_button = QPushButton("打开登录页")
        self.browser_button.setObjectName("Ghost")
        self.browser_button.setEnabled(False)
        self.browser_button.clicked.connect(self._open_browser)
        buttons.addWidget(self.browser_button)
        buttons.addStretch(1)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("Ghost")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)

        self.start_button = QPushButton("开始登录")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        self._code_ready.connect(self._show_code)
        self._status_changed.connect(self._show_status)
        self._succeeded.connect(self._on_success)
        self._failed.connect(self._on_failure)
        self._verification_uri = ""

    # ------------------------------------------------------------- actions
    def start(self) -> None:
        if self._task is not None:
            return
        self.start_button.setEnabled(False)
        self.start_button.setText("等待登录…")
        self.progress.show()
        self.status.setText("正在向微软请求登录代码…")
        client_id = str(self.settings.get("microsoft_client_id") or "").strip()
        auth = MicrosoftAuth(client_id or None)

        def work(task):
            return auth.login_with_device_code(
                on_device_code=lambda code: self._code_ready.emit(code),
                on_status=lambda text: self._status_changed.emit(text),
                cancelled=lambda: task.cancelled,
            )

        self._task = self.host.tasks.run(
            work,
            title="微软登录",
            on_done=lambda account: self._succeeded.emit(account),
            on_error=lambda exc: self._failed.emit(str(exc)),
            on_cancelled=lambda: self._failed.emit("登录已取消。"),
        )

    def _copy_code(self, silent: bool = False) -> None:
        text = self.code_label.text().replace(" ", "")
        if text and text != "------":
            QGuiApplication.clipboard().setText(text)
            if not silent:
                self.status.setText("代码已复制到剪贴板。")

    def _open_browser(self) -> None:
        if not self._verification_uri:
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self._verification_uri))

    def _show_code(self, code: dict[str, Any]) -> None:
        user_code = str(code.get("user_code") or "")
        uri = str(code.get("verification_uri") or "https://microsoft.com/link")
        self._verification_uri = uri
        self.code_label.setText(" ".join(user_code))
        self.url_label.setText(f'在浏览器打开 <a style="color:#9E86FF" href="{uri}">{uri}</a>')
        self.copy_button.setEnabled(True)
        self.browser_button.setEnabled(True)
        self._copy_code(silent=True)
        self.status.setText("已获取代码并复制到剪贴板，请在浏览器中完成登录…")

    def _show_status(self, text: str) -> None:
        self.status.setText(text)

    def _on_success(self, account) -> None:
        self._finished = True
        self.progress.hide()
        self.status.setText(f"登录成功，欢迎 {account.name}！")
        self.accounts.add(account, make_current=True)
        self.start_button.setText("完成")
        self.start_button.setEnabled(True)
        self.start_button.clicked.disconnect()
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.hide()
        self.accept()

    def _on_failure(self, message: str) -> None:
        if self._finished:
            return
        self._finished = True
        self.progress.hide()
        self.start_button.setEnabled(True)
        self.start_button.setText("重试")
        self.start_button.clicked.disconnect()
        self.start_button.clicked.connect(self.start)
        self._task = None
        if "取消" in message:
            self.status.setText(message)
        else:
            self.status.setText(f"登录失败：{message}")

    # -------------------------------------------------------------- events
    def reject(self) -> None:
        if self._task is not None:
            self._task.cancel()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._task is not None:
            self._task.cancel()
        super().closeEvent(event)
