"""可复用的小部件。"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, accent: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("CardAccent" if accent else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(10)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class Avatar(QLabel):
    def __init__(self, name: str = "", size: int = 44, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("Avatar")
        self.set_name(name)

    def set_name(self, name: str) -> None:
        text = (name or "?").strip()
        initials = text[:2].upper() if text else "?"
        self.setText(initials)


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Hint")
            sub.setWordWrap(True)
            layout.addWidget(sub)


class Pill(QLabel):
    def __init__(self, text: str = "", kind: str = "normal", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        self.setObjectName(
            {
                "normal": "Pill",
                "ok": "PillOk",
                "busy": "PillBusy",
                "danger": "PillDanger",
                "warn": "PillWarn",
            }.get(kind, "Pill")
        )
        style = self.style()
        style.unpolish(self)
        style.polish(self)


class Toast(QFrame):
    """右下角浮层通知。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMaximumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(3)
        self.title = QLabel("")
        self.title.setObjectName("SectionTitle")
        self.message = QLabel("")
        self.message.setObjectName("Muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_toast(self, title: str, message: str, msec: int = 4200) -> None:
        self.title.setText(title)
        self.message.setText(message)
        self.message.setVisible(bool(message))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(msec)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent:
            x = parent.width() - self.width() - 28
            y = parent.height() - self.height() - 24
            self.move(max(0, x), max(0, y))


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
