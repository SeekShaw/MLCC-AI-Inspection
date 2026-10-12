"""设备设置 / 触发设定 / 剔除设定 三个非模态设置窗口。

均为非模态对话框（show 而非 exec），置顶浮于生产运行 / 调试界面之上；
控件改动实时驱动 ProductionView 的模拟数据（直接接入模拟数据）。

UI 风格与「报警设置」保持一致：橙色选中标签页、蓝色标题分区框、统一宽度的
数值输入框、底部统一风格的「关闭」按钮；运行时自动跟随暗 / 亮主题。
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QPushButton, QTabWidget,
    QGroupBox, QFrame, QGridLayout, QLineEdit, QMessageBox, QScrollArea,
    QStackedWidget,
)
from PyQt6.QtCore import Qt

from styles import COLORS
from components import ToggleSwitch


# 数值输入框统一宽度，保证对齐美观（与报警设置一致）
_SPIN_W = 150


def _tab_style():
    """标签页（QTabWidget）样式：选中标签用强调橙、未选中用卡片灰，契合整体风格。"""
    return (
        f"QTabWidget::pane {{ border: 1px solid {COLORS['border']}; "
        f"border-radius: 6px; top: -1px; background: {COLORS['bg_panel']}; }}"
        f"QTabBar::tab {{ background: {COLORS['bg_card']}; color: {COLORS['text_secondary']}; "
        f"padding: 7px 16px; font-size: 12px; "
        f"border: 1px solid {COLORS['border']}; border-bottom: none; "
        f"border-top-left-radius: 5px; border-top-right-radius: 5px; }}"
        f"QTabBar::tab:hover {{ color: {COLORS['text_primary']}; }}"
        f"QTabBar::tab:selected {{ background: {COLORS['accent_orange']}; "
        f"color: white; font-weight: bold; }}"
        f"QTabBar::tab:!selected {{ margin-top: 2px; }}"
    )


def _section_box(title_text):
    """蓝色标题分区框（与报警设置一致的 QGroupBox 样式）。"""
    box = QGroupBox(title_text)
    box.setStyleSheet(
        f"QGroupBox {{ color: {COLORS['accent_blue']}; font-size: 13px; font-weight: bold; "
        f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
        f"margin-top: 8px; padding: 6px 8px 8px 8px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}")
    inner = QVBoxLayout(box)
    inner.setContentsMargins(10, 14, 10, 10)
    inner.setSpacing(8)
    return box, inner


def _hint():
    hint = QLabel("改动即时生效，并同步到运行模拟数据。")
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    return hint


def _action_btn(text):
    """操作类按钮（运行 / 停止 / 正转 / 反转 / 启动 / 停止）统一中性样式。"""
    btn = QPushButton(text)
    btn.setMinimumHeight(30)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']}; border-radius: 4px;
            font-size: 12px; padding: 4px 14px;
        }}
        QPushButton:hover {{ border-color: {COLORS['accent_orange']}; color: {COLORS['accent_orange']}; }}
        QPushButton:disabled {{ color: {COLORS['text_secondary']}; }}
    """)
    return btn


