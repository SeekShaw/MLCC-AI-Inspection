"""新增导航功能按钮对应的对话框：系统配置 / 盒子监控 / 高级设置 / 日志管理 / 生产报表占位。

这些窗口由 MainWindow 的导航功能按钮打开；主题切换时通过 styles.COLORS（可变字典，
set_theme 原地替换）即时取色，因此创建时调用样式函数即可拿到当前主题配色。
"""
from __future__ import annotations

import json
import os

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QProgressBar, QListWidget, QListWidgetItem, QLineEdit,
    QTableWidget, QTableWidgetItem, QTabWidget, QSplitter, QAbstractItemView,
    QHeaderView, QComboBox, QGridLayout, QFrame, QScrollArea, QSpinBox,
    QListView, QFileDialog, QMessageBox,
)
from PyQt6.QtGui import (QPainter, QColor, QStandardItem, QStandardItemModel,
                         QFont, QFontMetrics)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent

import styles
from styles import COLORS
from user_manager import UserManager as _UserManager
from alarm_config import ALARM, save_alarm_config, feature_auto_clear

# 密码输入确认时间周期可选值（与用户配置保持一致，避免两处硬编码走样）
UM_CONFIRM_OPTIONS = _UserManager.confirm_interval_options()
# 玻璃盘清洁提示时间周期可选值（与用户配置保持一致）
UM_GLASS_CLEAN_OPTIONS = _UserManager.GLASS_CLEAN_OPTIONS


def _group_style():
    return (
    f"QGroupBox {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
    f"border: 1px solid {COLORS['border']}; border-radius: 8px; margin-top: 10px; "
    f"padding-top: 10px; font-weight: bold; font-size: 12px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; "
        f"color: {COLORS['text_secondary']}; }}"
    )


def _prog_normal():
    return (
        f"QProgressBar {{ background-color: {COLORS['bg_dark']}; border: 1px solid {COLORS['border']}; "
        f"border-radius: 4px; text-align: center; color: {COLORS['text_primary']}; }}"
        f"QProgressBar::chunk {{ background-color: {COLORS['accent_blue']}; border-radius: 3px; }}"
    )


def _prog_full():
    return (
        f"QProgressBar {{ background-color: {COLORS['bg_dark']}; border: 1px solid {COLORS['border']}; "
        f"border-radius: 4px; text-align: center; color: white; }}"
        f"QProgressBar::chunk {{ background-color: {COLORS['accent_red']}; border-radius: 3px; }}"
    )


def _dialog_base(d, title, w=440, h=320):
    d.setWindowTitle(title)
    d.setMinimumSize(w, h)
    d.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")


# ---------------------------------------------------------------------------
# 日志保存配置（启用日志保存 / 保存天数 / 硬盘剩余空间监控）持久化
# 默认：未启用、保存 3 天、硬盘剩余空间低于 10GB 时告警。
# ---------------------------------------------------------------------------
def _log_save_cfg_path():
    """配置落盘路径：与 exe 或脚本同目录（优先跟随可执行文件所在目录）。"""
    import sys
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "log_save_config.json")


