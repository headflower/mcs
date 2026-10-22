"""日志查看页面：实时展示启动器、插件与游戏进程日志。"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.logging import LogEntry, log_path, memory_handler
from .widgets import Card, Pill, SectionHeader

log = logging.getLogger("mcs.ui.logs")


class LogsPage(QWidget):
    def __init__(self, host: Any, window: Any) -> None:
        super().__init__()
        self.host = host
        self.window = window
        self._entries: list[LogEntry] = []
        self._cursor = 0
        self._build()
        self._poll()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ----------------------------------------------------------------- ui
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        card = Card()
        head = QHBoxLayout()
        head.addWidget(SectionHeader("运行日志", "启动器、插件与游戏进程的实时输出；完整日志同时写入文件"), 1)
        head.addWidget(Pill("实时", "ok"))
        card.body.addLayout(head)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        path_label = QLabel(f"日志文件：{log_path()}")
        path_label.setObjectName("Hint")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_row.addWidget(path_label, 1)
        open_button = QPushButton("打开日志目录")
        open_button.setObjectName("Ghost")
        open_button.clicked.connect(lambda: self.host.ui.open_path(log_path().parent))
        file_row.addWidget(open_button)
        card.body.addLayout(file_row)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.level_combo = QComboBox()
        self.level_combo.addItem("全部级别", logging.DEBUG)
        self.level_combo.addItem("信息及以上", logging.INFO)
        self.level_combo.addItem("警告及以上", logging.WARNING)
        self.level_combo.addItem("仅错误", logging.ERROR)
        self.level_combo.currentIndexChanged.connect(self._render)
        filters.addWidget(self.level_combo)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索日志内容、插件名或错误关键字…")
        self.search.textChanged.connect(self._render)
        filters.addWidget(self.search, 1)
        self.follow = QCheckBox("自动滚动")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda _checked: self._render())
        filters.addWidget(self.follow)
        refresh = QPushButton("刷新")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(lambda: self._poll())
        filters.addWidget(refresh)
        card.body.addLayout(filters)

        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(6000)
        self.console.setMinimumHeight(320)
        self.console.setPlaceholderText("暂无日志。")
        card.body.addWidget(self.console, 1)

        actions = QHBoxLayout()
        actions.addWidget(
            QLabel("日志中可能包含账户名称等本机信息，分享前请自行检查。"),
            1,
        )
        copy_button = QPushButton("复制当前视图")
        copy_button.setObjectName("Ghost")
        copy_button.clicked.connect(self._copy)
        actions.addWidget(copy_button)
        clear_button = QPushButton("清空视图")
        clear_button.setObjectName("Ghost")
        clear_button.clicked.connect(self._clear)
        actions.addWidget(clear_button)
        card.body.addLayout(actions)

        layout.addWidget(card, 1)
        self._render()

    # ------------------------------------------------------------- logging
    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._poll()

    def _poll(self) -> None:
        if not self.isVisible():
            return
        new_entries, cursor = memory_handler().entries(self._cursor)
        if not new_entries:
            return
        self._cursor = cursor
        self._entries.extend(new_entries)
        if len(self._entries) > 6000:
            self._entries = self._entries[-6000:]
        self._render()

    def _filtered(self) -> list[LogEntry]:
        minimum = int(self.level_combo.currentData() or logging.DEBUG)
        query = self.search.text().strip().lower()
        result: list[LogEntry] = []
        for entry in self._entries:
            if entry.level < minimum:
                continue
            if query and query not in entry.format().lower():
                continue
            result.append(entry)
        return result

    def _render(self, *_args: Any) -> None:
        entries = self._filtered()
        text = "\n".join(entry.format() for entry in entries)
        if not text:
            if not self._entries:
                text = "本次会话还没有日志。启动器、插件和游戏进程的日志会实时出现在这里。"
            else:
                text = "没有符合当前筛选条件的日志。"
        self.console.setPlainText(text)
        if self.follow.isChecked():
            self.console.moveCursor(QTextCursor.MoveOperation.End)
            self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def _copy(self) -> None:
        self.console.selectAll()
        self.console.copy()
        self.console.moveCursor(QTextCursor.MoveOperation.End)
        self.window.show_toast("日志", "当前视图已复制到剪贴板。")

    def _clear(self) -> None:
        self._entries.clear()
        self._render()
        self.window.show_toast("日志", "已清空当前视图，日志文件不受影响。")
