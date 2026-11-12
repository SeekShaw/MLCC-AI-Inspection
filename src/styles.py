# 全局样式表与配色常量
import os
import sys
import json

from PyQt6.QtWidgets import QApplication


# --------------------------------------------------------------------------
# 暗色（默认）与亮色两套配色；COLORS 为可变字典，set_theme 原地替换，
# 已 `from styles import COLORS` 的模块在替换后即时可见新值。
# --------------------------------------------------------------------------
DARK_COLORS = {
    "bg_dark": "#1A1B1F",
    "bg_panel": "#23252B",
    "bg_card": "#2A2D35",
    "border": "#3A3E47",
    "text_primary": "#FFFFFF",
    "text_secondary": "#9CA3AF",
    "accent_orange": "#E95420",
    "accent_green": "#0D822B",
    "accent_red": "#C81435",
    "accent_blue": "#4261FF",
    "accent_yellow": "#F9AA0B",
    "ok": "#0D822B",
    "ng": "#C81435",
    "warn": "#F9AA0B",
}

LIGHT_COLORS = {
    "bg_dark": "#EDEEF1",
    "bg_panel": "#FFFFFF",
    "bg_card": "#F6F7F9",
    "border": "#D4D7DD",
    "text_primary": "#1F2329",
    "text_secondary": "#5C6670",
    "accent_orange": "#E95420",
    "accent_green": "#0D822B",
    "accent_red": "#C81435",
    "accent_blue": "#4261FF",
    "accent_yellow": "#F9AA0B",
    "ok": "#0D822B",
    "ng": "#C81435",
    "warn": "#F9AA0B",
}

# 可变 COLORS：set_theme 原地替换，已 `from styles import COLORS` 的模块即时可见
COLORS = dict(DARK_COLORS)

_THEME_NAME = "dark"

# 重新着色回调注册表：各组件构造时登记 _restyle 闭包，切换主题时统一触发
_RESTYLE_CALLBACKS = []


def register_restyle(fn):
    """登记一个无参回调，主题切换时统一调用（组件自我重绘）。"""
    if callable(fn):
        _RESTYLE_CALLBACKS.append(fn)


def emit_restyle():
    for fn in list(_RESTYLE_CALLBACKS):
        try:
            fn()
        except Exception:
            pass


def _config_dir():
    """配置目录：打包后为 exe 所在目录，开发时为脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_theme_name():
    return _THEME_NAME


def _theme_path():
    return os.path.join(_config_dir(), "theme.json")


def _save_theme(name):
    try:
        with open(_theme_path(), "w", encoding="utf-8") as f:
            json.dump({"theme": name}, f)
    except Exception:
        pass


def _load_theme():
    """读取持久化的主题偏好（暗/亮），缺失或损坏时回退暗色。"""
    global _THEME_NAME
    try:
        with open(_theme_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("theme")
        if name in ("dark", "light"):
            _THEME_NAME = name
    except Exception:
        pass


def build_main_style():
    """由当前 COLORS 生成全局 QSS（基础控件：窗体/按钮/输入/表格/滚动条等）。"""
    return f"""
QMainWindow {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text_primary"]};
}}

QWidget {{
    background-color: transparent;
    color: {COLORS["text_primary"]};
    font-family: "Microsoft YaHei", "Noto Sans SC", sans-serif;
}}

QLabel {{
    color: {COLORS["text_primary"]};
    background-color: transparent;
}}

/* 悬停提示：显式给定底色与文字色，避免被 QWidget 的透明背景规则影响导致文字不可见 */
QToolTip {{
    background-color: {COLORS["bg_panel"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    padding: 4px 8px;
}}

QPushButton {{
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
}}

QPushButton:hover {{
    background-color: {COLORS["border"]};
}}

QPushButton:pressed {{
    background-color: {COLORS["accent_orange"]};
}}

QLineEdit {{
    background-color: {COLORS["bg_dark"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    padding: 4px 8px;
    color: {COLORS["text_primary"]};
}}

QComboBox {{
    background-color: {COLORS["bg_dark"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    padding: 4px 8px;
    color: {COLORS["text_primary"]};
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text_primary"]};
    selection-background-color: {COLORS["accent_orange"]};
}}

QTableWidget {{
    background-color: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border"]};
    gridline-color: {COLORS["border"]};
    color: {COLORS["text_primary"]};
}}

QTableWidget::item {{
    padding: 6px;
    border-bottom: 1px solid {COLORS["border"]};
}}

QTableWidget::item:selected {{
    background-color: {COLORS["accent_orange"]};
}}

QHeaderView::section {{
    background-color: {COLORS["bg_panel"]};
    color: {COLORS["text_primary"]};
    padding: 6px;
    border: 1px solid {COLORS["border"]};
    font-weight: bold;
}}

QScrollBar:vertical {{
    background-color: {COLORS["bg_dark"]};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS["border"]};
    border-radius: 4px;
}}

QGroupBox {{
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {COLORS["text_secondary"]};
}}

/* 2026-11-12 UI 需求：全局统一方形/圆形勾选框样式——
   未勾选：白色（暗色主题 text_primary）空心边框；
   勾选：蓝色实心。**纯色填充、不依赖图片**——规避 QSS `image: url()` 加载失败时
   整条 `:checked` 规则被丢弃导致的「已勾选但外观不变」（如权限/剔除勾选框
   勾选态不显示）。方块(QCheckBox) / 圆形(QRadioButton) 同规格。 */
QCheckBox::indicator, QGroupBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid {COLORS["text_primary"]};
    background-color: transparent;
}}
QCheckBox::indicator:hover, QGroupBox::indicator:hover {{
    border-color: {COLORS["accent_blue"]};
}}
QCheckBox::indicator:checked, QGroupBox::indicator:checked {{
    border: 1px solid {COLORS["accent_blue"]};
    background-color: {COLORS["accent_blue"]};
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 1px solid {COLORS["text_primary"]};
    background-color: transparent;
}}
QRadioButton::indicator:hover {{
    border-color: {COLORS["accent_blue"]};
}}
QRadioButton::indicator:checked {{
    border: 1px solid {COLORS["accent_blue"]};
    background-color: {COLORS["accent_blue"]};
}}
"""

MAIN_STYLE = build_main_style()


def set_theme(name):
    """切换暗/亮主题：原地替换 COLORS、重建全局 QSS 并应用到应用、触发各组件重绘。"""
    global COLORS, _THEME_NAME, MAIN_STYLE
    if name not in ("dark", "light"):
        return
    _THEME_NAME = name
    COLORS.clear()
    COLORS.update(DARK_COLORS if name == "dark" else LIGHT_COLORS)
    MAIN_STYLE = build_main_style()
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(MAIN_STYLE)
    emit_restyle()
    _save_theme(name)


# 启动时按持久化偏好初始化（在模块导入末尾执行）
_load_theme()
if _THEME_NAME == "light":
    COLORS.clear()
    COLORS.update(LIGHT_COLORS)
    MAIN_STYLE = build_main_style()


# 按钮变体样式
BTN_PRIMARY = f"""
    background-color: {COLORS["accent_orange"]};
    color: white;
"""

BTN_SUCCESS = f"""
    background-color: {COLORS["accent_green"]};
    color: white;
"""

BTN_DANGER = f"""
    background-color: {COLORS["accent_red"]};
    color: white;
"""

BTN_GHOST = f"""
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
"""