def _load_log_save_cfg():
    try:
        with open(_log_save_cfg_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    return {
        "enabled": bool(d.get("enabled", False)),
        "days": int(d.get("days", 3)),
        "disk_gb": int(d.get("disk_gb", 10)),
    }


def _save_log_save_cfg(cfg):
    try:
        with open(_log_save_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class BoxMonitorDialog(QDialog):
    """盒子监控：实时显示 OK / NG1 / NG2 / RST 四个料盒的收料数量、容量与满料状态。"""

    _KEYS = [("OK", "OK 料盒"), ("NG1", "NG1 料盒"),
             ("NG2", "NG2 料盒"), ("RST", "RST 料盒")]

    def __init__(self, pv, parent=None):
        super().__init__(parent)
        self.pv = pv
        _dialog_base(self, "盒子监控", 480, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        self._bars = {}
        for key, label in self._KEYS:
            box = QGroupBox(label)
            box.setStyleSheet(_group_style())
            bl = QVBoxLayout(box)
            cnt = QLabel("数量：0 / 0")
            cnt.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px;")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(18)
            bar.setStyleSheet(_prog_normal())
            pct = QLabel("0.0%")
            pct.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            bl.addWidget(cnt)
            bl.addWidget(bar)
            bl.addWidget(pct)
            lay.addWidget(box)
            self._bars[key] = (cnt, bar, pct)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._refresh()
        self._timer.start()

    def _refresh(self):
        st = self.pv.get_bin_status() if hasattr(self.pv, "get_bin_status") else {}
        for key, (cnt, bar, pct) in self._bars.items():
            info = st.get(key, {})
            c = info.get("count", 0)
            cap = info.get("capacity", 0)
            p = info.get("pct", 0.0)
            full = info.get("full", False)
            cnt.setText(f"数量：{c} / {cap}")
            bar.setValue(int(round(p)))
            pct.setText(f"{p:.1f}%")
            bar.setStyleSheet(_prog_full() if full else _prog_normal())

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


class LogManagerDialog(QDialog):
    """日志管理：展示运行操作日志（最近 200 条），可手动刷新。"""

    def __init__(self, pv, parent=None):
        super().__init__(parent)
        self.pv = pv
        _dialog_base(self, "日志管理", 580, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # 顶部：启用日志保存开关 + 保存天数 / 硬盘剩余空间监控
        cfg = _load_log_save_cfg()
        top = QHBoxLayout()
        top.setSpacing(12)
        self._log_save_sw = ToggleSwitch(checked=cfg["enabled"])
        self._log_save_sw.toggled.connect(self._on_log_save_toggled)
        sw_lbl = QLabel("启用日志保存")
        sw_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; background-color: transparent;")
        top.addWidget(self._log_save_sw)
        top.addWidget(sw_lbl)

        top.addSpacing(16)
        day_lbl = QLabel("保存天数")
        day_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background-color: transparent;")
        self._log_save_days = QSpinBox()
        self._log_save_days.setRange(1, 365)
        self._log_save_days.setValue(cfg["days"])
        self._log_save_days.setSuffix(" 天")
        self._log_save_days.setMinimumHeight(26)
        self._log_save_days.setStyleSheet(self._spin_style())
        self._log_save_days.valueChanged.connect(lambda _v: self._on_log_save_cfg_changed())
        top.addWidget(day_lbl)
        top.addWidget(self._log_save_days)

        top.addSpacing(16)
        disk_lbl = QLabel("硬盘剩余空间监控")
        disk_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background-color: transparent;")
        self._log_save_disk = QSpinBox()
        self._log_save_disk.setRange(1, 1000)
        self._log_save_disk.setValue(cfg["disk_gb"])
        self._log_save_disk.setSuffix(" GB")
        self._log_save_disk.setMinimumHeight(26)
        self._log_save_disk.setStyleSheet(self._spin_style())
        self._log_save_disk.valueChanged.connect(lambda _v: self._on_log_save_cfg_changed())
        top.addWidget(disk_lbl)
        top.addWidget(self._log_save_disk)
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self._h_line())

        tip = QLabel("操作日志记录（最近 200 条）")
        tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        lay.addWidget(tip)
        self.list_w = QListWidget()
        self.list_w.setStyleSheet(
            f"QListWidget {{ background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; color: {COLORS['text_primary']}; }}"
            f"QListWidget::item {{ padding: 4px; border-bottom: 1px solid {COLORS['border']}; }}")
        lay.addWidget(self.list_w, 1)
        btn = QPushButton("刷新")
        btn.setFixedWidth(90)
        btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        btn.clicked.connect(self._refresh)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._refresh()

    # ------------------------------------------------------------------
    @staticmethod
    def _spin_style():
        return _spin_style()

    def _h_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLORS['border']};")
        return line

    def _on_log_save_toggled(self, checked):
        self._on_log_save_cfg_changed()

    def _on_log_save_cfg_changed(self):
        _save_log_save_cfg({
            "enabled": bool(self._log_save_sw.isChecked()),
            "days": int(self._log_save_days.value()),
            "disk_gb": int(self._log_save_disk.value()),
        })

    def _refresh(self):
        logs = self.pv.get_operation_logs() if hasattr(self.pv, "get_operation_logs") else []
        self.list_w.clear()
        for ts, actor, action in logs[-200:]:
            self.list_w.addItem(QListWidgetItem(f"{ts}    {actor}    {action}"))


def _spin_style():
    """数值输入框统一样式。

    与「触发设定」等其它页面完全一致（见 device_settings_dialog._spin_style）：
    暗底 + 圆角边框，仅把上/下按钮宽度收窄到 16px，**不覆盖**按钮底色与箭头，
    箭头交由 Qt 默认绘制 —— 深色主题下才不会被自绘三角/QSS 三角渲染成
    越界方块（此前ArrowSpinBox 自绘的三角会溢出到输入框右侧框外）。
    """
    return (
        f"QSpinBox {{ background-color: {COLORS['bg_card']}; "
        f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
        f"border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
        f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
    )


class CheckableCombo(QComboBox):
    """可多选下拉：弹层条目带复选框，点击仅切换勾选、弹层不关闭；
    已勾选项以「、」拼接显示在只读输入框内。"""

    def __init__(self, items, placeholder="请选择（可多选）", parent=None):
        super().__init__(parent)
        self.setEditable(True)
        le = self.lineEdit()
        le.setReadOnly(True)
        le.setPlaceholderText(placeholder)
        self._model = QStandardItemModel(self)
        for t in items:
            it = QStandardItem(t)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self._model.appendRow(it)
        self.setModel(self._model)
        self.setView(QListView(self))
        # 弹层视口事件过滤：鼠标点击 → 手动切换勾选并吞掉事件，避免弹层关闭
        self.view().viewport().installEventFilter(self)
        self._model.itemChanged.connect(lambda _it: self._sync_text())
        self._sync_text()

    # ------------------------------------------------------------------
    def checked_items(self):
        """返回已勾选条目文本列表（按弹层顺序）。"""
        out = []
        for r in range(self._model.rowCount()):
            it = self._model.item(r)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.text())
        return out

    def set_checked(self, names):
        """按文本列表勾选/取消勾选（不在列表中的条目全部取消）。"""
        want = set(names or [])
        for r in range(self._model.rowCount()):
            it = self._model.item(r)
            it.setCheckState(Qt.CheckState.Checked if it.text() in want
                             else Qt.CheckState.Unchecked)

    def _sync_text(self):
        self.lineEdit().setText("、".join(self.checked_items()))

    def eventFilter(self, obj, event):
        if obj is self.view().viewport() and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick):
            idx = self.view().indexAt(event.position().toPoint())
            if idx.isValid():
                cur = idx.data(Qt.ItemDataRole.CheckStateRole)
                new = (Qt.CheckState.Unchecked if cur == Qt.CheckState.Checked
                       else Qt.CheckState.Checked)
                self._model.setData(idx, new, Qt.ItemDataRole.CheckStateRole)
            return True
        return super().eventFilter(obj, event)


