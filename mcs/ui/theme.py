"""现代深色主题：单一 QSS 样式表，强调色可配置。"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication

DEFAULT_ACCENT = "#7C5CFF"

ACCENTS = {
    "紫罗兰": "#7C5CFF",
    "青碧": "#2ED3B7",
    "蔚蓝": "#4C8DFF",
    "珊瑚": "#FF6B6B",
    "琥珀": "#F5A524",
}


def _rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _ink(hex_color: str) -> str:
    """在强调色上选择对比度更高的文字颜色。"""
    color = QColor(hex_color)

    def channel(value: int) -> float:
        value = value / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )
    return "#0C0E13" if luminance > 0.34 else "#FFFFFF"


def build_stylesheet(accent: str = DEFAULT_ACCENT) -> str:
    if not QColor.isValidColor(accent):
        accent = DEFAULT_ACCENT
    soft = _rgba(accent, 0.16)
    softer = _rgba(accent, 0.09)
    border = _rgba(accent, 0.45)
    ink = _ink(accent)
    return f"""
    * {{
        font-family: "Segoe UI Variable Display", "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 14px;
        color: #E7EAF2;
        outline: none;
    }}
    QMainWindow, QWidget#Root {{
        background: #0C0E13;
    }}
    QWidget {{
        background: transparent;
    }}
    QFrame#Sidebar {{
        background: #101319;
        border-right: 1px solid #1B202B;
    }}
    QLabel#BrandName {{
        font-size: 19px;
        font-weight: 800;
        letter-spacing: 1px;
    }}
    QLabel#BrandSub {{
        color: #6A7386;
        font-size: 10px;
        letter-spacing: 2px;
    }}
    QLabel#PageTitle {{
        font-size: 26px;
        font-weight: 800;
    }}
    QLabel#PageSubtitle {{
        color: #8B94A8;
        font-size: 13px;
    }}
    QLabel#SectionTitle {{
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel#Muted {{
        color: #7C8598;
        font-size: 13px;
    }}
    QLabel#Hint {{
        color: #6A7386;
        font-size: 12px;
    }}
    QLabel#Danger {{
        color: #FF7B7B;
    }}
    QFrame#Card {{
        background: #141821;
        border: 1px solid #1E2430;
        border-radius: 16px;
    }}
    QFrame#CardAccent {{
        background: {softer};
        border: 1px solid {border};
        border-radius: 16px;
    }}
    QFrame#Divider {{
        background: #1E2430;
        max-height: 1px;
        border: none;
    }}
    QPushButton {{
        background: #1A1F2A;
        border: 1px solid #252C3A;
        border-radius: 9px;
        padding: 8px 16px;
        color: #E7EAF2;
    }}
    QPushButton:hover {{
        background: #212836;
        border-color: #313A4D;
    }}
    QPushButton:pressed {{
        background: #171C26;
    }}
    QPushButton:disabled {{
        color: #5E6678;
        background: #151922;
        border-color: #1E2430;
    }}
    QPushButton#Primary {{
        background: {accent};
        border: 1px solid {accent};
        color: {ink};
        font-weight: 700;
        padding: 11px 26px;
        border-radius: 11px;
    }}
    QPushButton#Primary:hover {{
        background: {QColor(accent).lighter(112).name()};
        border-color: {QColor(accent).lighter(112).name()};
    }}
    QPushButton#Primary:pressed {{
        background: {QColor(accent).darker(112).name()};
    }}
    QPushButton#Primary:disabled {{
        background: #2A2E3B;
        border-color: #2A2E3B;
        color: #7C8598;
    }}
    QPushButton#Ghost {{
        background: transparent;
        border: 1px solid #2A3242;
        color: #B9C1D2;
    }}
    QPushButton#Ghost:hover {{
        background: #171C26;
        color: #FFFFFF;
    }}
    QPushButton#Danger {{
        background: transparent;
        border: 1px solid #4A2A33;
        color: #FF8D8D;
    }}
    QPushButton#Danger:hover {{
        background: #2A171C;
    }}
    QPushButton#NavButton {{
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 11px 14px;
        text-align: left;
        color: #939CAF;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton#NavButton:hover {{
        background: #171B24;
        color: #E7EAF2;
    }}
    QPushButton#NavButton:checked {{
        background: {soft};
        color: #FFFFFF;
    }}
    QPushButton#Link {{
        background: transparent;
        border: none;
        color: {accent};
        padding: 2px 4px;
        font-weight: 600;
    }}
    QPushButton#Link:hover {{
        color: {QColor(accent).lighter(120).name()};
        text-decoration: underline;
    }}
    QLabel#Logo {{
        background: {accent};
        border-radius: 11px;
        color: {ink};
        font-size: 20px;
        font-weight: 900;
    }}
    QLabel#Avatar {{
        background: {soft};
        border: 1px solid {border};
        border-radius: 22px;
        color: #FFFFFF;
        font-size: 16px;
        font-weight: 800;
    }}
    QLabel#Pill {{
        background: #1A1F2A;
        border: 1px solid #252C3A;
        border-radius: 11px;
        padding: 5px 12px;
        color: #AEB7C9;
        font-size: 12px;
    }}
    QLabel#PillOk {{
        background: rgba(46, 211, 183, 0.12);
        border: 1px solid rgba(46, 211, 183, 0.35);
        border-radius: 11px;
        padding: 5px 12px;
        color: #6FE7D1;
        font-size: 12px;
    }}
    QLabel#PillBusy {{
        background: {soft};
        border: 1px solid {border};
        border-radius: 11px;
        padding: 5px 12px;
        color: {accent};
        font-size: 12px;
    }}
    QLabel#PillDanger {{
        background: rgba(255, 107, 107, 0.12);
        border: 1px solid rgba(255, 107, 107, 0.35);
        border-radius: 11px;
        padding: 5px 12px;
        color: #FF9B9B;
        font-size: 12px;
    }}
    QLabel#PillWarn {{
        background: rgba(245, 192, 107, 0.12);
        border: 1px solid rgba(245, 192, 107, 0.35);
        border-radius: 11px;
        padding: 5px 12px;
        color: #F5C06B;
        font-size: 12px;
    }}
    QLabel#ErrorText {{
        background: rgba(255, 107, 107, 0.08);
        border: 1px solid rgba(255, 107, 107, 0.28);
        border-radius: 8px;
        padding: 8px 10px;
        color: #FFB4B4;
        font-size: 12px;
    }}
    QLabel#ErrorBadge {{
        background: rgba(255, 107, 107, 0.16);
        border: 1px solid rgba(255, 107, 107, 0.5);
        border-radius: 20px;
        color: #FF8D8D;
        font-size: 22px;
        font-weight: 800;
    }}
    QLabel#DialogTitle {{
        color: #F2F4F9;
        font-size: 18px;
        font-weight: 700;
    }}
    QPlainTextEdit#Details {{
        background: #0A0D12;
        border: 1px solid #252C3A;
        border-radius: 8px;
        padding: 8px;
        color: #C8D0DE;
        font-family: "Consolas", "Cascadia Mono", monospace;
        font-size: 12px;
        selection-background-color: {accent};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: #0F131B;
        border: 1px solid #252C3A;
        border-radius: 9px;
        padding: 8px 11px;
        selection-background-color: {accent};
        min-height: 20px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {accent};
    }}
    QLineEdit:disabled, QComboBox:disabled {{
        color: #667086;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 26px;
    }}
    QComboBox QAbstractItemView {{
        background: #141821;
        border: 1px solid #252C3A;
        border-radius: 8px;
        selection-background-color: {soft};
        padding: 4px;
    }}
    QCheckBox {{
        spacing: 9px;
        color: #C6CDDB;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid #333C4E;
        background: #0F131B;
    }}
    QCheckBox::indicator:hover {{
        border-color: {accent};
    }}
    QCheckBox::indicator:checked {{
        background: {accent};
        border-color: {accent};
        image: none;
    }}
    QSlider::groove:horizontal {{
        height: 5px;
        background: #232A38;
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 8px;
        background: #FFFFFF;
        border: 3px solid {accent};
    }}
    QScrollArea {{
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #2A3242;
        border-radius: 5px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3A4356;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0;
    }}
    QPlainTextEdit#Console {{
        background: #0B0E14;
        border: 1px solid #1B202B;
        border-radius: 12px;
        padding: 10px;
        color: #A8B2C5;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
        selection-background-color: {accent};
    }}
    QListWidget {{
        background: #10141C;
        border: 1px solid #1E2430;
        border-radius: 12px;
        padding: 6px;
    }}
    QListWidget::item {{
        border-radius: 8px;
        padding: 10px 12px;
        color: #C6CDDB;
    }}
    QListWidget::item:hover {{
        background: #171C26;
    }}
    QListWidget::item:selected {{
        background: {soft};
        color: #FFFFFF;
    }}
    QTableWidget {{
        background: #10141C;
        border: 1px solid #1E2430;
        border-radius: 12px;
        gridline-color: #1B202B;
        alternate-background-color: #12161F;
    }}
    QTableWidget::item {{
        padding: 8px;
    }}
    QTableWidget::item:selected {{
        background: {soft};
        color: #FFFFFF;
    }}
    QHeaderView::section {{
        background: #10141C;
        color: #7C8598;
        border: none;
        border-bottom: 1px solid #1E2430;
        padding: 9px 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QProgressBar {{
        background: #1A1F2A;
        border: none;
        border-radius: 5px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {accent};
        border-radius: 5px;
    }}
    QTabWidget::pane {{
        border: 1px solid #1E2430;
        border-radius: 14px;
        background: #10141C;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: #8A93A6;
        padding: 9px 20px;
        margin-right: 4px;
        border-radius: 9px;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{
        color: #D6DBE6;
        background: #171C26;
    }}
    QTabBar::tab:selected {{
        color: #FFFFFF;
        background: {soft};
    }}
    QToolTip {{
        background: #1A1F2A;
        color: #E7EAF2;
        border: 1px solid #2A3242;
        border-radius: 6px;
        padding: 6px;
    }}
    QMessageBox {{
        background: #141821;
    }}
    QDialog {{
        background: #0F1219;
    }}
    QMenu {{
        background: #141821;
        border: 1px solid #252C3A;
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 18px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {soft};
    }}
    """


def apply_theme(app: QApplication, accent: str | None = None) -> None:
    color = accent or DEFAULT_ACCENT
    app.setStyleSheet(build_stylesheet(color))
    # 部分原生视图（表格选中行）使用调色板绘制，QSS 无法完全覆盖。
    palette = app.palette()
    selection = QColor(color).darker(230)
    palette.setColor(QPalette.ColorRole.Highlight, selection)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_ink(selection.name())))
    if hasattr(QPalette.ColorRole, "Accent"):
        palette.setColor(QPalette.ColorRole.Accent, selection)
    app.setPalette(palette)


def app_icon(accent: str = DEFAULT_ACCENT) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(accent))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.drawRoundedRect(0, 0, 64, 64, 15, 15)
    painter.setPen(QColor(_ink(accent)))
    font = painter.font()
    font.setPointSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), int(0x84), "M")
    painter.end()
    return QIcon(pixmap)