def _active_style(btn, active):
    """高亮当前激活的操作按钮（运行 / 正转等）。"""
    if active:
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
            f"border: 1px solid {COLORS['accent_orange']}; border-radius: 4px; "
            f"font-size: 12px; padding: 4px 14px; }}")
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']}; border-radius: 4px;
                font-size: 12px; padding: 4px 14px;
            }}
            QPushButton:hover {{ border-color: {COLORS['accent_orange']}; color: {COLORS['accent_orange']}; }}
        """)


class DeviceSettingsDialog(QDialog):
    """设备设置：DD马达 / 振动盘 / 高压静电 / 负压 四类参数，各占一个标签页。"""

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.pv = mw.production
        self.setWindowTitle("设备设置")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(480, 500)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_panel']}; }}")
        self._build()
        self._load()
        self._apply_spin_style()

    # ---- 构建 ----
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        tabs = QTabWidget()
        tabs.setStyleSheet(_tab_style())
        tabs.addTab(self._tab_dd(), "DD马达")
        tabs.addTab(self._tab_vib(), "振动盘")
        tabs.addTab(self._tab_esd(), "高压静电")
        tabs.addTab(self._tab_np(), "负压")
        lay.addWidget(tabs, 1)

        lay.addWidget(_hint())

        apply_btn = QPushButton("应用")
        apply_btn.setFixedWidth(90)
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        apply_btn.clicked.connect(self._on_apply)
        save = QPushButton("保存")
        save.setFixedWidth(90)
        save.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        save.clicked.connect(self._on_save)
        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(apply_btn)
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

    # —— DD 马达 ——
    def _tab_dd(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 运行参数
        box, inner = _section_box("DD马达运行参数")

        # 运行模式：一行三按钮（生产运行 / 玻璃清洁 / 点动旋转），默认「生产运行」
        self._dd_mode = "生产运行"
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("运行模式：")
        mode_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        mode_row.addWidget(mode_lbl)
        self._mode_btns = []
        for name in ("生产运行", "玻璃清洁", "点动旋转"):
            b = _action_btn(name)
            b.clicked.connect(lambda _checked=False, n=name: self._set_dd_mode(n))
            mode_row.addWidget(b)
            self._mode_btns.append(b)
        mode_row.addStretch(1)
        inner.addLayout(mode_row)

        # 三种工作模式的参数页（堆叠），各含转速输入 + 运行/停止/正转/反转
        self._dd_run_btns = []
        self._dd_stop_btns = []
        self._dd_fwd_btns = []
        self._dd_rev_btns = []

        self.sb_prod = QDoubleSpinBox()
        self.sb_prod.setFixedWidth(_SPIN_W)
        self.sb_prod.setRange(0.0, 60.0)
        self.sb_prod.setSingleStep(0.5)
        self.sb_prod.setSuffix(" RPM")
        self.sb_prod.valueChanged.connect(self._apply)

        self.sb_clean = QDoubleSpinBox()
        self.sb_clean.setFixedWidth(_SPIN_W)
        self.sb_clean.setRange(0.0, 60.0)
        self.sb_clean.setSingleStep(0.5)
        self.sb_clean.setSuffix(" RPM")
        self.sb_clean.valueChanged.connect(self._apply)

        self.sb_jog = QDoubleSpinBox()
        self.sb_jog.setFixedWidth(_SPIN_W)
        self.sb_jog.setRange(0.0, 60.0)
        self.sb_jog.setSingleStep(0.5)
        self.sb_jog.setSuffix(" RPM")
        self.sb_jog.valueChanged.connect(self._apply)

        self.dd_stack = QStackedWidget()
        self.dd_stack.addWidget(
            self._dd_mode_page("生产运行", self.sb_prod, "目标转速"))
        self.dd_stack.addWidget(
            self._dd_mode_page("玻璃清洁", self.sb_clean, "目标转速"))
        self.dd_stack.addWidget(
            self._dd_mode_page("点动旋转", self.sb_jog, "点动转速"))
        inner.addWidget(self.dd_stack)

        outer.addWidget(box)

        # 高级参数：初始频率 / 间隔 / 累加量（需点击「保存」生效）
        adv_box, adv_inner = _section_box("高级参数")
        af = QFormLayout()
        af.setContentsMargins(0, 0, 0, 0)
        af.setSpacing(6)
        self.sb_dd_freq = QSpinBox()
        self.sb_dd_freq.setFixedWidth(180)
        self.sb_dd_freq.setRange(0, 999999)
        self.sb_dd_freq.setSuffix(" Pulse")
        af.addRow("初始频率", self.sb_dd_freq)
        self.sb_dd_interval = QSpinBox()
        self.sb_dd_interval.setFixedWidth(180)
        self.sb_dd_interval.setRange(0, 60000)
        self.sb_dd_interval.setSuffix(" ms")
        af.addRow("间隔", self.sb_dd_interval)
        self.sb_dd_accum = QSpinBox()
        self.sb_dd_accum.setFixedWidth(180)
        self.sb_dd_accum.setRange(0, 999999)
        self.sb_dd_accum.setSuffix(" Pulse")
        af.addRow("累加量", self.sb_dd_accum)
        adv_inner.addLayout(af)
        adv_note = QLabel("修改后请点击「保存」生效。")
        adv_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        adv_inner.addWidget(adv_note)
        outer.addWidget(adv_box)

        outer.addStretch(1)
        return w

    # —— 振动盘 ——
    def _tab_vib(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 供料速度（驱动每节拍产能）
        box, inner = _section_box("供料设置")
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(6)
        self.sb_vib = QSpinBox()
        self.sb_vib.setFixedWidth(_SPIN_W)
        # 供料速度：单位 Pcs/Min（示例值 12000），运行时按播放节拍折算为每节拍产品数
        self.sb_vib.setRange(1, 999999)
        self.sb_vib.setSuffix(" Pcs/Min")
        self.sb_vib.valueChanged.connect(self._apply)
        f.addRow("供料速度", self.sb_vib)
        inner.addLayout(f)
        outer.addWidget(box)

        # 圆振
        rbox, rinner = _section_box("圆振")
        rf = QFormLayout()
        rf.setContentsMargins(0, 0, 0, 0)
        rf.setSpacing(6)
        self.sb_round_v = QDoubleSpinBox()
        self.sb_round_v.setFixedWidth(_SPIN_W)
        self.sb_round_v.setRange(0.0, 220.0)
        self.sb_round_v.setSingleStep(0.5)
        self.sb_round_v.setSuffix(" V")
        self.sb_round_v.valueChanged.connect(self._apply)
        rf.addRow("电压", self.sb_round_v)
        rinner.addLayout(rf)
        self.btn_round_start = _action_btn("启动")
        self.btn_round_stop = _action_btn("停止")
        self.btn_round_start.clicked.connect(self._round_start)
        self.btn_round_stop.clicked.connect(self._round_stop)
        rrow = QHBoxLayout()
        rrow.setSpacing(8)
        rrow.addWidget(self.btn_round_start)
        rrow.addWidget(self.btn_round_stop)
        rrow.addStretch(1)
        rinner.addLayout(rrow)
        outer.addWidget(rbox)

        # 直振
        lbox, linner = _section_box("直振")
        lf = QFormLayout()
        lf.setContentsMargins(0, 0, 0, 0)
        lf.setSpacing(6)
        self.sb_line_v = QDoubleSpinBox()
        self.sb_line_v.setFixedWidth(_SPIN_W)
        self.sb_line_v.setRange(0.0, 220.0)
        self.sb_line_v.setSingleStep(0.5)
        self.sb_line_v.setSuffix(" V")
        self.sb_line_v.valueChanged.connect(self._apply)
        lf.addRow("电压", self.sb_line_v)
        linner.addLayout(lf)
        self.btn_line_start = _action_btn("启动")
        self.btn_line_stop = _action_btn("停止")
        self.btn_line_start.clicked.connect(self._line_start)
        self.btn_line_stop.clicked.connect(self._line_stop)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        lrow.addWidget(self.btn_line_start)
        lrow.addWidget(self.btn_line_stop)
        lrow.addStretch(1)
        linner.addLayout(lrow)
        outer.addWidget(lbox)

        outer.addStretch(1)
        return w

    # —— 高压静电 ——
    def _tab_esd(self):
        w = QWidget()
        box, inner = _section_box("高压静电")
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(6)
        self.sb_esd = QDoubleSpinBox()
        self.sb_esd.setFixedWidth(_SPIN_W)
        self.sb_esd.setRange(0.0, 5.0)
        self.sb_esd.setSingleStep(0.1)
        self.sb_esd.setSuffix(" KV")
        self.sb_esd.valueChanged.connect(self._apply)
        self.sb_esd_lo = QDoubleSpinBox()
        self.sb_esd_lo.setFixedWidth(_SPIN_W)
        self.sb_esd_lo.setRange(0.0, 5.0)
        self.sb_esd_lo.setSingleStep(0.1)
        self.sb_esd_lo.setSuffix(" KV")
        self.sb_esd_lo.valueChanged.connect(self._apply)
        self.sb_esd_hi = QDoubleSpinBox()
        self.sb_esd_hi.setFixedWidth(_SPIN_W)
        self.sb_esd_hi.setRange(0.0, 5.0)
        self.sb_esd_hi.setSingleStep(0.1)
        self.sb_esd_hi.setSuffix(" KV")
        self.sb_esd_hi.valueChanged.connect(self._apply)
        f.addRow("目标电压", self.sb_esd)
        f.addRow("报警下限", self.sb_esd_lo)
        f.addRow("报警上限", self.sb_esd_hi)
        inner.addLayout(f)

        # 运行控制：通电 / 断电（玻璃清洁前需先断电，由生产界面「玻璃清洁」按钮做安全判断）
        ctrl_box, ctrl_inner = _section_box("运行控制")
        self.btn_esd_on = _action_btn("通电")
        self.btn_esd_off = _action_btn("断电")
        self.btn_esd_on.clicked.connect(self._esd_on)
        self.btn_esd_off.clicked.connect(self._esd_off)
        esd_row = QHBoxLayout()
        esd_row.setSpacing(8)
        esd_row.addWidget(self.btn_esd_on)
        esd_row.addWidget(self.btn_esd_off)
        esd_row.addStretch(1)
        ctrl_inner.addLayout(esd_row)

        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        outer.addWidget(ctrl_box)
        outer.addStretch(1)
        return w

    # —— 高压静电 运行控制 ——
    def _esd_on(self):
        cfg = self.pv.dev_cfg["hv_esd"]
        cfg["powered"] = True
        self._refresh_esd_btns()
        self.pv.log_operation(getattr(self.pv, "_op_user", "操作员"), "高压静电：通电")

    def _esd_off(self):
        cfg = self.pv.dev_cfg["hv_esd"]
        cfg["powered"] = False
        self._refresh_esd_btns()
        self.pv.log_operation(getattr(self.pv, "_op_user", "操作员"), "高压静电：断电")

    def _refresh_esd_btns(self):
        cfg = self.pv.dev_cfg["hv_esd"]
        powered = bool(cfg.get("powered", True))
        _active_style(self.btn_esd_on, powered)
        _active_style(self.btn_esd_off, not powered)

    # —— 负压 ——
    def _tab_np(self):
        w = QWidget()
        box, inner = _section_box("负压")
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(6)
        self.sb_np = QDoubleSpinBox()
        self.sb_np.setFixedWidth(_SPIN_W)
        self.sb_np.setRange(0.0, 0.50)
        self.sb_np.setSingleStep(0.01)
        self.sb_np.setSuffix(" MPa")
        self.sb_np.valueChanged.connect(self._apply)
        self.sb_np_lo = QDoubleSpinBox()
        self.sb_np_lo.setFixedWidth(_SPIN_W)
        self.sb_np_lo.setRange(0.0, 0.50)
        self.sb_np_lo.setSingleStep(0.01)
        self.sb_np_lo.setSuffix(" MPa")
        self.sb_np_lo.valueChanged.connect(self._apply)
        self.sb_np_hi = QDoubleSpinBox()
        self.sb_np_hi.setFixedWidth(_SPIN_W)
        self.sb_np_hi.setRange(0.0, 0.50)
        self.sb_np_hi.setSingleStep(0.01)
        self.sb_np_hi.setSuffix(" MPa")
        self.sb_np_hi.valueChanged.connect(self._apply)
        f.addRow("目标压力", self.sb_np)
        f.addRow("报警下限", self.sb_np_lo)
        f.addRow("报警上限", self.sb_np_hi)
        inner.addLayout(f)
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        outer.addStretch(1)
        return w

    # ---- DD 马达运行模式 ----
    _DD_MODES = ("生产运行", "玻璃清洁", "点动旋转")

    def _set_dd_mode(self, name):
        """切换 DD 马达工作模式（默认「生产模式」），切到对应参数页并同步到模拟转速。"""
        if name not in self._DD_MODES:
            name = "生产运行"
        self._dd_mode = name
        self.dd_stack.setCurrentIndex(self._DD_MODES.index(name))
        self._highlight_mode_btns()
        self.pv.dev_cfg["dd_motor"]["mode"] = name
        # 把当前模式的目标转速同步到「旋转盘」模拟转速并刷新运行态显示
        self._apply()

    def _highlight_mode_btns(self):
        """高亮当前选中的运行模式按钮。"""
        for b in self._mode_btns:
            _active_style(b, b.text() == self._dd_mode)

    def _dd_mode_page(self, name, spinbox, label_text):
        """单个工作模式的参数页：转速输入（目标转速 / 点动转速）+ 运行/停止/正转/反转。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(6)
        f.addRow(label_text, spinbox)
        v.addLayout(f)

        op = QHBoxLayout()
        op.setSpacing(8)
        b_run = _action_btn("运行")
        b_stop = _action_btn("停止")
        b_fwd = _action_btn("正转")
        b_rev = _action_btn("反转")
        b_run.clicked.connect(self._dd_run)
        b_stop.clicked.connect(self._dd_stop)
        b_fwd.clicked.connect(self._dd_fwd)
        b_rev.clicked.connect(self._dd_rev)
        self._dd_run_btns.append(b_run)
        self._dd_stop_btns.append(b_stop)
        self._dd_fwd_btns.append(b_fwd)
        self._dd_rev_btns.append(b_rev)
        op.addWidget(b_run)
        op.addWidget(b_stop)
        op.addStretch(1)
        op.addWidget(b_fwd)
        op.addWidget(b_rev)
        v.addLayout(op)
        return page

    # ---- DD 马达操作 ----
    def _dd_run(self):
        self.pv.dev_cfg["dd_motor"]["running"] = True
        self._log_dd("运行")
        self._refresh_dd_btns()

    def _dd_stop(self):
        self.pv.dev_cfg["dd_motor"]["running"] = False
        self._log_dd("停止")
        self._refresh_dd_btns()

    def _dd_fwd(self):
        self.pv.dev_cfg["dd_motor"]["direction"] = 1
        self._log_dd("正转")
        self._refresh_dd_btns()

    def _dd_rev(self):
        self.pv.dev_cfg["dd_motor"]["direction"] = -1
        self._log_dd("反转")
        self._refresh_dd_btns()

    def _log_dd(self, action):
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, f"DD马达：{action}")

    def _refresh_dd_btns(self):
        cfg = self.pv.dev_cfg["dd_motor"]
        running = cfg.get("running", False)
        fwd = cfg.get("direction", 1) == 1
        for b in self._dd_run_btns:
            _active_style(b, running)
        for b in self._dd_stop_btns:
            _active_style(b, not running)
        for b in self._dd_fwd_btns:
            _active_style(b, running and fwd)
        for b in self._dd_rev_btns:
            _active_style(b, running and not fwd)
        self._highlight_mode_btns()

    # ---- 振动盘操作 ----
    def _round_start(self):
        self.pv.dev_cfg["vibrator"]["round_running"] = True
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "圆振：启动")
        self._refresh_vib_btns()

    def _round_stop(self):
        self.pv.dev_cfg["vibrator"]["round_running"] = False
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "圆振：停止")
        self._refresh_vib_btns()

    def _line_start(self):
        self.pv.dev_cfg["vibrator"]["line_running"] = True
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "直振：启动")
        self._refresh_vib_btns()

    def _line_stop(self):
        self.pv.dev_cfg["vibrator"]["line_running"] = False
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "直振：停止")
        self._refresh_vib_btns()

    def _refresh_vib_btns(self):
        cfg = self.pv.dev_cfg["vibrator"]
        _active_style(self.btn_round_start, cfg.get("round_running", False))
        _active_style(self.btn_round_stop, not cfg.get("round_running", False))
        _active_style(self.btn_line_start, cfg.get("line_running", False))
        _active_style(self.btn_line_stop, not cfg.get("line_running", False))

    def _spin_style(self, disabled=False):
        # 与「报警设置」的数值输入框样式保持一致（边框 1px、圆角 4px、内边距、字号、上下按钮宽）
        fg = COLORS["text_secondary"] if disabled else COLORS["text_primary"]
        bg = COLORS["bg_panel"] if disabled else COLORS["bg_card"]
        return (
            f"QSpinBox, QDoubleSpinBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 11px; min-height: 20px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button, "
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; }}")

    def _apply_spin_style(self):
        """把报警设置同款样式套用到本对话框所有数值输入框。"""
        for sp in self.findChildren((QSpinBox, QDoubleSpinBox)):
            sp.setStyleSheet(self._spin_style())

    # ---- 读写 ----
    def _apply(self):
        # 载入配置期间（_load 回填各数值框）不写回配置：
        # 否则尚未回填、值仍为 0/1 的输入框会把配置覆盖掉（例如打开窗口即把振动盘电压改成 0）。
        if getattr(self, "_loading", False):
            return
        # 基础参数（各模式转速 / 振动盘 / 静电 / 负压）实时生效
        cfg = self.pv.dev_cfg
        mode = getattr(self, "_dd_mode", "生产运行")
        cfg["dd_motor"]["mode"] = mode
        cfg["dd_motor"]["prod_rpm"] = self.sb_prod.value()
        cfg["dd_motor"]["clean_rpm"] = self.sb_clean.value()
        cfg["dd_motor"]["jog_rpm"] = self.sb_jog.value()
        # 当前运行模式的目标转速驱动「旋转盘」模拟转速
        if mode == "生产运行":
            cfg["dd_motor"]["speed_rpm"] = self.sb_prod.value()
        elif mode == "玻璃清洁":
            cfg["dd_motor"]["speed_rpm"] = self.sb_clean.value()
        else:  # 点动旋转
            cfg["dd_motor"]["speed_rpm"] = self.sb_jog.value()
        cfg["vibrator"]["feed_rate"] = int(self.sb_vib.value())
        cfg["vibrator"]["round_voltage"] = self.sb_round_v.value()
        cfg["vibrator"]["line_voltage"] = self.sb_line_v.value()
        cfg["hv_esd"]["voltage_kv"] = self.sb_esd.value()
        lo, hi = sorted((self.sb_esd_lo.value(), self.sb_esd_hi.value()))
        cfg["hv_esd"]["lo"], cfg["hv_esd"]["hi"] = lo, hi
        cfg["neg_press"]["pressure_mpa"] = self.sb_np.value()
        lo, hi = sorted((self.sb_np_lo.value(), self.sb_np_hi.value()))
        cfg["neg_press"]["lo"], cfg["neg_press"]["hi"] = lo, hi
        self.pv.apply_device_settings()

    def _on_save(self):
        """保存：将全部设备设置（基础参数 + DD马达高级参数）写入配置并记录日志。"""
        self._apply()  # 先把当前 UI 上的基础参数同步进 dev_cfg
        cfg = self.pv.dev_cfg["dd_motor"]
        cfg["init_freq_pulse"] = int(self.sb_dd_freq.value())
        cfg["interval_ms"] = int(self.sb_dd_interval.value())
        cfg["accum_pulse"] = int(self.sb_dd_accum.value())
        self.pv.apply_device_settings()
        self.pv.save_device_config()   # 写盘，重启后保留上次保存的全部设备设置
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "保存了设备设置（基础参数 + DD马达高级参数）")
        self.close()   # 保存即确认并退出窗口

    def _on_close(self):
        """关闭即保存：把当前全部设备设置持久化到 device_config.json 后关闭窗口。"""
        self._apply()
        self.pv.apply_device_settings()
        self.pv.save_device_config()
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "关闭设备设置并保存")
        self.close()

    def _on_apply(self):
        """应用：把当前设备设置同步进运行系统（实时生效）并持久化，窗口保持打开。"""
        self._apply()
        self.pv.apply_device_settings()
        self.pv.save_device_config()

    def _load(self):
        self._loading = True      # 回填期间禁止 _apply 写回配置（见 _apply 顶部守卫）
        cfg = self.pv.dev_cfg
        # 全部数值框「静默写入」：阻断 valueChanged→_apply 的级联覆盖
        # （否则先写入的项会被尚未回填、值为 0 的其它项通过 _apply 反向写回配置，
        #  例如打开窗口就把振动盘电压/供料速度改成 0），最后统一 _apply 一次刷新运行态显示。
        _spins = [self.sb_prod, self.sb_clean, self.sb_jog,
                  self.sb_vib, self.sb_round_v, self.sb_line_v,
                  self.sb_esd, self.sb_esd_lo, self.sb_esd_hi,
                  self.sb_np, self.sb_np_lo, self.sb_np_hi,
                  self.sb_dd_freq, self.sb_dd_interval, self.sb_dd_accum]
        for sp in _spins:
            sp.blockSignals(True)
        self.sb_prod.setValue(cfg["dd_motor"].get("prod_rpm", 21.0))
        self.sb_clean.setValue(cfg["dd_motor"].get("clean_rpm", 1.0))
        self.sb_jog.setValue(cfg["dd_motor"].get("jog_rpm", 5.0))
        # 恢复上次保存的运行模式（默认「生产运行」），并切到对应参数页
        self._set_dd_mode(cfg["dd_motor"].get("mode", "生产运行"))
        self.sb_vib.setValue(cfg["vibrator"]["feed_rate"])
        self.sb_round_v.setValue(cfg["vibrator"]["round_voltage"])
        self.sb_line_v.setValue(cfg["vibrator"]["line_voltage"])
        self.sb_esd.setValue(cfg["hv_esd"]["voltage_kv"])
        self.sb_esd_lo.setValue(cfg["hv_esd"]["lo"])
        self.sb_esd_hi.setValue(cfg["hv_esd"]["hi"])
        self.sb_np.setValue(cfg["neg_press"]["pressure_mpa"])
        self.sb_np_lo.setValue(cfg["neg_press"]["lo"])
        self.sb_np_hi.setValue(cfg["neg_press"]["hi"])
        # DD 马达高级参数（需点击「保存」才写入，故仅从配置回填显示）
        self.sb_dd_freq.setValue(cfg["dd_motor"]["init_freq_pulse"])
        self.sb_dd_interval.setValue(cfg["dd_motor"]["interval_ms"])
        self.sb_dd_accum.setValue(cfg["dd_motor"]["accum_pulse"])
        for sp in _spins:
            sp.blockSignals(False)
        self._loading = False
        # 统一落一次（各框已是配置值，等价于空操作），刷新运行态显示
        self._apply()
        # 按当前状态刷新按钮高亮
        self._refresh_dd_btns()
        self._refresh_vib_btns()
        self._refresh_esd_btns()