class SimulateProductionDialog(QDialog):
    """模拟生产：开关（默认关闭）+ 8 路相机各自的模拟图片来源路径设置。

    设备处于「生产运行中」时不允许打开（入口按钮已置灰），因此这里只负责
    编辑并落盘配置；设置完毕后由用户点击「设备启动」生效。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        _dialog_base(self, "模拟生产", 640, 460)
        import simulate_config as _simcfg
        self._simcfg = _simcfg
        self._cfg = _simcfg.load_cfg()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        #顶部：模拟生产开关（默认关闭）
        top = QHBoxLayout()
        top.setSpacing(10)
        self._enable_sw = ToggleSwitch(checked=bool(self._cfg.get("enabled", False)))
        top.addWidget(self._enable_sw)
        top.addWidget(self._label("启用模拟生产"))
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self._h_line())

        # 各相机模拟图片来源路径（8 路）
        paths = self._cfg.get("paths", {})
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for i, cam in enumerate(_simcfg.CAM_NAMES):
            grid.addWidget(self._label(cam), i, 0)
            edit = QLineEdit(str(paths.get(cam, "") or ""))
            edit.setMinimumHeight(28)
            edit.setPlaceholderText("未设置（留空则该相机使用内置示例图）")
            edit.setStyleSheet(self._input_style())
            grid.addWidget(edit, i, 1)
            btn = QPushButton("浏览")
            btn.setFixedWidth(60)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(self._browse_btn_style())
            btn.clicked.connect(
                lambda _=False, e=edit, c=cam: self._browse(e, c))
            grid.addWidget(btn, i, 2)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        # 底部按钮
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        save_btn = QPushButton("保存")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border-radius: 4px; padding: 6px 14px; font-size: 13px;")
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        close_btn.clicked.connect(self.close)
        btns.addWidget(save_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        # ⚠️ 需求：底部提示「设置完毕后点击设备启动即可模拟生产」
        tip = QLabel("设置完毕后点击设备启动即可模拟生产")
        tip.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"background-color: transparent;")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(tip)

        self._edits = {}
        for i, cam in enumerate(_simcfg.CAM_NAMES):
            w = grid.itemAtPosition(i, 1).widget()
            if w is not None:
                self._edits[cam] = w

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; "
            f"background-color: transparent;")
        return lbl

    def _h_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLORS['border']};")
        return line

    def _input_style(self):
        return (f"QLineEdit {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 12px; }}")

    def _browse_btn_style(self):
        return (f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
                f"color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"padding: 4px 10px; font-size: 12px; }}")

    def _browse(self, edit, cam):
        """为指定相机选择模拟图片文件。"""
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择{cam}模拟图片",
            edit.text() or "", "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if path:
            edit.setText(path)

    def _on_save(self):
        cfg = self._simcfg.default_cfg()
        cfg["enabled"] = bool(self._enable_sw.isChecked())
        for cam, edit in self._edits.items():
            cfg["paths"][cam] = edit.text().strip()
        self._simcfg.save_cfg(cfg)
        QMessageBox.information(
            self, "提示", "模拟生产设置已保存\n设置完毕后点击设备启动即可模拟生产")


class ImageSaveDialog(QDialog):
    """图片保存：启用图像保存开关 + 保存策略 / 检测项（多选）/ 保存格式 /
    缩放比例 / 图像质量 / 保存天数 / 保存路径 / 硬盘剩余空间监控 / 存满执行动作。"""

    SAVE_STRATEGIES = ["所有图像", "所有良品", "所有不良", "所有待定",
                       "所有不良+待定", "指定检测项不良"]
    SAVE_FORMATS = ["JPEG", "BMP", "PNG", "TIFF"]
    FULL_ACTIONS = ["停止存储", "覆盖存储"]

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        # ⚠️ 2026-10-09：配置区改为「每字段一行」后行数变少（原双列竖排占两行），
        # 高度从 620 收到 480：实测内容需要 ≈450px（检测项显示时），
        # 留少量余量即可，避免底部大片空白。
        _dialog_base(self, "图片保存", 500, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # 顶部：启用图像保存开关（关闭时下方配置区整体禁用）
        self._enable_sw = ToggleSwitch(checked=True)
        self._enable_sw.toggled.connect(self._on_enable_toggled)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._enable_sw)
        top.addWidget(self._label("启用图像保存"))
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self._h_line())

        # 配置区（受顶部开关统一启用/禁用）
        self._cfg_area = QWidget()
        body = QVBoxLayout(self._cfg_area)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        lay.addWidget(self._cfg_area)

        # ⚠️ 2026-10-09 需求：配置区**所有字段改为「标签 + 控件同一行」**，
        # 且所有行**同列对齐**（各行控件左缘严格对齐）。
        # 实现：先按最长标签实算统一标签列宽 `_lbl_w`，每个字段一个横向行
        # （`_field_row`），标签 `setFixedWidth(_lbl_w)` → 控件左缘自然对齐。
        # 这样保存策略/保存格式的下拉框也上移到与标题同一行。
        # ⚠️ 保存策略/保存格式已统一用字段样式（13px 常规字重），故标签列宽
        # 只需按**全部字段标签**用同一字体实算，不能再混用 12px 加粗的度量。
        _fm_lbl = QFontMetrics(QFont("Microsoft YaHei", 13))
        _ALL_LABELS = ("检测项", "保存策略", "保存格式", "缩放比例", "图像质量",
                       "保存天数", "硬盘剩余空间监控", "图片存满时执行动作",
                       "保存路径")
        _lbl_w = max(_fm_lbl.horizontalAdvance(t) for t in _ALL_LABELS) + 12

        def _field_row(text):
            """构造「标签 + 控件」同一行的横向布局（控件由调用方 addWidget 追加）。

            标签固定宽度 `_lbl_w`（由最长标签实算 +12 余量），
            保证**每一行的控件左缘严格对齐**（同列对齐）。
            ⚠️ 2026-10-09：所有字段标签（含保存策略 / 保存格式）统一用 `_label()`
            的字段样式（`text_primary` / 13px），不再用 `_section_label()` 的
            次级色加粗样式，保持同一列文字颜色字体一致。
            """
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            lbl = self._label(text)
            lbl.setFixedWidth(_lbl_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(lbl)
            return row

        # 保存策略（下拉框与标题同一行）
        _row = _field_row("保存策略")
        self._strategy = QComboBox()
        self._strategy.addItems(self.SAVE_STRATEGIES)
        self._strategy.setMinimumHeight(28)
        self._strategy.setStyleSheet(self._combo_style())
        self._strategy.currentTextChanged.connect(self._on_strategy_changed)
        _row.addWidget(self._strategy, 1)
        body.addLayout(_row)

        # 检测项（可多选）：仅当保存策略 = 「指定检测项不良」时显示
        self._defect_widget = QWidget()
        self._defect_row = QHBoxLayout(self._defect_widget)
        self._defect_row.setContentsMargins(0, 0, 0, 0)
        self._defect_row.setSpacing(8)
        self._defect_label = self._label("检测项")
        self._defect_label.setFixedWidth(_lbl_w)
        self._defect_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        try:
            from production_view import _DEFECT_TYPES
            defect_items = list(_DEFECT_TYPES)
        except Exception:
            defect_items = []
        self._defect_combo = CheckableCombo(defect_items)
        self._defect_combo.setMinimumHeight(28)
        self._defect_combo.setStyleSheet(self._combo_style())
        self._defect_row.addWidget(self._defect_label)
        self._defect_row.addWidget(self._defect_combo, 1)
        self._defect_widget.setVisible(False)
        body.addWidget(self._defect_widget)

        # 保存格式（下拉框与标题同一行）
        _row = _field_row("保存格式")
        self._fmt = QComboBox()
        self._fmt.addItems(self.SAVE_FORMATS)
        self._fmt.setMinimumHeight(28)
        self._fmt.setStyleSheet(self._combo_style())
        _row.addWidget(self._fmt, 1)
        body.addLayout(_row)

        # 缩放比例（默认 100%）
        _row = _field_row("缩放比例")
        self._scale = QSpinBox()
        self._scale.setRange(1, 300)
        self._scale.setValue(100)
        self._scale.setSuffix("%")
        self._scale.setMinimumHeight(28)
        self._scale.setStyleSheet(self._spin_style())
        _row.addWidget(self._scale, 1)
        body.addLayout(_row)

        # 图像质量（默认 100，可改）
        _row = _field_row("图像质量")
        self._quality = QSpinBox()
        self._quality.setRange(0, 100)
        self._quality.setValue(100)
        self._quality.setMinimumHeight(28)
        self._quality.setStyleSheet(self._spin_style())
        _row.addWidget(self._quality, 1)
        body.addLayout(_row)

        # 保存天数（默认 7 天）
        _row = _field_row("保存天数")
        self._days = QSpinBox()
        self._days.setRange(1, 365)
        self._days.setValue(7)
        self._days.setSuffix(" 天")
        self._days.setMinimumHeight(28)
        self._days.setStyleSheet(self._spin_style())
        _row.addWidget(self._days, 1)
        body.addLayout(_row)

        # 硬盘剩余空间监控（默认 10 GB）
        _row = _field_row("硬盘剩余空间监控")
        self._disk = QSpinBox()
        self._disk.setRange(1, 1000)
        self._disk.setValue(10)
        self._disk.setSuffix(" GB")
        self._disk.setMinimumHeight(28)
        self._disk.setStyleSheet(self._spin_style())
        _row.addWidget(self._disk, 1)
        body.addLayout(_row)

        # 图片存满时执行动作（停止存储 / 覆盖存储）
        _row = _field_row("图片存满时执行动作")
        self._full_action = QComboBox()
        self._full_action.addItems(self.FULL_ACTIONS)
        self._full_action.setMinimumHeight(28)
        self._full_action.setStyleSheet(self._combo_style())
        _row.addWidget(self._full_action, 1)
        body.addLayout(_row)

        # 保存路径（输入框 + 浏览按钮同列）
        _row = _field_row("保存路径")
        self._path_edit = QLineEdit()
        self._path_edit.setMinimumHeight(28)
        self._path_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 4px 8px; font-size: 12px; }}")
        browse_btn = QPushButton("浏览")
        browse_btn.setFixedWidth(60)
        browse_btn.setMinimumHeight(28)
        browse_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 10px; font-size: 12px;")
        browse_btn.clicked.connect(self._on_browse)
        _row.addWidget(self._path_edit, 1)
        _row.addWidget(browse_btn)
        body.addLayout(_row)

        body.addStretch(1)

        # 按钮区
        btns = QHBoxLayout()
        btns.setSpacing(8)
        save_btn = QPushButton("保存")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        close_btn.clicked.connect(self.close)
        btns.addStretch(1)
        btns.addWidget(save_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        self._restore_cfg(self._load_cfg())

    # ------------------------------------------------------------------
    @staticmethod
    def _combo_style():
        """下拉框样式：含弹层列表配色（修正下拉选项字体颜色）与只读编辑框。"""
        return (f"QComboBox {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 12px; "
                f"selection-background-color: {COLORS['accent_blue']}; selection-color: #FFFFFF; }}"
                f"QComboBox QLineEdit {{ background-color: transparent; border: none; "
                f"color: {COLORS['text_primary']}; }}"
                f"QComboBox::drop-down {{ border: none; width: 18px; }}"
                f"QComboBox QAbstractItemView {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; outline: none; }}"
                f"QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; "
                f"color: {COLORS['text_primary']}; }}"
                f"QComboBox QAbstractItemView::item:selected {{ "
                f"background-color: {COLORS['accent_blue']}; color: #FFFFFF; }}")

    @staticmethod
    def _spin_style():
        return _spin_style()

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; background-color: transparent;")
        return lbl

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold; "
            f"background-color: transparent;")
        return lbl

    def _h_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLORS['border']};")
        return line

    # ------------------------------------------------------------------
    def _cfg_path(self):
        """配置落盘路径：与 exe 或脚本同目录（优先跟随可执行文件所在目录）。"""
        import sys
        if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "image_save_config.json")

    def _load_cfg(self):
        import json
        try:
            with open(self._cfg_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cfg(self, cfg):
        import json
        try:
            with open(self._cfg_path(), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _restore_cfg(self, cfg):
        if "enabled" in cfg:
            self._enable_sw.setChecked(bool(cfg["enabled"]))
        if "strategy" in cfg:
            self._strategy.setCurrentText(cfg["strategy"])
        if "format" in cfg:
            self._fmt.setCurrentText(cfg["format"])
        self._scale.setValue(int(cfg.get("scale", 100)))
        self._quality.setValue(int(cfg.get("quality", 100)))
        self._days.setValue(int(cfg.get("days", 7)))
        self._disk.setValue(int(cfg.get("disk_gb", 10)))
        full_action = str(cfg.get("full_action") or "停止存储")
        if full_action in self.FULL_ACTIONS:
            self._full_action.setCurrentText(full_action)
        self._path_edit.setText(str(cfg.get("path") or self._default_save_path()))
        defects = cfg.get("defects")
        if isinstance(defects, list):
            self._defect_combo.set_checked(defects)
        self._on_strategy_changed(self._strategy.currentText())
        self._on_enable_toggled(self._enable_sw.isChecked())

    def _default_save_path(self):
        """默认保存路径：exe 或脚本同目录下的 images 子目录。"""
        import sys
        if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "images")

    def _on_enable_toggled(self, checked):
        """启用图像保存开关：控制下方整个配置区的可用态。"""
        self._cfg_area.setEnabled(bool(checked))

    def _on_strategy_changed(self, text):
        # 检测项（多选）行仅在「指定检测项不良」时显示
        self._defect_widget.setVisible(text == "指定检测项不良")

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择保存路径", self._path_edit.text().strip() or "")
        if d:
            self._path_edit.setText(os.path.normpath(d))

    def _on_save(self):
        strategy = self._strategy.currentText()
        cfg = {
            "enabled": bool(self._enable_sw.isChecked()),
            "strategy": strategy,
            "format": self._fmt.currentText(),
            "scale": self._scale.value(),
            "quality": self._quality.value(),
            "days": self._days.value(),
            "disk_gb": self._disk.value(),
            "path": self._path_edit.text().strip(),
            "full_action": self._full_action.currentText(),
            "defects": self._defect_combo.checked_items()
            if strategy == "指定检测项不良" else [],
        }
        self._save_cfg(cfg)
        if self._app is not None and hasattr(self._app, "production"):
            name = getattr(getattr(self._app, "current_user", None), "name", "用户")
            self._app.production.log_operation(
                name, f"图片保存配置：{'启用' if cfg['enabled'] else '停用'} "
                      f"策略={strategy} 格式={cfg['format']} "
                      f"缩放={cfg['scale']}% 质量={cfg['quality']} "
                      f"保存{cfg['days']}天 磁盘余量监控{cfg['disk_gb']}GB "
                      f"存满{cfg['full_action']}"
                      + (f" 检测项={'、'.join(cfg['defects'])}" if cfg["defects"] else ""))
        self.close()


class SystemConfigDialog(QDialog):
    """系统配置：智感盒子 / 检测线配置 / 相机配置 / 光源配置。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        _dialog_base(self, "系统配置", 1300, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        main = QHBoxLayout()
        main.setSpacing(10)

        # 左侧面板：智感盒子 + 检测线配置
        left = QVBoxLayout()
        left.setSpacing(10)

        box_table = self._make_table(["站点", "站点名称", "协议类型", "连接参数", "分组"])
        box_table.setObjectName("box_table")
        self._fill_table(box_table, [["1", "默认站点", "不使用控制器", "", "不编组"]])
        left.addWidget(self._wrap_group("智感盒子", box_table), 1)

        line_table = self._make_table(["线号", "线名", "最大触发数", "最大剔除数", "最大光源数", "组号"])
        line_table.setObjectName("line_table")
        self._fill_table(line_table, [["1", "检测线_0_0", "9", "8", "16", "不编组"]])
        left.addWidget(self._wrap_group("检测线配置", line_table), 2)

        left_w = QWidget()
        left_w.setLayout(left)
        main.addWidget(left_w, 5)

        # 右侧面板：相机配置 / 光源配置 标签页
        tabs = QTabWidget()
        tabs.setStyleSheet(self._tab_style())

        cam_table = self._make_table(["相机序号", "相机昵称", "相机类型", "连接参数", "组号"])
        self._fill_table(cam_table, [
            ["1", "相机_1", "ZGCamera", "", "不编组"],
            ["2", "相机2", "TriggerLocalFile", "demo", "不编组"],
        ])
        tabs.addTab(cam_table, "相机配置")

        light_widget = QWidget()
        light_lay = QVBoxLayout(light_widget)
        light_lay.setContentsMargins(8, 8, 8, 8)
        light_tip = QLabel("暂无光源配置数据")
        light_tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        light_lay.addWidget(light_tip)
        light_lay.addStretch(1)
        tabs.addTab(light_widget, "光源配置")

        main.addWidget(tabs, 4)
        lay.addLayout(main, 1)

        # 底部关闭按钮
        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 6px 14px; font-size: 13px;")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _make_table(self, headers):
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 列宽自适应填满，杜绝横向滚动条
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(False)
        table.verticalHeader().setVisible(False)
        # 双保险：即便极端情况下也不出现横向滚动条（内容会被压缩而非滚动）
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setStyleSheet(self._table_style())
        return table

    def _fill_table(self, table, rows):
        table.setRowCount(len(rows))
        for r, cols in enumerate(rows):
            for c, text in enumerate(cols):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                table.setItem(r, c, item)
        if rows:
            table.selectRow(0)

    def _wrap_group(self, title, widget):
        box = QGroupBox(title)
        box.setStyleSheet(_group_style())
        bl = QVBoxLayout(box)
        bl.setContentsMargins(8, 12, 8, 8)
        bl.addWidget(widget)
        return box

    def _table_style(self):
        return f"""
            QTableWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                gridline-color: {COLORS['border']};
                outline: none;
                font-size: 12px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                padding: 5px;
                font-weight: bold;
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                border: 1px solid {COLORS['accent_orange']};
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_primary']};
            }}
        """

    def _tab_style(self):
        return f"""
            QTabWidget::pane {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                padding: 8px 24px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['accent_blue']};
                border-bottom: 2px solid {COLORS['accent_blue']};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
            }}
        """


class AboutDialog(QDialog):
    """关于：显示当前软件信息（名称 / 版本 / 设备信息）与厂商信息。"""

    def __init__(self, parent=None, software_name="", version="",
                 device_code=None, company="", copyright_text=""):
        super().__init__(parent)
        _dialog_base(self, "关于", 520, 380)
        dev = dict(device_code or {})
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        # 标题：软件名称（大号）+ 版本（次要色）
        name = (software_name or "").strip() or "电子元件视觉检测系统"
        title = QLabel(name)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 18px; font-weight: bold; "
            f"background-color: transparent;")
        lay.addWidget(title)
        ver = QLabel(f"软件版本： {version}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13px; background-color: transparent;")
        lay.addWidget(ver)

        # 设备 / 厂商信息表（标签右对齐、取值左对齐）
        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        rows = [
            ("软件版本", version),
            ("设备编码", dev.get("设备编码", "")),
            ("设备名称", dev.get("设备名称", "")),
            ("产线编号", dev.get("产线编号", "")),
            ("厂商名称", company),
            ("版权信息", copyright_text),
        ]
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k + "：")
            kl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12px; "
                f"background-color: transparent;")
            kl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            vl = QLabel(str(v or "—"))
            vl.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 12px; "
                f"background-color: transparent;")
            vl.setWordWrap(True)
            grid.addWidget(kl, r, 0)
            grid.addWidget(vl, r, 1)
        grid.setColumnStretch(1, 1)
        self._rows = [(k, str(v or "—")) for k, v in rows]
        lay.addWidget(box)
        lay.addStretch(1)

        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 14px; font-size: 13px;")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def info_rows(self):
        """返回 (标签, 取值) 列表，便于自检/测试读取窗口内容。"""
        return self._rows

    def report_text(self):
        """窗口内容的纯文本形式（便于自检）。"""
        return "\n".join(f"{k}：{v}" for k, v in getattr(self, "_rows", []))


