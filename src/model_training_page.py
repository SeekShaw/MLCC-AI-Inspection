# -*- coding: utf-8 -*-
"""「模型训练助手」应用内占位页（2026-11-12 UI 需求）。

点击左侧导航 / 顶部标题栏「模型训练助手」时打开的**应用内页面**。当前各功能模块
（数据集管理 / 训练配置 / 训练监控 / 模型评估 / 模型部署 / 训练记录）尚未设计实现，
本页仅提供：标题栏、左侧模块导航、以及居中的「内容待设计」空状态提示，
避免打开后纯空白、像程序出错。后续按模块逐步填充真实功能即可。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QSizePolicy,
)

from styles import COLORS

# 占位模块导航（顺序即展示顺序；点击仅更新空状态标题，不做真实功能）
_NAV_ITEMS = (
    "数据集管理",
    "训练配置",
    "训练监控",
    "模型评估",
    "模型部署",
    "训练记录",
)


class ModelTrainingPage(QDialog):
    """模型训练助手占位页：左侧模块导航 + 右侧「内容待设计」空状态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 独立进程窗口：允许最小化 / 隐藏 / 关闭，且始终置顶于主软件之上便于定位
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle("模型训练助手")
        self.resize(1000, 680)
        self.setMinimumSize(820, 560)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 左侧导航栏 ----
        nav = QWidget()
        nav.setFixedWidth(220)
        nav.setStyleSheet(f"background-color: {COLORS['bg_panel']};")
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(0)

        title = QLabel("模型训练助手")
        title.setContentsMargins(16, 18, 16, 0)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15px; "
            f"font-weight: bold;")
        nv.addWidget(title)
        sub = QLabel("Model Training Assistant")
        sub.setContentsMargins(16, 4, 16, 0)
        sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        nv.addWidget(sub)

        listw = QListWidget()
        listw.addItems(_NAV_ITEMS)
        listw.setCurrentRow(0)
        listw.setFrameShape(listw.Shape.NoFrame)
        listw.setSpacing(2)
        listw.setStyleSheet(
            f"QListWidget {{ background-color: transparent; "
            f"color: {COLORS['text_primary']}; font-size: 13px; "
            f"padding: 8px 0; outline: 0; border: none; }}"
            f"QListWidget::item {{ padding: 10px 16px; }}"
            f"QListWidget::item:hover {{ background-color: {COLORS['bg_card']}; }}"
            f"QListWidget::item:selected {{ background-color: {COLORS['accent_blue']}; "
            f"color: #FFFFFF; border-radius: 4px; }}")
        nv.addWidget(listw, 1)
        root.addWidget(nav)

        # ---- 右侧主区：空状态提示 ----
        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)

        state = QWidget()
        sv = QVBoxLayout(state)
        sv.setSpacing(12)
        sv.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🧠")
        icon.setStyleSheet(f"font-size: 56px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sv.addWidget(icon)

        self._state_big = QLabel("内容待设计")
        self._state_big.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 20px; "
            f"font-weight: bold;")
        self._state_big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sv.addWidget(self._state_big)

        self._state_sub = QLabel("该模块界面正在规划设计中，敬请期待。")
        self._state_sub.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13px;")
        self._state_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sv.addWidget(self._state_sub)

        mv.addStretch(1)
        mv.addWidget(state, alignment=Qt.AlignmentFlag.AlignCenter)
        mv.addStretch(1)
        root.addWidget(main, 1)

        listw.currentTextChanged.connect(self._on_nav)
        self._state_big.setText(f"「{_NAV_ITEMS[0]}」内容待设计")

    def _on_nav(self, text: str):
        """切换左侧模块时，仅更新空状态标题（真实功能待设计）。"""
        if text:
            self._state_big.setText(f"「{text}」内容待设计")
