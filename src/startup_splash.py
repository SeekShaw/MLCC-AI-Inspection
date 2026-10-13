"""启动加载窗（Splash）：双击 exe 后、主窗口出现前的「正在打开 + 进度」反馈。

设计约束：
- 只依赖 PyQt6，**不导入 app / styles 等重模块**——入口 main_b.py 会在
  `from app import run`（触发 production_view / debug_view 等重导入）之前先创建本窗，
  让用户在导入与界面构建期间立即看到明确反馈；
- set_status / set_progress 内部都会立即 processEvents（排除用户输入事件），
  保证在主事件循环尚未启动的「导入 / 界面构建」阶段也能实时刷新；
- finish() 淡出后关闭，避免主窗口出现瞬间的闪跳。

注意：PyInstaller 单文件引导的解压阶段发生在任何 Python 代码之前，本窗无法覆盖；
覆盖范围为「Python 导入 → 主界面构建」全过程（通常也是等待的主要部分）。
"""
import os
import sys

from PyQt6.QtCore import Qt, QRect, QEventLoop, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPainterPath, QIcon
from PyQt6.QtWidgets import (
    QWidget, QLabel, QProgressBar, QVBoxLayout, QHBoxLayout, QApplication,
)

SOFTWARE_NAME = "电子元件视觉检测系统"
# 与 output/ 下 exe 名后缀（_V3.0）保持一致；软件构建号见 app.APP_VERSION
VERSION = "V3.0"

# 与 styles.py 暗色主题一致的取色（启动早于主题加载，故内联一份）
C_BG = "#23252B"
C_CARD = "#2A2D35"
C_BORDER = "#3A3E47"
C_TEXT = "#FFFFFF"
C_TEXT2 = "#9CA3AF"
C_BLUE = "#4261FF"

_WIN_W, _WIN_H = 480, 250


def _load_app_icon():
    """优先取 exe 同级 / 工程根的 app_icon.ico（多档尺寸原生图标）。"""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                  "app_icon.ico"))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        cands.append(os.path.join(os.path.dirname(here), "app_icon.ico"))
        cands.append(os.path.join(here, "app_icon.ico"))
    for p in cands:
        try:
            if os.path.exists(p):
                # 用 QIcon 取 .ico 内最大一档原生帧（QPixmap 直接读 ico 会取到
                # 32×32 小档，拉伸后 logo 模糊）；再由调用方平滑缩放到目标尺寸。
                icon = QIcon(p)
                sizes = icon.availableSizes()
                if sizes:
                    best = max(sizes, key=lambda s: s.width() * s.height())
                    pm = icon.pixmap(best)
                else:
                    pm = QPixmap(p)
                if not pm.isNull():
                    return pm
        except Exception:
            continue
    return None


def _fallback_icon_pixmap():
    """无 ico 时绘制一枚蓝色圆角方块 + ✦ 作为占位图标。"""
    pm = QPixmap(72, 72)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRect(2, 2, 68, 68), 14, 14)
    p.fillPath(path, QColor(C_BLUE))
    f = QFont("Microsoft YaHei", 30)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRect(2, 2, 68, 68), Qt.AlignmentFlag.AlignCenter, "✦")
    p.end()
    return pm


