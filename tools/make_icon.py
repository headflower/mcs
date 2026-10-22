"""生成 Windows 应用图标（PNG + 多尺寸 ICO）。

用法：
    .\\.venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PIL import Image
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPixmap

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ACCENT = "#7C5CFF"


def draw_icon(size: int = 512) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#9377FF"))
    gradient.setColorAt(1.0, QColor("#5D3FE8"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", weight=QFont.Weight.Black)
    font.setPixelSize(int(size * 0.58))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "M")
    painter.end()
    return pixmap


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    png_path = ASSETS / "mcs.png"
    ico_path = ASSETS / "mcs.ico"
    pixmap = draw_icon(512)
    if not pixmap.save(str(png_path), "PNG"):
        raise SystemExit("无法写入 PNG 图标")

    with Image.open(png_path) as image:
        image.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    app.quit()
    print(f"icon: {ico_path} ({ico_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