class PasswordConfirmDialog(QDialog):
    """密码输入确认窗口：空闲超时后再次操作软件时弹出，要求输入当前账号密码。

    - 输入正确：提示「密码正确」，随后窗口自动退出（accept）；
    - 输入错误：提示「当前输入密码不对，请重新输入正确的密码或关闭本页面并切换用户登录」，
      清空输入框并保持在窗口内，可继续重试或关闭（取消）。
    """

    WRONG_TEXT = "当前输入密码不对，请重新输入正确的密码或关闭本页面并切换用户登录"
    OK_TEXT = "密码正确"

    def __init__(self, parent=None, username="", name="", password="",
                 interval="3分钟", action_hint=""):
        super().__init__(parent)
        self._password = str(password or "")
        self.setWindowTitle("输入密码")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        title = QLabel("输入密码")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 16px; font-weight: bold; "
            f"background-color: transparent;")
        lay.addWidget(title)

        who = QLabel(f"当前登录：{name}（{username}）")
        who.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background-color: transparent;")
        lay.addWidget(who)

        hint = (f"已超过 {interval} 未操作软件，"
                f"请重新输入密码以继续操作{('（' + action_hint + '）') if action_hint else ''}。")
        hl = QLabel(hint)
        hl.setWordWrap(True)
        hl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; background-color: transparent;")
        lay.addWidget(hl)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("请输入密码")
        self.edit.setMinimumHeight(32)
        self.edit.setStyleSheet(
            f"QLineEdit {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px 8px; "
            f"font-size: 13px; }}")
        self.edit.returnPressed.connect(self._on_ok)
        lay.addWidget(self.edit)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet(f"color: {COLORS['accent_red']}; font-size: 12px; background-color: transparent;")
        lay.addWidget(self.msg)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 6px 16px; font-size: 13px;")
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 18px; font-size: 13px;")
        self.ok_btn.clicked.connect(self._on_ok)
        row.addWidget(cancel)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self.edit.setFocus()

    def _on_ok(self):
        """校验密码：正确则提示「密码正确」并自动退出；错误则提示并留在窗口内。"""
        if self.edit.text() == self._password:
            self.msg.setStyleSheet(
                f"color: {COLORS['accent_green']}; font-size: 12px; background-color: transparent;")
            self.msg.setText(self.OK_TEXT)
            self.ok_btn.setEnabled(False)
            # 提示「密码正确」后窗口自动退出（无需再点确定）
            QTimer.singleShot(600, self.accept)
            return
        self.msg.setStyleSheet(
            f"color: {COLORS['accent_red']}; font-size: 12px; background-color: transparent;")
        self.msg.setText(self.WRONG_TEXT)
        self.edit.clear()
        self.edit.setFocus()