class StartupSplash(QWidget):
    """无边框启动加载窗：图标 + 名称/版本 + 状态文字 + 进度条。"""

    def __init__(self, title=SOFTWARE_NAME, version=VERSION, parent=None):
        super().__init__(parent)
        self.setObjectName("splashRoot")
        # 无边框 + 置顶 + 不进任务栏（SplashScreen）
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.SplashScreen)
        self.setFixedSize(_WIN_W, _WIN_H)
        self.setStyleSheet(
            f"QWidget#splashRoot {{ background-color: {C_BG}; "
            f"border: 1px solid {C_BORDER}; border-radius: 10px; }}"
            f"QLabel {{ background: transparent; }}")

        # ⚠️ 不要给整窗挂 QGraphicsDropShadowEffect：主事件循环未启动时界面靠
        # processEvents 刷新，特效栅格化重绘会产生文字/百分比「重影」（真机实测）。
        # 阴影改为不可见窗口 margins + 背景层的简易方案成本过高，这里直接省略阴影。

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(0)

        # 顶部：图标 + 名称 / 版本
        top = QHBoxLayout()
        top.setSpacing(16)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(72, 72)
        pm = _load_app_icon()
        icon_lbl.setPixmap((pm if pm is not None else _fallback_icon_pixmap())
                           .scaled(72, 72,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))
        top.addWidget(icon_lbl)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name_lbl = QLabel(title)
        name_lbl.setStyleSheet(f"color: {C_TEXT}; font-size: 17px; font-weight: bold;")
        ver_lbl = QLabel(f"版本 {version}")
        ver_lbl.setStyleSheet(
            f"color: {C_TEXT2}; font-size: 11px; "
            f"background-color: {C_CARD}; border-radius: 8px; padding: 1px 8px;")
        ver_lbl.setFixedHeight(20)
        dev_lbl = QLabel("开发：ZY.SHAW")
        dev_lbl.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        name_box.addWidget(name_lbl)
        name_box.addWidget(ver_lbl)
        name_box.addWidget(dev_lbl)
        name_box.addStretch(1)
        top.addLayout(name_box, 1)
        root.addLayout(top)
        root.addStretch(1)

        # 中部：状态文字
        self._status = QLabel("正在打开…")
        self._status.setStyleSheet(f"color: {C_TEXT2}; font-size: 12px;")
        root.addWidget(self._status)
        root.addSpacing(8)

        # 底部：进度条 + 百分比
        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)
        self._bar = QProgressBar()
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 0)  # 初始为「未知进度」忙碌态
        self._bar.setStyleSheet(
            f"QProgressBar {{ background-color: {C_CARD}; border: none; "
            f"border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background-color: {C_BLUE}; border-radius: 4px; }}")
        bar_row.addWidget(self._bar, 1)
        self._pct_lbl = QLabel("")
        self._pct_lbl.setFixedWidth(38)
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._pct_lbl.setStyleSheet(f"color: {C_TEXT2}; font-size: 11px;")
        bar_row.addWidget(self._pct_lbl)
        root.addLayout(bar_row)

        self._center()

    # ---------------- 内部 ----------------
    def _center(self):
        try:
            scr = QApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                self.move(g.center().x() - self.width() // 2,
                          g.center().y() - self.height() // 2)
        except Exception:
            pass

    def _poke(self):
        """主事件循环未启动时立即刷新界面（排除用户输入，避免重入）。"""
        try:
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        except Exception:
            pass

    # ---------------- 公开 API ----------------
    def set_status(self, text):
        """只更新状态文字（进度保持忙碌态）。"""
        self._status.setText(text or "")
        self._poke()

    def set_busy(self, on=True):
        """未知进度：忙碌动画条（仅在事件循环运转时才有动画）。"""
        if on:
            self._bar.setRange(0, 0)
            self._pct_lbl.setText("")
        else:
            self._bar.setRange(0, 100)
            self._bar.setValue(0)
            self._pct_lbl.setText("0%")

    def set_progress(self, value, text=None):
        """确定进度 0~100；首次调用自动从忙碌态切换为确定态。"""
        try:
            v = int(value)
        except Exception:
            return
        v = 0 if v < 0 else (100 if v > 100 else v)
        if self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._bar.setValue(v)
        self._pct_lbl.setText(f"{v}%")
        if text:
            self._status.setText(text)
        self._poke()

    def finish(self, main_window=None):
        """主窗口已显示：收尾到 100% 后淡出关闭。"""
        try:
            self._status.setText("启动完成")
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setValue(100)
            self._pct_lbl.setText("100%")
            self._poke()
        except Exception:
            pass
        self._fade_out()

    def _fade_out(self):
        try:
            ani = QPropertyAnimation(self, b"windowOpacity", self)
            ani.setDuration(180)
            ani.setStartValue(1.0)
            ani.setEndValue(0.0)
            ani.setEasingCurve(QEasingCurve.Type.OutCubic)
            ani.finished.connect(self.close)
            ani.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception:
            self.close()