class TriggerSettingsDialog(QDialog):
    """触发设定：相机按钮列表 + 选中相机详情（采图使能 / 触发位置 / 触发光源 1-18）。

    每个相机为一个按钮，点击后在下方详情区勾选该相机的 18 个触发光源；
    编辑先写入工作副本，点「保存」才提交到 dev_cfg 并持久化到 device_config.json。
    """

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.pv = mw.production
        self.setWindowTitle("触发设定")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(660, 480)
        self.resize(680, 640)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_panel']}; }}")
        self._cam_names = [f"相机{i}" for i in range(1, 9)]
        # 工作副本：编辑先写入 _work，点保存才提交到 dev_cfg
        cfg = self.pv.get_trigger_config()
        self._work = {}
        for name in self._cam_names:
            cam = cfg.get(name, {"enable": True, "position": 5112, "lights": [True] * 18,
                                 "multi_enable": False, "multi_count": 2, "multi_delay": 100})
            lights = list(cam.get("lights", [True] * 18))
            while len(lights) < 18:
                lights.append(False)
            self._work[name] = {
                "enable": bool(cam.get("enable", True)),
                "position": int(cam.get("position", 5112)),
                "lights": [bool(x) for x in lights[:18]],
                "multi_enable": bool(cam.get("multi_enable", False)),
                "multi_count": int(cam.get("multi_count", 2)),
                "multi_delay": int(cam.get("multi_delay", 100)),
                # 相机参数（曝光增益 / 曝光时间 / 最小匹配 / 最大匹配），每相机独立
                "exposure_gain": int(cam.get("exposure_gain", 16)),
                "exposure_time": int(cam.get("exposure_time", 2000)),
                "min_match": int(cam.get("min_match", 50)),
                "max_match": int(cam.get("max_match", 90)),
            }
        # 光源通道名称（跨相机共享、可编辑），与 dev_cfg["trigger"]["light_names"] 同步
        names = list(cfg.get("light_names", [f"光源{i + 1}" for i in range(18)]))
        while len(names) < 18:
            names.append(f"光源{len(names) + 1}")
        self._light_names = names[:18]
        # 光源通道亮度值（跨相机共享、默认 255），与 light_names 同步
        values = list(cfg.get("light_values", [255] * 18))
        while len(values) < 18:
            values.append(255)
        self._light_values = values[:18]
        self._current = self._cam_names[0]
        self._cam_btns = {}
        self._loading = False
        self._build()
        self._select(self._current)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # 相机按钮列表：一行 8 个（每个相机一个按钮）
        cam_box = QWidget()
        cam_box.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px;")
        cam_lay = QHBoxLayout(cam_box)
        cam_lay.setContentsMargins(10, 10, 10, 10)
        cam_lay.setSpacing(6)
        for name in self._cam_names:
            btn = QPushButton(name)
            btn.setFixedSize(64, 32)
            btn.setCheckable(True)
            btn.setStyleSheet(self._cam_btn_style(False))
            btn.clicked.connect(lambda _, n=name: self._select(n))
            cam_lay.addWidget(btn)
            self._cam_btns[name] = btn
        cam_lay.addStretch()

        # 主内容区：放入可滚动容器，避免内容超出窗口被裁剪（触发光源 6 行 + 高级参数较高）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg_panel']}; }}")
        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(12)
        clay.addWidget(cam_box)

        # 选中相机的详情区
        self.detail_box, d_inner = _section_box("相机参数")
        lbl_style = f"color: {COLORS['text_primary']}; font-size: 12px;"

        # 采图使能
        en_row = QHBoxLayout()
        en_row.setSpacing(8)
        en_lbl = QLabel("采图使能")
        en_lbl.setStyleSheet(lbl_style)
        self.toggle = ToggleSwitch(on=True, on_color="#2F80ED")
        self.toggle_text = QLabel("开启")
        self.toggle_text.setStyleSheet(lbl_style)
        self.toggle.toggled.connect(self._on_enable_toggled)
        en_row.addWidget(en_lbl)
        en_row.addSpacing(8)
        en_row.addWidget(self.toggle)
        en_row.addWidget(self.toggle_text)
        en_row.addStretch()
        d_inner.addLayout(en_row)

        # 多次曝光（仅在「采图使能」开启时显示，否则整块收起隐藏）
        # 曝光次数 / 曝光延时 与「多次曝光使能」置于同一行
        self.multi_block = QWidget()
        mb_lay = QHBoxLayout(self.multi_block)
        mb_lay.setContentsMargins(0, 0, 0, 0)
        mb_lay.setSpacing(10)
        # 多次曝光使能
        me_row = QHBoxLayout()
        me_row.setSpacing(6)
        me_lbl = QLabel("多次曝光使能")
        me_lbl.setStyleSheet(lbl_style)
        self.multi_toggle = ToggleSwitch(on=False, on_color="#2F80ED")
        self.multi_toggle_text = QLabel("关闭")
        self.multi_toggle_text.setStyleSheet(lbl_style)
        self.multi_toggle.toggled.connect(self._on_multi_toggled)
        me_row.addWidget(me_lbl)
        me_row.addWidget(self.multi_toggle)
        me_row.addWidget(self.multi_toggle_text)
        mb_lay.addLayout(me_row)
        # 曝光次数
        mc = QHBoxLayout()
        mc.setSpacing(6)
        mc_lbl = QLabel("曝光次数")
        mc_lbl.setStyleSheet(lbl_style)
        self.multi_count = QSpinBox()
        self.multi_count.setFixedWidth(100)
        self.multi_count.setRange(2, 16)
        self.multi_count.setSuffix(" 次")
        self.multi_count.setStyleSheet(self._spin_style())
        self.multi_count.valueChanged.connect(self._sync_work)
        mc.addWidget(mc_lbl)
        mc.addWidget(self.multi_count)
        mb_lay.addLayout(mc)
        # 曝光延时
        md = QHBoxLayout()
        md.setSpacing(6)
        md_lbl = QLabel("曝光延时")
        md_lbl.setStyleSheet(lbl_style)
        self.multi_delay = QSpinBox()
        self.multi_delay.setFixedWidth(100)
        self.multi_delay.setRange(0, 9999)
        self.multi_delay.setSuffix(" Pulse")
        self.multi_delay.setStyleSheet(self._spin_style())
        self.multi_delay.valueChanged.connect(self._sync_work)
        md.addWidget(md_lbl)
        md.addWidget(self.multi_delay)
        mb_lay.addLayout(md)
        mb_lay.addStretch(1)
        d_inner.addWidget(self.multi_block)

        # 触发位置
        pos_row = QHBoxLayout()
        pos_row.setSpacing(8)
        pos_lbl = QLabel("触发位置")
        pos_lbl.setStyleSheet(lbl_style)
        self.pos = QSpinBox()
        self.pos.setFixedWidth(_SPIN_W)
        self.pos.setRange(0, 99999)
        self.pos.setSuffix(" Pulse")
        self.pos.setStyleSheet(self._spin_style())
        self.pos.valueChanged.connect(self._sync_work)
        pos_row.addWidget(pos_lbl)
        pos_row.addSpacing(8)
        pos_row.addWidget(self.pos)
        # 「自动获取」按钮：从运行系统自动获取当前触发位置并填入
        auto_btn = QPushButton("自动获取")
        auto_btn.setFixedWidth(88)
        auto_btn.setToolTip("从运行系统自动获取当前触发位置（Pulse）并填入")
        auto_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 0; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; }}")
        auto_btn.clicked.connect(self._on_auto_get_position)
        pos_row.addWidget(auto_btn)
        pos_row.addStretch()
        d_inner.addLayout(pos_row)

        # 相机参数（曝光增益 / 曝光时间 / 最小匹配 / 最大匹配，每相机独立）
        # 与报警设置中的原「相机参数」页一致：四项可调参数，保存在各相机自身配置中
        cam_param_box, cam_param_inner = _section_box("相机参数")
        cam_param_specs = [
            ("exposure_gain", "曝光增益", "", 0, 64, 1),
            ("exposure_time", "曝光时间", " µs", 0, 100000, 100),
            ("min_match", "最小匹配", " %", 0, 100, 1),
            ("max_match", "最大匹配", " %", 0, 100, 1),
        ]
        self.cam_param_spins = {}
        for key, label, suffix, lo, hi, step in cam_param_specs:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setStyleSheet(lbl_style)
            spin = QSpinBox()
            spin.setFixedWidth(_SPIN_W)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setStyleSheet(self._spin_style())
            spin.valueChanged.connect(self._sync_work)
            row.addWidget(lbl)
            row.addSpacing(8)
            row.addWidget(spin)
            row.addStretch()
            cam_param_inner.addLayout(row)
            self.cam_param_spins[key] = spin
        d_inner.addWidget(cam_param_box)

        # 触发光源 1-18（每行 3 个；勾选框紧跟名称，间距收紧；名称可编辑，跨相机共享）
        src_row = QHBoxLayout()
        src_lbl = QLabel("触发光源（勾选需要使用的光源，名称可双击修改）")
        src_lbl.setStyleSheet(lbl_style)
        src_row.addWidget(src_lbl)
        src_row.addStretch(1)
        self._light_filter = "all"  # 全部 / 仅已选
        self.light_filter_btn = QPushButton("显示已选")
        self.light_filter_btn.setFixedWidth(90)
        self.light_filter_btn.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 12px; font-size: 12px;")
        self.light_filter_btn.clicked.connect(self._on_light_filter_toggle)
        src_row.addWidget(self.light_filter_btn)
        d_inner.addLayout(src_row)
        self.lights = []
        self.name_edits = []
        self.light_vals = []
        self.light_cells = []
        for r in range(6):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(16)  # 每 3 组之间的间隔
            for c in range(3):
                i = r * 3 + c
                cell = QWidget()
                ch = QHBoxLayout(cell)
                ch.setContentsMargins(0, 0, 0, 0)
                ch.setSpacing(4)  # 勾选框/名称/亮度值之间的间距
                ck = QCheckBox()
                ck.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
                ck.toggled.connect(self._sync_work)
                le = QLineEdit(self._light_names[i])
                le.setFixedWidth(72)
                le.setStyleSheet(
                    f"color: {COLORS['text_primary']}; font-size: 12px; "
                    f"background-color: {COLORS['bg_card']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 3px 6px;")
                le.textChanged.connect(lambda txt, idx=i: self._on_name(idx, txt))
                # 亮度值：每个光源通道右侧一列，示例数值 255
                sp = QSpinBox()
                sp.setFixedWidth(72)
                sp.setRange(0, 255)
                sp.setStyleSheet(self._spin_style())
                sp.setValue(int(self._light_values[i]))
                ch.addWidget(ck)
                ch.addWidget(le)
                ch.addWidget(sp)
                row.addWidget(cell)
                self.lights.append(ck)
                self.name_edits.append(le)
                self.light_vals.append(sp)
                self.light_cells.append(cell)
            row.addStretch(1)
            d_inner.addLayout(row)
        clay.addWidget(self.detail_box)

        # 触发高级参数（全局，所有相机共用同一组值）
        trig = self.pv.dev_cfg["trigger"]
        adv_box, adv_inner = _section_box("触发高级参数")
        adv_lbl = QLabel("输入滤波 / 触发应答为全局参数，对全部相机生效。")
        adv_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        adv_inner.addWidget(adv_lbl)
        # 输入滤波 / 触发应答：一行两列
        af_ar_row = QHBoxLayout()
        af_ar_row.setSpacing(32)
        # 输入滤波
        af_col = QHBoxLayout()
        af_col.setSpacing(8)
        af_lbl = QLabel("输入滤波")
        af_lbl.setStyleSheet(lbl_style)
        self.adv_filter = QSpinBox()
        self.adv_filter.setFixedWidth(_SPIN_W)
        self.adv_filter.setRange(0, 999999)
        self.adv_filter.setSuffix(" μs")
        self.adv_filter.setStyleSheet(self._spin_style())
        self.adv_filter.setValue(int(trig.get("input_filter", 5000)))
        af_col.addWidget(af_lbl)
        af_col.addWidget(self.adv_filter)
        af_ar_row.addLayout(af_col)
        # 触发应答
        ar_col = QHBoxLayout()
        ar_col.setSpacing(8)
        ar_lbl = QLabel("触发应答")
        ar_lbl.setStyleSheet(lbl_style)
        self.adv_response = QSpinBox()
        self.adv_response.setFixedWidth(_SPIN_W)
        self.adv_response.setRange(0, 99999)
        self.adv_response.setSuffix(" ms")
        self.adv_response.setStyleSheet(self._spin_style())
        self.adv_response.setValue(int(trig.get("trigger_response", 5)))
        ar_col.addWidget(ar_lbl)
        ar_col.addWidget(self.adv_response)
        af_ar_row.addLayout(ar_col)
        af_ar_row.addStretch()
        adv_inner.addLayout(af_ar_row)
        clay.addWidget(adv_box)

        hint = QLabel("点击相机按钮查看并设置，编辑后点「保存」方可生效并持久化。")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        clay.addWidget(hint)
        clay.addStretch(1)
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

        # 底部：应用 / 保存 / 关闭
        apply_btn = QPushButton("应用")
        apply_btn.setFixedWidth(90)
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        apply_btn.clicked.connect(self._on_apply)
        save = QPushButton("保存")
        save.setFixedWidth(90)
        save.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; border: none; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        save.clicked.connect(self._on_save)
        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(apply_btn)
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

    def _cam_btn_style(self, selected):
        if selected:
            return (
                f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
                f"border: 1px solid {COLORS['accent_orange']}; border-radius: 4px; "
                f"font-size: 12px; font-weight: bold; }}")
        return (
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; font-size: 12px; }}"
        f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; "
        f"color: {COLORS['accent_blue']}; }}")

    def _spin_style(self, disabled=False):
        # 与「报警设置」的数值输入框样式保持一致
        fg = COLORS["text_secondary"] if disabled else COLORS["text_primary"]
        bg = COLORS["bg_panel"] if disabled else COLORS["bg_card"]
        return (
            f"QSpinBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )

    def _select(self, name):
        if name not in self._work:
            return
        self._loading = True
        self._current = name
        for n, btn in self._cam_btns.items():
            btn.setStyleSheet(self._cam_btn_style(n == name))
        cam = self._work[name]
        self.toggle.set_on(bool(cam["enable"]))
        self.toggle_text.setText("开启" if cam["enable"] else "关闭")
        self.multi_block.setVisible(bool(cam["enable"]))
        self.multi_toggle.set_on(bool(cam["multi_enable"]))
        self.multi_toggle_text.setText("开启" if cam["multi_enable"] else "关闭")
        self.multi_count.setValue(int(cam["multi_count"]))
        self.multi_delay.setValue(int(cam["multi_delay"]))
        self.pos.setValue(int(cam["position"]))
        # 相机参数（每相机独立）
        self.cam_param_spins["exposure_gain"].setValue(int(cam["exposure_gain"]))
        self.cam_param_spins["exposure_time"].setValue(int(cam["exposure_time"]))
        self.cam_param_spins["min_match"].setValue(int(cam["min_match"]))
        self.cam_param_spins["max_match"].setValue(int(cam["max_match"]))
        for ck, v in zip(self.lights, cam["lights"][:18]):
            ck.setChecked(bool(v))
        for le, nm in zip(self.name_edits, self._light_names):
            if le.text() != nm:
                le.setText(nm)
        self.detail_box.setTitle(f"相机参数 - {name}")
        self._apply_light_filter()
        self._loading = False

    def _on_enable_toggled(self, on):
        """采图使能切换：更新文字、收起/展开多次曝光整块，并同步工作副本。"""
        self.toggle_text.setText("开启" if on else "关闭")
        self.multi_block.setVisible(on)
        self._sync_work()

    def _on_multi_toggled(self, on):
        self.multi_toggle_text.setText("开启" if on else "关闭")
        self._sync_work()

    def _sync_work(self):
        if self._loading:
            return
        cam = self._work[self._current]
        cam["enable"] = bool(self.toggle._on)
        cam["position"] = int(self.pos.value())
        cam["lights"] = [ck.isChecked() for ck in self.lights]
        cam["multi_enable"] = bool(self.multi_toggle._on)
        cam["multi_count"] = int(self.multi_count.value())
        cam["multi_delay"] = int(self.multi_delay.value())
        # 相机参数（每相机独立）
        cam["exposure_gain"] = int(self.cam_param_spins["exposure_gain"].value())
        cam["exposure_time"] = int(self.cam_param_spins["exposure_time"].value())
        cam["min_match"] = int(self.cam_param_spins["min_match"].value())
        cam["max_match"] = int(self.cam_param_spins["max_match"].value())
        self._apply_light_filter()

    def _on_name(self, idx, txt):
        # 光源名称跨相机共享、可编辑，存入工作副本（保存时一并落盘）
        self._light_names[idx] = (txt or f"光源{idx + 1}").strip()

    def _on_auto_get_position(self):
        """「自动获取」：从运行系统读取当前脉冲位置并填入触发位置（随 _sync_work 写入工作副本）。"""
        try:
            pos = int(self.pv.get_current_pulse_position())
        except Exception:
            return
        self.pos.setValue(max(self.pos.minimum(), min(self.pos.maximum(), pos)))

    def _on_light_filter_toggle(self):
        """切换「显示所有 / 显示已选」：按钮文字随当前模式变化，并即时刷新可见性。"""
        if self._light_filter == "all":
            self._light_filter = "selected"
            self.light_filter_btn.setText("显示所有")
        else:
            self._light_filter = "all"
            self.light_filter_btn.setText("显示已选")
        self._apply_light_filter()

    def _apply_light_filter(self):
        """根据当前筛选模式，控制 18 个光源单元的可见性。"""
        show_all = (self._light_filter == "all")
        for cell, ck in zip(self.light_cells, self.lights):
            cell.setVisible(show_all or ck.isChecked())

    def _on_save(self):
        for name, cam in self._work.items():
            self.pv.set_trigger_config(
                name, enable=cam["enable"], position=cam["position"], lights=cam["lights"],
                multi_enable=cam["multi_enable"], multi_count=cam["multi_count"],
                multi_delay=cam["multi_delay"],
                exposure_gain=cam["exposure_gain"], exposure_time=cam["exposure_time"],
                min_match=cam["min_match"], max_match=cam["max_match"])
        # 光源通道名称一并保存到 dev_cfg，重启后保留
        self.pv.dev_cfg["trigger"]["light_names"] = list(self._light_names)
        # 光源通道亮度值一并保存
        self.pv.dev_cfg["trigger"]["light_values"] = [int(x.value()) for x in self.light_vals]
        # 触发高级参数（全局）一并保存
        self.pv.dev_cfg["trigger"]["input_filter"] = int(self.adv_filter.value())
        self.pv.dev_cfg["trigger"]["trigger_response"] = int(self.adv_response.value())
        self.pv.save_device_config()
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "保存了触发设定")
        self.close()   # 保存即确认并退出窗口

    def _on_apply(self):
        """应用：把当前触发设定提交到运行系统（实时生效）并持久化，窗口保持打开。"""
        for name, cam in self._work.items():
            self.pv.set_trigger_config(
                name, enable=cam["enable"], position=cam["position"], lights=cam["lights"],
                multi_enable=cam["multi_enable"], multi_count=cam["multi_count"],
                multi_delay=cam["multi_delay"],
                exposure_gain=cam["exposure_gain"], exposure_time=cam["exposure_time"],
                min_match=cam["min_match"], max_match=cam["max_match"])
        self.pv.dev_cfg["trigger"]["light_names"] = list(self._light_names)
        self.pv.dev_cfg["trigger"]["light_values"] = [int(x.value()) for x in self.light_vals]
        self.pv.dev_cfg["trigger"]["input_filter"] = int(self.adv_filter.value())
        self.pv.dev_cfg["trigger"]["trigger_response"] = int(self.adv_response.value())
        self.pv.save_device_config()


