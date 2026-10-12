"""离屏渲染多尺寸应用图标并拼成 Windows .ico（PNG-in-ICO）。
图标设计：橙色圆角方块 + 白色 ZiGAA 字样，作为软件名称标识。
"""
import os
import struct
import sys

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from styles import COLORS

ACCENT = QColor(COLORS["accent_orange"])
WORDMARK_TEXT = "ZiGAA"


def _ensure_wordmark_font() -> str:
    """显式加载 Microsoft YaHei 字体文件，避免离屏/无 GUI 环境下出现豆腐块。

    依次尝试加粗版与常规版；均失败时回退到字体名称，由 Qt 在运行时解析。
    """
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            fid = QFontDatabase.addApplicationFont(path)
            if fid != -1:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    print(f"[gen_icon] loaded wordmark font: {path} -> {families[0]}")
                    return families[0]
    print("[gen_icon] warning: could not load explicit wordmark font, falling back to Microsoft YaHei")
    return "Microsoft YaHei"


def paint_wordmark(p, size, text, color, font_family="Microsoft YaHei"):
    """在正方形画布内居中绘制自适应缩放的单词字样。"""
    margin = size * 0.12
    max_w = size - 2 * margin
    max_h = size - 2 * margin
    font = QFont(font_family, int(size * 0.6))
    font.setBold(True)
    p.setFont(font)
    fm = QFontMetrics(font)
    w = fm.horizontalAdvance(text)
    h = fm.height()
    scale = min(max_w / w, max_h / h)
    font.setPointSizeF(font.pointSizeF() * scale)
    p.setFont(font)
    p.setPen(color)
    p.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, text)


def draw_icon(size: int, font_family: str = "Microsoft YaHei") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # 橙色圆角方块背景
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)

    # 白色 ZiGAA 字样（自适应缩放、居中）
    paint_wordmark(p, size, WORDMARK_TEXT, QColor("#FFFFFF"), font_family)
    p.end()
    return pm


def main():
    app = QApplication(sys.argv)
    font_family = _ensure_wordmark_font()
    here = os.path.dirname(os.path.abspath(__file__))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = {}
    for s in sizes:
        pm = draw_icon(s, font_family)
        path = os.path.join(here, f"_icon_{s}.png")
        pm.save(path, "PNG")
        with open(path, "rb") as f:
            pngs[s] = f.read()
        os.remove(path)

    # 拼装 PNG-in-ICO
    ico_path = os.path.join(here, "app_icon.ico")
    header = b"\x00\x00" + b"\x01\x00" + struct.pack("<H", len(pngs))
    entries = []
    offset = 6 + 16 * len(pngs)
    for s in sizes:
        data = pngs[s]
        w = s if s < 256 else 0
        h = s if s < 256 else 0
        entry = bytes([w, h, 0, 0]) + struct.pack("<HH", 1, 32) + \
            struct.pack("<I", len(data)) + struct.pack("<I", offset)
        entries.append(entry)
        offset += len(data)
    ico = header + b"".join(entries) + b"".join(pngs[s] for s in sizes)
    with open(ico_path, "wb") as f:
        f.write(ico)
    print("wrote", ico_path, len(ico), "bytes; sizes:", sizes)


if __name__ == "__main__":
    main()