class ToggleSwitch(QWidget):
    """iOS 风格开关，替代 QCheckBox；背景透明，无黑色窗体。"""
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        h = rect.height()
        r = h / 2.0

        # 轨道
        track_color = QColor(
            COLORS["accent_blue"] if self._checked else COLORS["bg_panel"])
        p.setBrush(track_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, r, r)

        # 滑钮
        knob_d = h - 4
        margin = 2
        x = rect.right() - knob_d - margin if self._checked else rect.left() + margin
        y = rect.center().y() - knob_d / 2.0
        p.setBrush(QColor(COLORS["text_primary"]))
        p.drawEllipse(int(x), int(y), knob_d, knob_d)


class AdvancedSettingsDialog(QDialog):
    """高级设置：分组（运行选项 / 系统参数 / 功能开关 / 设备）展示高级运行选项，
    改动记入运行日志。会话级开关存于主窗口；开机自启动、剔除逻辑、密码确认周期
    持久化到用户配置。内容区可滚动，便于后续扩展更多选项。"""

    # 料盒抽出超时未放回的剔除逻辑（顺序即下拉顺序，第一项为默认）
    REJECT_MODES = ["对应抽出料盒走待定", "全部料盒走待定"]

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        _dialog_base(self, "高级设置", 580, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        intro = QLabel("以下为高级运行选项，按模块分组，修改即时生效并记入运行日志：")
        intro.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        intro.setContentsMargins(16, 12, 16, 8)
        outer.addWidget(intro)

        tabs = QTabWidget()
        tabs.setStyleSheet(self._tabs_style())
        self._tabs = tabs
        outer.addWidget(tabs, 1)

        um = getattr(app, "user_manager", None)

        def _scroll_page():
            """统一每个子页面的承载方式（滚动区 + 内容容器），与各功能模块窗口保持一致。"""
            page = QWidget()
            page.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
            pl = QVBoxLayout(page)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(0)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
            content = QWidget()
            cl = QVBoxLayout(content)
            cl.setContentsMargins(16, 16, 16, 16)
            cl.setSpacing(12)
            scroll.setWidget(content)
            pl.addWidget(scroll, 1)
            return page, cl

        # —— Tab 1: 运行选项（会话开关 + 密码确认周期 + 料盒剔除逻辑）——
        page_run, rc_lay = _scroll_page()
        grp_run = QGroupBox("运行选项")
        grp_run.setStyleSheet(_group_style())
        run_lay = QVBoxLayout(grp_run)
        run_lay.setSpacing(8)

        # 会话级开关（「料盒取出计数自动清零」紧跟「设备停止统计清零」下一行，
        # 原报警设置页选项移入；持久化到报警配置 features.auto_clear）
        self._boxes = {}
        sw, _, row = self._make_switch_row(
            "设备停止统计清零",
            bool(app._adv_settings.get("stop_clear_stats", False)),
            lambda checked: self._on_toggle("stop_clear_stats", checked))
        run_lay.addLayout(row)
        self._boxes["stop_clear_stats"] = sw

        ac_sw, _, ac_row = self._make_switch_row(
            "料盒取出计数自动清零", feature_auto_clear(), self._on_auto_clear_toggle)
        run_lay.addLayout(ac_row)
        self._auto_clear_switch = ac_sw

        for key, label in [
            ("beep", "启用蜂鸣报警提示"),
            ("auto_clear_confirm", "启动时弹窗确认料盒已清空"),
            ("debug_overlay", "调试界面显示坐标叠加层"),
        ]:
            sw, _, row = self._make_switch_row(
                label,
                bool(app._adv_settings.get(key, False)),
                lambda checked, k=key: self._on_toggle(k, checked))
            run_lay.addLayout(row)
            self._boxes[key] = sw

        run_lay.addWidget(self._h_line())

        # 密码输入确认时间周期（原安全页；分组小标题已按需求删除）
        crow = QHBoxLayout()
        crow.setSpacing(8)
        clbl = self._label("密码输入确认时间周期")
        self._confirm_combo = QComboBox()
        opts = (UM_CONFIRM_OPTIONS if UM_CONFIRM_OPTIONS
                else ["1分钟", "3分钟", "5分钟", "10分钟", "20分钟", "30分钟", "45分钟",
                      "1小时", "2小时", "8小时", "24小时"])
        self._confirm_combo.addItems(opts)
        cur_c = str(getattr(um, "confirm_interval", "") or "")
        self._confirm_combo.setCurrentText(
            cur_c if cur_c in opts else "3分钟")
        self._confirm_combo.setMinimumHeight(28)
        self._confirm_combo.setStyleSheet(self._combo_style())
        self._confirm_combo.currentTextChanged.connect(self._on_confirm_interval)
        crow.addWidget(clbl)
        crow.addWidget(self._confirm_combo, 1)
        run_lay.addLayout(crow)
        cnote = QLabel("说明：超过该时长未操作软件，再次操作时需重新输入当前账号密码确认。")
        cnote.setWordWrap(True)
        cnote.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; background-color: transparent;")
        run_lay.addWidget(cnote)

        # 玻璃盘清洁提示时间周期（置于「密码输入确认时间周期」正下方）
        grow = QHBoxLayout()
        grow.setSpacing(8)
        glbl = self._label("玻璃盘清洁提示时间周期")
        self._glass_clean_combo = QComboBox()
        gopts = (UM_GLASS_CLEAN_OPTIONS if UM_GLASS_CLEAN_OPTIONS
                 else ["1天", "3天", "7天", "14天", "30天", "60天", "90天"])
        self._glass_clean_combo.addItems(gopts)
        cur_g = str(getattr(um, "glass_clean_interval", "") or "")
        self._glass_clean_combo.setCurrentText(
            cur_g if cur_g in gopts else "7天")
        self._glass_clean_combo.setMinimumHeight(28)
        self._glass_clean_combo.setStyleSheet(self._combo_style())
        self._glass_clean_combo.currentTextChanged.connect(
            self._on_glass_clean_interval)
        grow.addWidget(glbl)
        grow.addWidget(self._glass_clean_combo, 1)
        run_lay.addLayout(grow)
        gnote = QLabel("说明：超过该天数未清洁玻璃盘时，系统给出清洁提示。")
        gnote.setWordWrap(True)
        gnote.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; background-color: transparent;")
        run_lay.addWidget(gnote)

        run_lay.addWidget(self._h_line())

        # 料盒抽出超时未放回的剔除逻辑（原料盒管理页并入）
        brow = QHBoxLayout()
        brow.setSpacing(8)
        blbl = self._label("料盒抽出超时未放回的剔除逻辑")
        self._reject_combo = QComboBox()
        self._reject_combo.addItems(self.REJECT_MODES)
        cur = str(getattr(um, "bin_taken_reject_mode", "") or "")
        self._reject_combo.setCurrentText(
            cur if cur in self.REJECT_MODES else self.REJECT_MODES[0])
        self._reject_combo.setMinimumHeight(28)
        self._reject_combo.setStyleSheet(self._combo_style())
        self._reject_combo.currentTextChanged.connect(self._on_reject_mode)
        brow.addWidget(blbl)
        brow.addWidget(self._reject_combo, 1)
        run_lay.addLayout(brow)

        run_lay.addStretch(1)
        rc_lay.addWidget(grp_run)
        rc_lay.addStretch(1)
        tabs.addTab(page_run, "运行选项")

        # —— Tab 2: 系统参数 ——
        page_sys, sc_lay = _scroll_page()
        grp_sys = QGroupBox("系统参数")
        grp_sys.setStyleSheet(_group_style())
        sys_lay = QVBoxLayout(grp_sys)
        sys_lay.setSpacing(8)

        grid_sys = QGridLayout()
        grid_sys.setColumnStretch(1, 1)
        grid_sys.setHorizontalSpacing(12)
        grid_sys.setVerticalSpacing(8)
        row = 0
        self._special_com = self._make_combo(
            [f"COM{i}" for i in range(1, 33)], "COM16", "special_com")
        grid_sys.addWidget(self._label("特殊串口"), row, 0)
        grid_sys.addWidget(self._special_com, row, 1)
        row += 1
        self._algo_threads = self._make_spin(1, 16, 3, "algo_threads")
        grid_sys.addWidget(self._label("算法线程数"), row, 0)
        grid_sys.addWidget(self._algo_threads, row, 1)
        row += 1
        self._measure_decimals = self._make_spin(0, 6, 4, "measure_decimals")
        grid_sys.addWidget(self._label("尺寸测量小数点位数"), row, 0)
        grid_sys.addWidget(self._measure_decimals, row, 1)
        row += 1
        self._startup_check_algo = self._make_combo(
            ["启用", "禁用"], "禁用", "startup_check_algo")
        grid_sys.addWidget(self._label("启动时检查算法状态"), row, 0)
        grid_sys.addWidget(self._startup_check_algo, row, 1)
        row += 1
        self._startup_input_detail = self._make_combo(
            ["启用", "禁用"], "禁用", "startup_input_detail")
        grid_sys.addWidget(self._label("启动时输入产品明细"), row, 0)
        grid_sys.addWidget(self._startup_input_detail, row, 1)
        row += 1
        self._min_refresh_interval = self._make_spin(
            1, 1000, 10, "min_refresh_interval")
        grid_sys.addWidget(self._label("主界面最小刷新间隔"), row, 0)
        grid_sys.addWidget(self._min_refresh_interval, row, 1)
        row += 1
        self._main_display_mode = self._make_combo(
            ["保持比例显示", "拉伸显示", "原始尺寸"], "保持比例显示",
            "main_display_mode")
        grid_sys.addWidget(self._label("主界面显示模式"), row, 0)
        grid_sys.addWidget(self._main_display_mode, row, 1)
        sys_lay.addLayout(grid_sys)

        sys_lay.addStretch(1)
        sc_lay.addWidget(grp_sys)
        sc_lay.addStretch(1)
        tabs.addTab(page_sys, "系统参数")

        # —— Tab 3: 功能开关 ——
        page_func, fc_lay = _scroll_page()
        grp_func = QGroupBox("功能开关")
        grp_func.setStyleSheet(_group_style())
        func_lay = QVBoxLayout(grp_func)
        func_lay.setSpacing(8)

        grid_func = QGridLayout()
        grid_func.setColumnStretch(1, 1)
        grid_func.setHorizontalSpacing(12)
        grid_func.setVerticalSpacing(8)
        row = 0
        self._reject_mode_run = self._make_combo(
            ["逻辑剔除", "物理剔除"], "逻辑剔除", "reject_mode")
        grid_func.addWidget(self._label("剔除模式"), row, 0)
        grid_func.addWidget(self._reject_mode_run, row, 1)
        row += 1
        self._flash_gauge_mode = self._make_combo(
            ["启用", "禁用"], "禁用", "flash_gauge_mode")
        grid_func.addWidget(self._label("闪测仪模式"), row, 0)
        grid_func.addWidget(self._flash_gauge_mode, row, 1)
        row += 1
        self._spot_check = self._make_combo(
            ["启用", "禁用"], "禁用", "spot_check")
        grid_func.addWidget(self._label("点检功能"), row, 0)
        grid_func.addWidget(self._spot_check, row, 1)
        row += 1
        self._grr_func = self._make_combo(
            ["启用", "禁用"], "禁用", "grr_func")
        grid_func.addWidget(self._label("GRR 功能"), row, 0)
        grid_func.addWidget(self._grr_func, row, 1)
        row += 1
        self._primary_lang = self._make_combo(
            ["跟随系统", "中文", "English"], "跟随系统", "primary_lang")
        grid_func.addWidget(self._label("首选语言"), row, 0)
        grid_func.addWidget(self._primary_lang, row, 1)
        row += 1
        self._secondary_lang = self._make_combo(
            ["English", "中文"], "English", "secondary_lang")
        grid_func.addWidget(self._label("第二语言"), row, 0)
        grid_func.addWidget(self._secondary_lang, row, 1)
        row += 1
        self._pending_redirect = self._make_combo(
            ["启用", "禁用"], "禁用", "pending_redirect")
        grid_func.addWidget(self._label("待定结果重定向"), row, 0)
        grid_func.addWidget(self._pending_redirect, row, 1)
        func_lay.addLayout(grid_func)

        func_lay.addStretch(1)
        fc_lay.addWidget(grp_func)
        fc_lay.addStretch(1)
        tabs.addTab(page_func, "功能开关")

        # —— Tab 4: 设备（开机自启动 + 检测启停联动 / 启动·停止检测过程 / 算法延时）——
        page_dev, dc_lay = _scroll_page()
        grp_dev = QGroupBox("设备")
        grp_dev.setStyleSheet(_group_style())
        dev_lay = QVBoxLayout(grp_dev)
        dev_lay.setSpacing(8)

        # 设备开机自启动
        self._autostart_cb, _, row = self._make_switch_row(
            "设备开机自启动（开机后自动启动本软件）",
            bool(getattr(um, "autostart", True)),
            self._on_autostart)
        dev_lay.addLayout(row)
        dev_lay.addWidget(self._h_line())

        # 检测启停联动（含启动/停止检测的过程与算法延时）
        dev_lay.addWidget(self._section_label("检测启停联动"))
        grid_link = QGridLayout()
        grid_link.setColumnStretch(1, 1)
        grid_link.setHorizontalSpacing(12)
        grid_link.setVerticalSpacing(8)
        row = 0
        self._linkage_mode = self._make_combo(
            ["检测与设备联动模式（默认）", "仅检测", "仅设备"],
            "检测与设备联动模式（默认）", "linkage_mode")
        grid_link.addWidget(self._label("上下位机启停联动模式"), row, 0)
        grid_link.addWidget(self._linkage_mode, row, 1)
        row += 1
        grid_link.addWidget(self._section_label("启动检测的过程", small=True), row, 0, 1, 2)
        row += 1
        self._start_out_to_glass_delay = self._make_spin(
            0, 10000, 10, "start_out_to_glass_delay")
        grid_link.addWidget(self._label("出料皮带到玻璃盘的延时(ms)"), row, 0)
        grid_link.addWidget(self._start_out_to_glass_delay, row, 1)
        row += 1
        self._start_glass_to_in_delay = self._make_spin(
            0, 10000, 10, "start_glass_to_in_delay")
        grid_link.addWidget(self._label("玻璃盘到进料皮带的延时(ms)"), row, 0)
        grid_link.addWidget(self._start_glass_to_in_delay, row, 1)
        row += 1
        grid_link.addWidget(self._section_label("停止检测的过程", small=True), row, 0, 1, 2)
        row += 1
        self._stop_in_to_glass_delay = self._make_spin(
            0, 10000, 10, "stop_in_to_glass_delay")
        grid_link.addWidget(self._label("进料皮带到玻璃盘的延时(ms)"), row, 0)
        grid_link.addWidget(self._stop_in_to_glass_delay, row, 1)
        row += 1
        self._stop_glass_to_out_delay = self._make_spin(
            0, 10000, 10, "stop_glass_to_out_delay")
        grid_link.addWidget(self._label("玻璃盘到出料皮带的延时(ms)"), row, 0)
        grid_link.addWidget(self._stop_glass_to_out_delay, row, 1)
        row += 1
        self._start_algo_delay = self._make_spin(
            0, 30000, 1000, "start_algo_delay")
        grid_link.addWidget(self._label("启动检测算法延时(ms)"), row, 0)
        grid_link.addWidget(self._start_algo_delay, row, 1)
        row += 1
        self._stop_algo_delay = self._make_spin(
            0, 30000, 1000, "stop_algo_delay")
        grid_link.addWidget(self._label("停止检测算法延时(ms)"), row, 0)
        grid_link.addWidget(self._stop_algo_delay, row, 1)
        row += 1
        self._sequential_exec = self._make_combo(
            ["是", "否"], "是", "sequential_exec")
        grid_link.addWidget(self._label("顺序执行功能"), row, 0)
        grid_link.addWidget(self._sequential_exec, row, 1)
        dev_lay.addLayout(grid_link)

        dev_lay.addStretch(1)
        dc_lay.addWidget(grp_dev)
        dc_lay.addStretch(1)
        tabs.addTab(page_dev, "设备")

        # 底部操作栏
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 12, 16, 14)
        footer.addStretch(1)
        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 6px 14px; font-size: 13px;")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

    @staticmethod
    def _tabs_style():
        return (
            f"QTabWidget::pane {{ border: none; background-color: {COLORS['bg_dark']}; }}"
            f"QTabBar::tab {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_secondary']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; "
            f"padding: 7px 16px; font-size: 13px; margin-right: 4px; }}"
            f"QTabBar::tab:selected {{ background-color: {COLORS['accent_blue']}; "
            f"color: white; }}"
            f"QTabBar::tab:hover:!selected {{ color: {COLORS['text_primary']}; }}")

    @staticmethod
    def _combo_style():
        return (f"QComboBox {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 12px; }}")

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; background-color: transparent;")
        return lbl

    def _section_label(self, text, small=False):
        lbl = QLabel(text)
        size = "11px" if small else "12px"
        lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: {size}; font-weight: bold; "
            f"background-color: transparent;")
        return lbl

    def _make_switch_row(self, text, checked, toggled_handler):
        """构造「开关 + 文字标签」横向行；文字透明底，无黑色窗体。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        sw = ToggleSwitch(checked=checked)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; background-color: transparent;")
        row.addWidget(sw)
        row.addWidget(lbl, 1)
        sw.toggled.connect(toggled_handler)
        return sw, lbl, row

    def _h_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {COLORS['border']};")
        return line

    @staticmethod
    def _spin_style():
        return (f"QSpinBox {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
                f"QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; "
                f"background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; }}"
                f"QSpinBox::up-button {{ border-top-right-radius: 3px; }}"
                f"QSpinBox::down-button {{ border-bottom-right-radius: 3px; }}")

    def _make_combo(self, options, default, key):
        cb = QComboBox()
        cb.addItems(options)
        cb.setCurrentText(str(self.app._adv_settings.get(key, default)))
        cb.setMinimumHeight(28)
        cb.setStyleSheet(self._combo_style())
        cb.currentTextChanged.connect(
            lambda text, k=key: self._on_run_value_changed(k, text))
        return cb

    def _make_spin(self, min_v, max_v, default, key):
        sp = QSpinBox()
        sp.setRange(min_v, max_v)
        sp.setValue(int(self.app._adv_settings.get(key, default)))
        sp.setMinimumHeight(28)
        sp.setStyleSheet(self._spin_style())
        sp.valueChanged.connect(
            lambda v, k=key: self._on_run_value_changed(k, v))
        return sp

    def _on_run_value_changed(self, key, value):
        self.app._adv_settings[key] = value
        self.app.production.log_operation(
            self.app.current_user["name"], f"高级设置：{key} = {value}")

    def _on_toggle(self, key, checked):
        self.app._adv_settings[key] = bool(checked)
        self.app.production.log_operation(
            self.app.current_user["name"], f"高级设置：{key} = {checked}")

    def _on_auto_clear_toggle(self, checked):
        """料盒取出计数自动清零：写入报警配置 features.auto_clear 并持久化。"""
        ALARM["features"]["auto_clear"] = bool(checked)
        save_alarm_config()
        self.app.production.log_operation(
            self.app.current_user["name"],
            f"高级设置：料盒取出计数自动清零 = {bool(checked)}")

    def _on_autostart(self, checked):
        """设备开机自启动：写入用户配置并同步 Windows 开机启动项。"""
        um = getattr(self.app, "user_manager", None)
        if um is not None:
            um.set_autostart(bool(checked))
        ok = True
        setter = getattr(self.app, "apply_autostart", None)
        if callable(setter):
            ok = bool(setter(bool(checked)))
        self.app.production.log_operation(
            self.app.current_user["name"],
            f"高级设置：设备开机自启动 = {bool(checked)}（{'已生效' if ok else '写入系统项失败'}）")

    def _on_reject_mode(self, text):
        """料盒抽出超时未放回的剔除逻辑：持久化并实时生效。"""
        um = getattr(self.app, "user_manager", None)
        if um is not None:
            um.set_bin_taken_reject_mode(str(text))
        self.app.production.log_operation(
            self.app.current_user["name"], f"高级设置：料盒抽出超时剔除逻辑 = {text}")

    def _on_confirm_interval(self, text):
        """密码输入确认时间周期：持久化到用户配置并实时生效。"""
        um = getattr(self.app, "user_manager", None)
        if um is not None:
            um.set_confirm_interval(str(text))
        self.app.production.log_operation(
            self.app.current_user["name"], f"高级设置：密码输入确认时间周期 = {text}")

    def _on_glass_clean_interval(self, text):
        """玻璃盘清洁提示时间周期：持久化到用户配置并实时生效。"""
        um = getattr(self.app, "user_manager", None)
        if um is not None:
            um.set_glass_clean_interval(str(text))
        self.app.production.log_operation(
            self.app.current_user["name"], f"高级设置：玻璃盘清洁提示时间周期 = {text}")


class PlaceholderDialog(QDialog):
    """通用占位对话框（如「生产报表」功能开发中）。"""

    def __init__(self, parent, title, text):
        super().__init__(parent)
        _dialog_base(self, title, 420, 240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lab = QLabel(text)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 15px;")
        lay.addWidget(lab, 1)
        ok = QPushButton("关闭")
        ok.setFixedWidth(90)
        ok.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, alignment=Qt.AlignmentFlag.AlignCenter)