class RejectSettingsDialog(QDialog):
    """剔除设定：各剔除口（顺序/名称/启用/位置/吹气保持/优先级/测试）+ 默认剔除口设置。"""

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.pv = mw.production
        self.setWindowTitle("剔除设定")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(760, 480)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_panel']}; }}")
        self._build()
        self._load()

    def _build(self):
        self._loading = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lbl_style = f"color: {COLORS['text_primary']}; font-size: 12px;"

        # 各剔除口：顺序 / 名称 / 启用 / 剔除位置 / 吹气保持时间 / 剔除优先级 / 剔除测试
        box, inner = _section_box("剔除口设置")
        grid = QGridLayout()
        self.grid = grid
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        headers = ["剔除口顺序", "剔除口名称", "启用", "剔除位置 (Pulse)",
                   "吹气保持时间 (ms)", "剔除优先级", "剔除测试"]
        for c, t in enumerate(headers):
            h = QLabel(t)
            h.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            grid.addWidget(h, 0, c)
        self._port_rows = {}
        self._offline_ports = [("ok", "OK"), ("ng1", "NG1"), ("ng2", "NG2"), ("rst", "RST")]
        for r, (key, label) in enumerate(self._offline_ports, start=1):
            seq = QLabel(str(r))
            seq.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            name = QLabel(label)
            name.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            ck = QCheckBox("启用")
            ck.toggled.connect(self._apply)
            pos = QSpinBox()
            pos.setFixedWidth(120)
            pos.setRange(0, 99999)
            pos.setSuffix(" Pulse")
            pos.setStyleSheet(self._spin_style())
            pos.valueChanged.connect(self._apply)
            # 「自动获取」按钮：位于「剔除位置」右侧，从运行系统自动获取该口当前位置并填入
            auto_btn = QPushButton("自动获取")
            auto_btn.setFixedWidth(88)
            auto_btn.setToolTip("从运行系统自动获取该剔除口当前剔除位置（Pulse）并填入")
            auto_btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"padding: 4px 0; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; }}")
            auto_btn.clicked.connect(
                lambda _checked=False, sp=pos, idx=r - 1: self._on_auto_get_port(sp, idx))
            pos_cell = QWidget()
            pos_lay = QHBoxLayout(pos_cell)
            pos_lay.setContentsMargins(0, 0, 0, 0)
            pos_lay.setSpacing(6)
            pos_lay.addWidget(pos)
            pos_lay.addWidget(auto_btn)
            blow = QSpinBox()
            blow.setFixedWidth(110)
            blow.setRange(0, 9999)
            blow.setSuffix(" ms")
            blow.setStyleSheet(self._spin_style())
            blow.valueChanged.connect(self._apply)
            pri = QSpinBox()
            pri.setFixedWidth(80)
            pri.setRange(1, 4)
            pri.setStyleSheet(self._spin_style())
            pri.valueChanged.connect(self._apply)
            test_btn = QPushButton("测试")
            test_btn.setFixedWidth(64)
            test_btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"padding: 4px 0; font-size: 12px; }}"
                f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; }}")
            test_btn.clicked.connect(
                lambda _checked=False, k=key, lb=label: self._on_test(k, lb))
            grid.addWidget(seq, r, 0)
            grid.addWidget(name, r, 1)
            grid.addWidget(ck, r, 2)
            grid.addWidget(pos_cell, r, 3)
            grid.addWidget(blow, r, 4)
            grid.addWidget(pri, r, 5)
            grid.addWidget(test_btn, r, 6)
            self._port_rows[key] = (ck, pos, blow, pri, test_btn)
        inner.addLayout(grid)
        lay.addWidget(box)

        # 默认剔除口设置（含合并进来的「软件脱机/超时剔除口」）
        box4, inner4 = _section_box("默认剔除口设置")
        # 软件脱机/超时剔除口（默认 RST）—— 由独立区块合并而来
        off_row = QHBoxLayout()
        off_row.setSpacing(8)
        off_lbl = QLabel("软件脱机/超时剔除口")
        off_lbl.setStyleSheet(lbl_style)
        self.offline_combo = QComboBox()
        self.offline_combo.setFixedWidth(140)
        self.offline_combo.setStyleSheet(self._combo_style())
        for key, label in self._offline_ports:
            self.offline_combo.addItem(label, key)
        self.offline_combo.currentIndexChanged.connect(self._apply)
        off_row.addWidget(off_lbl)
        off_row.addSpacing(8)
        off_row.addWidget(self.offline_combo)
        off_row.addStretch()
        inner4.addLayout(off_row)
        # 默认未检状态剔除口（可选 OK/NG1/NG2/RST，默认 RST）
        uc_row = QHBoxLayout()
        uc_row.setSpacing(8)
        uc_lbl = QLabel("默认未检状态剔除口")
        uc_lbl.setStyleSheet(lbl_style)
        self.uc_combo = QComboBox()
        self.uc_combo.setFixedWidth(140)
        self.uc_combo.setStyleSheet(self._combo_style())
        for key, label in self._offline_ports:
            self.uc_combo.addItem(label, key)
        self.uc_combo.currentIndexChanged.connect(self._apply)
        uc_row.addWidget(uc_lbl)
        uc_row.addSpacing(8)
        uc_row.addWidget(self.uc_combo)
        uc_row.addStretch()
        inner4.addLayout(uc_row)
        # 默认 OK / 待定 / NG 剔除口编号（1-4）
        self._def_port_spins = {}
        for key, label, default in (
            ("default_ok_port", "默认 OK 剔除口", 1),
            ("default_pending_port", "默认待定剔除口", 4),
            ("default_ng_port", "默认 NG 剔除口", 2),
        ):
            d_row = QHBoxLayout()
            d_row.setSpacing(8)
            d_lbl = QLabel(label)
            d_lbl.setStyleSheet(lbl_style)
            sp = QSpinBox()
            sp.setFixedWidth(_SPIN_W)
            sp.setRange(1, 4)
            sp.setStyleSheet(self._spin_style())
            sp.setValue(default)
            sp.valueChanged.connect(self._apply)
            d_row.addWidget(d_lbl)
            d_row.addSpacing(8)
            d_row.addWidget(sp)
            d_row.addStretch()
            inner4.addLayout(d_row)
            self._def_port_spins[key] = sp
        lay.addWidget(box4)

        lay.addWidget(_hint())
        lay.addStretch(1)

        apply_btn = QPushButton("应用")
        apply_btn.setFixedWidth(90)
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        apply_btn.clicked.connect(self._on_apply)
        save = QPushButton("保存")
        save.setFixedWidth(90)
        save.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        save.clicked.connect(self._on_save)
        close = QPushButton("关闭")
        close.setFixedWidth(90)
        close.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(apply_btn)
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

    def _spin_style(self, disabled=False):
        # 与「报警设置」的数值输入框样式保持一致
        fg = COLORS["text_secondary"] if disabled else COLORS["text_primary"]
        bg = COLORS["bg_panel"] if disabled else COLORS["bg_card"]
        return (
            f"QSpinBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )

    def _on_save(self):
        """保存：立即保存当前剔除设定并关闭窗口。"""
        self._apply()
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, "保存了剔除设定")
        self.close()

    def _on_apply(self):
        """应用：把当前剔除设定提交到运行系统（实时生效）并持久化，窗口保持打开。"""
        self._apply()

    def _combo_style(self):
        return (
            f"QComboBox {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
            f"QComboBox::drop-down {{ width: 16px; border: none; }}")

    def _on_test(self, key, label):
        """剔除测试：向指定剔除口发送测试信号（演示用，记录操作日志并提示）。"""
        actor = getattr(self.pv, "_op_user", "操作员")
        self.pv.log_operation(actor, f"测试剔除口 {label}")
        QMessageBox.information(self, "剔除测试", f"已向 {label} 剔除口发送测试信号。")

    def _on_auto_get_port(self, spin, idx):
        """「自动获取」：从运行系统读取该剔除口当前位置（Pulse）并填入（随 _apply 实时生效）。"""
        try:
            pos = int(self.pv.get_current_pulse_position(offset=idx))
        except Exception:
            return
        spin.setValue(max(spin.minimum(), min(spin.maximum(), pos)))

    def _apply(self):
        if getattr(self, "_loading", False):
            return
        p = self.pv.dev_cfg["reject"]["ports"]
        for key, (ck, pos, blow, pri, test_btn) in self._port_rows.items():
            p[key]["enable"] = bool(ck.isChecked())
            p[key]["position"] = int(pos.value())
            p[key]["blow_time"] = int(blow.value())
            p[key]["priority"] = int(pri.value())
        off_key = self.offline_combo.currentData()
        self.pv.dev_cfg["reject"]["offline_port"] = off_key if off_key else "rst"
        uc_key = self.uc_combo.currentData()
        self.pv.dev_cfg["reject"]["default_unchecked_port"] = uc_key if uc_key else "rst"
        for key, sp in self._def_port_spins.items():
            self.pv.dev_cfg["reject"][key] = int(sp.value())
        self.pv.save_device_config()

    def _load(self):
        r = self.pv.dev_cfg["reject"]
        p = r["ports"]
        for key, (ck, pos, blow, pri, test_btn) in self._port_rows.items():
            cfg = p.get(key, {"enable": True, "position": 0, "priority": 1, "blow_time": 200})
            ck.setChecked(bool(cfg["enable"]))
            pos.setValue(int(cfg["position"]))
            blow.setValue(int(cfg.get("blow_time", 200)))
            pri.setValue(int(cfg["priority"]))
        off_key = r.get("offline_port", "rst")
        idx = next((i for i, (k, _) in enumerate(self._offline_ports) if k == off_key), 3)
        self.offline_combo.setCurrentIndex(idx)
        uc_key = r.get("default_unchecked_port", "rst")
        uc_idx = next((i for i, (k, _) in enumerate(self._offline_ports) if k == uc_key), 3)
        self.uc_combo.setCurrentIndex(uc_idx)
        for key, sp in self._def_port_spins.items():
            sp.setValue(int(r.get(key, sp.value())))
        self._loading = False
