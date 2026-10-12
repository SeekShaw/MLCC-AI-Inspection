"""报警设备阈值设置窗口。

从导航栏「🔔 报警设备」按钮打开，分区用标签页（QTabWidget）切换显示：
  1) 料盒满料停机阈值设置（件）
  2) 电磁阀使用寿命阈值设置（次动作）
  3) 速度 / 良率报警阈值设置
  4) 其他报警功能（各报警开关与阈值）
  5) 报警方案配置（状态方案数量 / 方案表格 / 导入导出）
  6) 相机参数（曝光增益 / 曝光时间 / 最小匹配 / 最大匹配）
加载示例默认值，保存后原地写入 ALARM 并持久化到 alarm_config.json。
窗口在打开时读取当前 COLORS，因此会自动跟随暗/亮主题。
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSpinBox,
    QDoubleSpinBox,
    QPushButton, QGroupBox, QFrame, QComboBox, QScrollArea, QTabWidget,
    QLineEdit, QFileDialog, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QTimer

import json

from styles import COLORS
from alarm_config import (
    ALARM, BIN_KEYS, VALVE_KEYS, SQ_KEYS, SQ_LABELS, SQ_UNITS, save_alarm_config,
    bin_full_threshold, valve_life_threshold, sq_threshold,
    alarm_duration_ms, alarm_delay_ms,
    feature_mis_wrong, mis_wrong_plan, mis_wrong_threshold,
    feature_mis_miss, mis_miss_plan, mis_miss_threshold,
    feature_door_alarm, feature_door_mode,
    feature_door_alarm_plan,
    feature_bin_taken_timeout, bin_taken_timeout_ms, bin_taken_timeout_plan, feature_bin_taken_timeout_mode,
    feature_bin_full_alarm, bin_full_plan, bin_full_pct, bin_full_stop_plan,
    feature_bin_full_stop, bin_full_stop_pct,
    feature_cont_mix, cont_mix_threshold,
    feature_cont_tilt, cont_tilt_threshold,
    feature_cont_stick, cont_stick_threshold,
    feature_cont_fly, cont_fly_threshold,
    feature_estop_alarm, estop_mode,
    feature_ion_fan_alarm, ion_fan_plan,
    feature_glass_disk_jump_alarm, glass_disk_jump_plan, feature_glass_disk_jump_count,
    cont_mix_plan, cont_tilt_plan, cont_stick_plan, cont_fly_plan,
    valve_alarm_pct, valve_alarm_plan, valve_stop_pct, valve_stop_enabled, sq_plan, item_yield_plan,
    state_plans_count, state_plans, state_plan_aliases,
)
from components import StateToggle, ToggleSwitch

_BIN_LABELS = {"OK": "OK 料盒", "NG1": "NG1 料盒", "NG2": "NG2 料盒", "RST": "RST 料盒"}
_VALVE_LABELS = {"OK": "OK 电磁阀", "NG1": "NG1 电磁阀", "NG2": "NG2 电磁阀", "RST": "RST 电磁阀"}

# 四个分区的输入框统一宽度，保证对齐美观
_LABEL_W = 110   # 标签统一宽度
_SPIN_W = 150    # 数值输入框统一宽度
_FEAT_NAME_W = 224   # 「其他报警功能」开关名称统一宽度，确保各开关与状态文字左对齐


class AlarmSettingsDialog(QDialog):
    def __init__(self, parent=None, on_clear_valve_counts=None, is_super_admin=False,
                 get_valve_counts=None):
        super().__init__(parent)
        self.setWindowTitle("报警设置")
        # 改为标签页（QTabWidget）切换显示：四块阈值设置 + 报警参数各占一个子页，
        # 每个子页内容超高时仅在本页内独立滚动，整体窗口高度受限（不再需要整窗滚动条），
        # 底部「保存 / 取消」按钮固定在标签页之外，始终可见、可点击。
        self.setMinimumWidth(760)
        self.setMaximumHeight(640)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_panel']}; }}")
        self._spins = {}  # (kind,key) -> QSpinBox
        self._valve_usage_labels = {}  # key -> 电磁阀使用次数 QLabel（实时刷新）
        self._is_super_admin = bool(is_super_admin)  # 仅超级管理员可见「清空」按钮
        self._on_clear_valve = on_clear_valve_counts  # 清空按钮回调：重置生产界面电磁阀使用次数
        self._get_valve_counts = get_valve_counts     # 读取生产界面电磁阀当前使用次数（次）
        # 定时器：每 500ms 拉取一次电磁阀使用次数并刷新显示（运行中随正常动作实时更新）
        self._usage_timer = QTimer(self)
        self._usage_timer.setInterval(500)
        self._usage_timer.timeout.connect(self._refresh_valve_usage)
        self._refresh_valve_usage()
        self._usage_timer.start()
        self.finished.connect(self._on_finished)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # 标签页：点击标签切换显示不同子页；每个子页自带滚动，互不干扰
        tabs = QTabWidget()
        tabs.setStyleSheet(self._tab_style())
        tabs.addTab(self._make_tab_page(self._build_bin_group()), "料盒满料停机")
        tabs.addTab(self._make_tab_page(self._build_valve_group()), "电磁阀寿命")
        tabs.addTab(self._make_tab_page(self._build_sq_group()), "速度 / 良率")
        tabs.addTab(self._make_tab_page(self._build_features_group()), "其他报警功能")
        tabs.addTab(self._make_tab_page(self._build_timing_group()), "报警方案配置")
        lay.addWidget(tabs, 1)

        # 自适应窗口宽度：取各子页内容所需的横向宽度（最宽一页，如料盒满料停机的
        # 4 列阈值），保证内容横向完整显示、不再被右侧裁切；同时不超过屏幕可用宽度，
        # 超宽时由子页内横向滚动条兜底。
        try:
            need_w = 0
            for i in range(tabs.count()):
                page = tabs.widget(i).widget()  # 滚动区内的内容页
                need_w = max(need_w, page.sizeHint().width())
            screen = QApplication.primaryScreen()
            screen_w = screen.availableGeometry().width() if screen else 1280
            self.setMinimumWidth(max(760, min(need_w + 48, screen_w - 40)))
        except Exception:
            pass

        # 标签页（含电磁阀使用次数列）已建好，立即填充一次初始使用次数，
        # 之后由 500ms 定时器持续刷新（运行中随正常动作实时更新）。
        self._refresh_valve_usage()

        # 操作按钮（固定在标签页之外，始终可见）：应用 / 保存 / 关闭
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        apply_btn = QPushButton("应用")
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: white; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border-radius: 4px; padding: 6px 20px; font-size: 13px;")
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 20px; font-size: 13px;")
        apply_btn.clicked.connect(self._on_apply)
        save_btn.clicked.connect(self._on_save)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _make_tab_page(self, widget):
        """把一个分区（QGroupBox）放进「带独立滚动」的标签页容器：内容超高时仅本页滚动，不影响整窗。"""
        page = QFrame()
        page.setFrameShape(QFrame.Shape.NoFrame)
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.setSpacing(0)
        page_lay.addWidget(widget)
        page_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 横向兜底：窗口再窄也能拖动横向滚动条看全（正常情况下窗口已自适应内容宽度）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_panel']}; border: none; }}")
        scroll.setWidget(page)
        return scroll

    def _tab_style(self):
        """标签页（QTabWidget）样式：选中标签用强调橙、未选中用卡片灰，契合 ubantu Yaru 浅色风。"""
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

    def _section_box(self, title_text):
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

    def _build_bin_group(self):
        """料盒满料停机页：拆成两张对齐卡片——
        ①「料盒满料停机阈值（件）」：4 行 [料盒名][阈值]，短标签统一宽度、数值框左对齐；
        ②「关联报警功能」：由原「其他报警功能」前三项并入，每个功能的参数行统一缩进到
           名称列右侧，保证阈值框 / 触发方式下拉在同一竖线上对齐。"""
        outer = QFrame()
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(12)

        # —— 卡片 1：料盒满料停机阈值（件）—— 4 列排布：第 0 行标签、第 1 行对应数值框
        bin_box, bin_inner = self._section_box("料盒满料停机阈值（件）")
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        # 4 列：OK / NG1 / NG2 / RST（标签在第 0 行、数值框在第 1 行，一一对应）
        col_of = {"OK": 0, "NG1": 1, "NG2": 2, "RST": 3}
        for key in BIN_KEYS:
            c = col_of[key]
            nm = QLabel(_BIN_LABELS[key])
            nm.setFixedWidth(_LABEL_W)
            nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            grid.addWidget(nm, 0, c, alignment=Qt.AlignmentFlag.AlignCenter)
            spin = QSpinBox()
            spin.setFixedWidth(_SPIN_W)
            spin.setRange(1, 9_999_999)
            spin.setSingleStep(100)
            spin.setValue(bin_full_threshold(key))
            spin.setSuffix(" 件")
            spin.setStyleSheet(self._spin_style())
            grid.addWidget(spin, 1, c, alignment=Qt.AlignmentFlag.AlignCenter)
            self._spins[("bin", key)] = spin
        bin_inner.addLayout(grid)
        outer_lay.addWidget(bin_box)

        # —— 卡片 2：关联报警功能（原「其他报警功能」前三项并入）——
        feat_box, feat_inner = self._section_box("关联报警功能")
        # 初始化功能开关字典（本页先于其他报警功能页构建）
        self._feat_toggles = getattr(self, "_feat_toggles", {})

        def _feat_row(toggle):
            """开关独占一行（名称列固定宽度，右侧留白），返回该行布局。"""
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addWidget(toggle)
            r.addStretch()
            return r

        def _param_row(widgets):
            """参数行：整体缩进到名称列右侧，保证所有阈值框 / 下拉在同一竖线对齐。"""
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addSpacing(_FEAT_NAME_W)
            for w in widgets:
                r.addWidget(w)
                r.addSpacing(8)
            r.addStretch()
            return r

        # ① 满料报警（默认开启）+ 报警方案 + 收料量（三者同排）
        t_full = self._make_toggle("满料报警", feature_bin_full_alarm(), _FEAT_NAME_W)
        full_plan = self._make_plan_combo(state_plan_aliases(), bin_full_plan())
        full_lbl = QLabel("报警方案")
        full_lbl.setFixedWidth(56)
        full_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        # 收料量（%）：料盒收料百分比达到该值即按所选报警方案报警
        pct_lbl = QLabel("收料量")
        pct_lbl.setFixedWidth(56)
        pct_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._bin_full_pct_spin = QSpinBox()
        self._bin_full_pct_spin.setFixedWidth(80)
        self._bin_full_pct_spin.setRange(0, 100)
        self._bin_full_pct_spin.setSuffix(" %")
        self._bin_full_pct_spin.setStyleSheet(self._spin_style())
        self._bin_full_pct_spin.setValue(bin_full_pct())
        _row_full = QHBoxLayout()
        _row_full.setSpacing(8)
        _row_full.addWidget(t_full)
        _row_full.addSpacing(12)
        _row_full.addWidget(full_lbl)
        _row_full.addWidget(full_plan)
        _row_full.addSpacing(20)
        _row_full.addWidget(pct_lbl)
        _row_full.addWidget(self._bin_full_pct_spin)
        _row_full.addStretch()
        feat_inner.addLayout(_row_full)

        def _sync_full(on):
            full_plan.setEnabled(on)
            full_plan.setStyleSheet(self._combo_style(disabled=not on))
            self._bin_full_pct_spin.setEnabled(on)
            self._bin_full_pct_spin.setStyleSheet(self._spin_style(disabled=not on))

        t_full.sw.toggled.connect(_sync_full)
        self._feat_toggles["bin_full_alarm"] = t_full
        self._bin_full_plan_combo = full_plan

        _sync_full(t_full.is_on())

        # ② 满料停机（默认开启）+ 报警方案 + 收料量（%）
        t_full_stop = self._make_toggle("满料停机", feature_bin_full_stop(), _FEAT_NAME_W)
        stop_plan_lbl = QLabel("报警方案")
        stop_plan_lbl.setFixedWidth(56)
        stop_plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        stop_plan = self._make_plan_combo(state_plan_aliases(), bin_full_stop_plan())
        stop_pct_lbl = QLabel("收料量")
        stop_pct_lbl.setFixedWidth(56)
        stop_pct_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._bin_full_stop_pct_spin = QSpinBox()
        self._bin_full_stop_pct_spin.setFixedWidth(80)
        self._bin_full_stop_pct_spin.setRange(0, 100)
        self._bin_full_stop_pct_spin.setSuffix(" %")
        self._bin_full_stop_pct_spin.setStyleSheet(self._spin_style())
        self._bin_full_stop_pct_spin.setValue(bin_full_stop_pct())
        _row_full_stop = QHBoxLayout()
        _row_full_stop.setSpacing(8)
        _row_full_stop.addWidget(t_full_stop)
        _row_full_stop.addSpacing(12)
        _row_full_stop.addWidget(stop_plan_lbl)
        _row_full_stop.addWidget(stop_plan)
        _row_full_stop.addSpacing(20)
        _row_full_stop.addWidget(stop_pct_lbl)
        _row_full_stop.addWidget(self._bin_full_stop_pct_spin)
        _row_full_stop.addStretch()
        feat_inner.addLayout(_row_full_stop)

        def _sync_full_stop(on):
            stop_plan.setEnabled(on)
            stop_plan.setStyleSheet(self._combo_style(disabled=not on))
            self._bin_full_stop_pct_spin.setEnabled(on)
            self._bin_full_stop_pct_spin.setStyleSheet(self._spin_style(disabled=not on))

        t_full_stop.sw.toggled.connect(_sync_full_stop)
        self._feat_toggles["bin_full_stop"] = t_full_stop
        self._bin_full_stop_plan_combo = stop_plan

        _sync_full_stop(t_full_stop.is_on())

        # 料盒取出未放回超时报警（默认开启）+ 报警方案 + 超时阈值(ms)
        t_bin_to = self._make_toggle("料盒取出未放回超时报警", feature_bin_taken_timeout(), _FEAT_NAME_W)
        bin_to_mode = self._make_plan_combo(state_plan_aliases(), bin_taken_timeout_plan())
        bt_lbl = QLabel("报警方案")
        bt_lbl.setFixedWidth(56)
        bt_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        # 超时阈值（ms）：料盒取出后未及时放回超过该时长即按所选报警方案报警
        to_lbl = QLabel("超时阈值")
        to_lbl.setFixedWidth(56)
        to_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        spin_bin_to = QSpinBox()
        spin_bin_to.setFixedWidth(_SPIN_W)
        spin_bin_to.setRange(0, 60000)
        spin_bin_to.setSingleStep(100)
        spin_bin_to.setValue(bin_taken_timeout_ms())
        spin_bin_to.setSuffix(" ms")
        spin_bin_to.setStyleSheet(self._spin_style())
        _row_bin_to = QHBoxLayout()
        _row_bin_to.setSpacing(8)
        _row_bin_to.addWidget(t_bin_to)
        _row_bin_to.addSpacing(12)
        _row_bin_to.addWidget(bt_lbl)
        _row_bin_to.addWidget(bin_to_mode)
        _row_bin_to.addSpacing(20)
        _row_bin_to.addWidget(to_lbl)
        _row_bin_to.addWidget(spin_bin_to)
        _row_bin_to.addStretch()
        feat_inner.addLayout(_row_bin_to)

        def _sync_bin_to(on_):
            bin_to_mode.setEnabled(on_)
            bin_to_mode.setStyleSheet(self._combo_style(disabled=not on_))
            spin_bin_to.setEnabled(on_)
            spin_bin_to.setStyleSheet(self._spin_style(disabled=not on_))

        t_bin_to.sw.toggled.connect(_sync_bin_to)
        _sync_bin_to(t_bin_to.is_on())
        self._feat_toggles["bin_taken_timeout"] = t_bin_to
        self._bin_to_spin = spin_bin_to
        self._bin_to_mode_combo = bin_to_mode
        self._bin_to_plan_lbl = bt_lbl

        # OK 良品料仓误踢监控报警（默认关闭）+ 报警方案 + 误踢阈值(Pcs/H)
        t_mis_wrong = self._make_toggle("OK 良品料仓误踢监控报警", feature_mis_wrong(), _FEAT_NAME_W)
        mis_wrong_cb = self._make_plan_combo(state_plan_aliases(), mis_wrong_plan())
        mis_wrong_plan_lbl = QLabel("报警方案")
        mis_wrong_plan_lbl.setFixedWidth(56)
        mis_wrong_plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        mis_wrong_th_lbl = QLabel("误踢阈值")
        mis_wrong_th_lbl.setFixedWidth(64)
        mis_wrong_th_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        mis_wrong_spin = QSpinBox()
        mis_wrong_spin.setFixedWidth(_SPIN_W)
        mis_wrong_spin.setRange(1, 10000)
        mis_wrong_spin.setSingleStep(1)
        mis_wrong_spin.setValue(mis_wrong_threshold())
        mis_wrong_spin.setSuffix(" Pcs/H")
        mis_wrong_spin.setStyleSheet(self._spin_style())
        _row_mis_wrong = QHBoxLayout()
        _row_mis_wrong.setSpacing(8)
        _row_mis_wrong.addWidget(t_mis_wrong)
        _row_mis_wrong.addSpacing(12)
        _row_mis_wrong.addWidget(mis_wrong_plan_lbl)
        _row_mis_wrong.addWidget(mis_wrong_cb)
        _row_mis_wrong.addSpacing(20)
        _row_mis_wrong.addWidget(mis_wrong_th_lbl)
        _row_mis_wrong.addWidget(mis_wrong_spin)
        _row_mis_wrong.addStretch()
        feat_inner.addLayout(_row_mis_wrong)

        # OK 良品料仓漏踢监控报警（默认关闭）+ 报警方案 + 漏踢阈值(Pcs/H)
        t_mis_miss = self._make_toggle("OK 良品料仓漏踢监控报警", feature_mis_miss(), _FEAT_NAME_W)
        mis_miss_cb = self._make_plan_combo(state_plan_aliases(), mis_miss_plan())
        mis_miss_plan_lbl = QLabel("报警方案")
        mis_miss_plan_lbl.setFixedWidth(56)
        mis_miss_plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        mis_miss_th_lbl = QLabel("漏踢阈值")
        mis_miss_th_lbl.setFixedWidth(64)
        mis_miss_th_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        mis_miss_spin = QSpinBox()
        mis_miss_spin.setFixedWidth(_SPIN_W)
        mis_miss_spin.setRange(1, 10000)
        mis_miss_spin.setSingleStep(1)
        mis_miss_spin.setValue(mis_miss_threshold())
        mis_miss_spin.setSuffix(" Pcs/H")
        mis_miss_spin.setStyleSheet(self._spin_style())
        _row_mis_miss = QHBoxLayout()
        _row_mis_miss.setSpacing(8)
        _row_mis_miss.addWidget(t_mis_miss)
        _row_mis_miss.addSpacing(12)
        _row_mis_miss.addWidget(mis_miss_plan_lbl)
        _row_mis_miss.addWidget(mis_miss_cb)
        _row_mis_miss.addSpacing(20)
        _row_mis_miss.addWidget(mis_miss_th_lbl)
        _row_mis_miss.addWidget(mis_miss_spin)
        _row_mis_miss.addStretch()
        feat_inner.addLayout(_row_mis_miss)

        def _sync_mis_wrong(on):
            mis_wrong_cb.setEnabled(on)
            mis_wrong_cb.setStyleSheet(self._combo_style(disabled=not on))
            mis_wrong_spin.setEnabled(on)
            mis_wrong_spin.setStyleSheet(self._spin_style(disabled=not on))

        def _sync_mis_miss(on):
            mis_miss_cb.setEnabled(on)
            mis_miss_cb.setStyleSheet(self._combo_style(disabled=not on))
            mis_miss_spin.setEnabled(on)
            mis_miss_spin.setStyleSheet(self._spin_style(disabled=not on))

        t_mis_wrong.sw.toggled.connect(_sync_mis_wrong)
        t_mis_miss.sw.toggled.connect(_sync_mis_miss)
        _sync_mis_wrong(t_mis_wrong.is_on())
        _sync_mis_miss(t_mis_miss.is_on())
        self._feat_toggles["mis_wrong"] = t_mis_wrong
        self._feat_toggles["mis_miss"] = t_mis_miss
        self._mis_wrong_spin = mis_wrong_spin
        self._mis_miss_spin = mis_miss_spin
        self._mis_wrong_plan_combo = mis_wrong_cb
        self._mis_miss_plan_combo = mis_miss_cb

        outer_lay.addWidget(feat_box)
        return outer

    def _build_valve_group(self):
        box, inner = self._section_box("电磁阀使用寿命阈值（次）")
        for key in VALVE_KEYS:
            row = QHBoxLayout()
            row.setSpacing(8)
            nm = QLabel(_VALVE_LABELS[key])
            nm.setFixedWidth(_LABEL_W)
            nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            # 寿命阈值为「次动作」，示例默认 5000000000 次，超出 QSpinBox 的 int32 上限
            # （2147483647），故此处用 QDoubleSpinBox（小数位 0）承载。
            spin = QDoubleSpinBox()
            spin.setDecimals(0)
            spin.setFixedWidth(_SPIN_W)
            spin.setRange(1, 1_000_000_000_000)
            spin.setSingleStep(1000)
            spin.setValue(float(valve_life_threshold(key)))
            spin.setSuffix(" 次")
            spin.setGroupSeparatorShown(False)
            spin.setStyleSheet(self._spin_style())
            row.addWidget(nm)
            row.addWidget(spin)
            # 电磁阀使用次数（次）：位于「寿命阈值」与「清空」之间，运行中随正常动作实时更新
            usage_lbl = QLabel("— 次")
            usage_lbl.setFixedWidth(86)
            usage_lbl.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 12px; "
                f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 3px; padding: 2px 6px;")
            row.addWidget(usage_lbl)
            self._valve_usage_labels[key] = usage_lbl
            # 「已使用次数清零」按钮：位于「已使用次数」右侧，点击后仅清零该电磁阀的
            # 已使用次数并重新开始计数，不改动寿命阈值本身。仅超级管理员可见、可用。
            if self._is_super_admin:
                clear_btn = QPushButton("已使用次数清零")
                clear_btn.setFixedWidth(110)
                clear_btn.setToolTip("把该电磁阀的已使用次数清零并重新开始计数（不影响寿命阈值）")
                clear_btn.setStyleSheet(self._clear_btn_style())
                clear_btn.clicked.connect(
                    lambda _checked=False, k=key: self._on_clear_one_valve(k))
                row.addWidget(clear_btn)
            # 行尾补 stretch：没有可伸展项时 QBoxLayout 会把剩余宽度均匀分到各间隙，
            # 导致整行内容右移、与「报警阈值 / 停机阈值」行不左对齐
            row.addStretch()
            inner.addLayout(row)
            self._spins[("valve", key)] = spin

        # —— 报警阈值设置（%）：已用动作次数达该百分比即按所选方案报警，默认 90% ——
        # 与上面 4 行电磁阀行保持相同的「标签列/数值列/第三列」对齐节奏
        a_lbl = QLabel("报警阈值")
        a_lbl.setFixedWidth(_LABEL_W)
        a_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._valve_alarm_pct_spin = QSpinBox()
        self._valve_alarm_pct_spin.setFixedWidth(_SPIN_W)
        self._valve_alarm_pct_spin.setRange(0, 100)
        self._valve_alarm_pct_spin.setSuffix(" %")
        self._valve_alarm_pct_spin.setStyleSheet(self._spin_style())
        self._valve_alarm_pct_spin.setValue(valve_alarm_pct())
        a_plan_lbl = QLabel("报警方案")
        a_plan_lbl.setFixedWidth(56)
        a_plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._valve_alarm_plan_combo = self._make_plan_combo(
            state_plan_aliases(), valve_alarm_plan())
        a_row = QHBoxLayout()
        a_row.setSpacing(8)
        a_row.addWidget(a_lbl)
        a_row.addWidget(self._valve_alarm_pct_spin)
        # 第三列与上面「使用次数」标签左对齐（从数值框右边缘起 8px）
        a_row.addWidget(a_plan_lbl)
        a_row.addSpacing(8)
        a_row.addWidget(self._valve_alarm_plan_combo)
        a_row.addStretch()
        inner.addLayout(a_row)

        # —— 停机阈值设置（%）：已用动作次数达该百分比即触发停机，默认 100% ——
        s_lbl = QLabel("停机阈值")
        s_lbl.setFixedWidth(_LABEL_W)
        s_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._valve_stop_pct_spin = QSpinBox()
        self._valve_stop_pct_spin.setFixedWidth(_SPIN_W)
        self._valve_stop_pct_spin.setRange(0, 100)
        self._valve_stop_pct_spin.setSuffix(" %")
        self._valve_stop_pct_spin.setStyleSheet(self._spin_style())
        self._valve_stop_pct_spin.setValue(valve_stop_pct())
        s_row = QHBoxLayout()
        s_row.setSpacing(8)
        s_row.addWidget(s_lbl)
        s_row.addWidget(self._valve_stop_pct_spin)
        # 与上面 4 行保持相同列数：第三列为「停机使能」开关（默认关闭不启用），
        # 开启后已用动作次数达停机阈值才执行停机
        self._valve_stop_enabled = ToggleSwitch(on=bool(valve_stop_enabled()))
        self._valve_stop_enabled.setToolTip(
            "开启后已用动作次数达停机阈值即触发停机（默认关闭不启用）")
        s_row.addWidget(self._valve_stop_enabled)
        s_row.addStretch()
        inner.addLayout(s_row)

        return box

    def _build_sq_group(self):
        box, inner = self._section_box("速度 / 良率报警阈值")
        ranges = {
            "turntable_low": (0, 99999), "turntable_high": (0, 99999),
            "detect_low": (0, 99999), "detect_high": (0, 99999),
            "good_low": (0, 100), "cam_yield_low": (0, 100), "recheck_high": (0, 100),
        }
        self._sq_plan_combos = {}
        for key in SQ_KEYS:
            row = QHBoxLayout()
            row.setSpacing(8)
            nm = QLabel(SQ_LABELS[key])
            nm.setFixedWidth(_LABEL_W)
            nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            spin = QSpinBox()
            spin.setFixedWidth(_SPIN_W)
            lo, hi = ranges[key]
            spin.setRange(lo, hi)
            spin.setSingleStep(1)
            spin.setValue(sq_threshold(key))
            spin.setSuffix(SQ_UNITS[key])
            spin.setStyleSheet(self._spin_style())
            combo = self._make_plan_combo(state_plan_aliases(), sq_plan(key))
            plan_lbl = QLabel("报警方案")
            plan_lbl.setFixedWidth(56)
            plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            row.addWidget(nm)
            row.addWidget(spin)
            row.addSpacing(12)
            row.addWidget(plan_lbl)
            row.addSpacing(8)
            row.addWidget(combo)
            row.addStretch()
            inner.addLayout(row)
            self._spins[("sq", key)] = spin
            self._sq_plan_combos[key] = combo

        # —— 检测项良率预警：无需设置阈值（阈值在调试界面「良率预警设置」列
        #    按检测项逐行设置），此处仅设置持续时长与触发预警时所按的报警方案 ——
        row = QHBoxLayout()
        row.setSpacing(8)
        nm = QLabel("检测项良率预警")
        nm.setFixedWidth(_LABEL_W)
        nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        # 阈值列占位（与其他行对齐，本行不设阈值）
        t_placeholder = QLabel("—")
        t_placeholder.setFixedWidth(_SPIN_W)
        t_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t_placeholder.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        # 检测项良率预警：无阈值，仅设报警方案
        combo = self._make_plan_combo(state_plan_aliases(), item_yield_plan())
        plan_lbl = QLabel("报警方案")
        plan_lbl.setFixedWidth(56)
        plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        row.addWidget(nm)
        row.addWidget(t_placeholder)
        row.addSpacing(12)
        row.addWidget(plan_lbl)
        row.addSpacing(8)
        row.addWidget(combo)
        row.addStretch()
        inner.addLayout(row)
        self._item_yield_plan_combo = combo
        return box

    def _build_timing_group(self):
        """报警方案配置页：状态方案数量 + 状态方案表格（别名/红绿黄灯/蜂鸣/停机/持续时长/报警延迟/停机延迟）+ 导入/导出。本页时间类数值单位均为 ms（数值框不再单独标注）。"""
        box, inner = self._section_box("报警方案配置")
        self._state_plan_rows = []

        # 状态方案数量
        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_lbl = QLabel("状态方案数量")
        count_lbl.setFixedWidth(90)
        count_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._state_plan_count_spin = QSpinBox()
        self._state_plan_count_spin.setFixedWidth(80)
        self._state_plan_count_spin.setRange(1, 20)
        self._state_plan_count_spin.setValue(state_plans_count())
        self._state_plan_count_spin.setStyleSheet(self._spin_style())
        self._state_plan_count_spin.valueChanged.connect(self._on_state_plan_count_changed)
        count_row.addWidget(count_lbl)
        count_row.addWidget(self._state_plan_count_spin)
        note_lbl = QLabel("（本页面内的时间单位均为 ms）")
        note_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        count_row.addWidget(note_lbl)
        count_row.addStretch()
        inner.addLayout(count_row)

        # 表头
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        headers = ["状态方案", "别名", "红灯", "绿灯", "黄灯", "蜂鸣", "停机", "持续时长", "报警延迟", "停机延迟"]
        # 三列时间列（持续时长/报警延迟/停机延迟）：表头与数值框统一同一宽度，
        # 宽度按最大值 600000 的文本宽度自适应计算（预留上下按钮与内边距），
        # 保证 5000 等较大数值完整显示；表头与数值框同宽后，列间隙与其它列一致（均为 8px）
        _probe_spin = QSpinBox()
        _probe_spin.setStyleSheet(self._spin_style())
        _fm = _probe_spin.fontMetrics()
        time_col_w = max(84, _fm.horizontalAdvance("600000") + 36)
        header_widths = [56, 80, 66, 66, 66, 66, 66, time_col_w, time_col_w, time_col_w]
        for c, (text, w) in enumerate(zip(headers, header_widths)):
            h = QLabel(text)
            h.setFixedWidth(w)
            h.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            grid.addWidget(h, 0, c)

        # 行数据：最多 20 个方案，按数量显示/隐藏
        plans = state_plans()
        light_states = ["闪烁", "开", "关"]
        buzzer_states = ["开", "关"]
        stop_states = ["开", "关"]
        for i in range(20):
            r = i + 1
            plan = plans[i] if i < len(plans) else {
                "alias": f"方案 {i + 1}", "red": "开", "green": "关",
                "yellow": "关", "buzzer": "关", "stop": "关",
                "duration_ms": 3000, "delay_ms": 1000, "stop_delay_ms": 5000,
            }
            idx_lbl = QLabel(f"方案 {i + 1}")
            idx_lbl.setFixedWidth(56)
            idx_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
            alias = QLineEdit(plan.get("alias", f"方案 {i + 1}"))
            alias.setFixedWidth(80)
            alias.setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 12px; "
                f"background-color: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px 6px;")
            combos = {}
            for col, (key, options) in enumerate((
                ("red", light_states), ("green", light_states),
                ("yellow", light_states), ("buzzer", buzzer_states),
                ("stop", stop_states)
            ), start=2):
                cb = QComboBox()
                cb.setFixedWidth(header_widths[col])
                cb.addItems(options)
                cb.setStyleSheet(self._combo_style())
                val = plan.get(key, "关" if key == "stop" else options[0])
                if val in options:
                    cb.setCurrentIndex(options.index(val))
                else:
                    cb.setCurrentIndex(0)
                combos[key] = cb
            # 持续时长(ms)：手动输入，示例 3000ms（单位已在本页顶部统一说明，数值框不再显示 ms）
            # 三列时间数值框（持续时长/报警延迟/停机延迟）与各自表头同宽（自适应列宽），
            # 列间隙与其它列一致（均为 8px），5000 等较大数值完整显示
            time_spin_w = header_widths[7]
            duration_spin = QSpinBox()
            duration_spin.setFixedWidth(time_spin_w)
            duration_spin.setRange(0, 600000)
            duration_spin.setSingleStep(100)
            duration_spin.setValue(int(plan.get("duration_ms", 3000)))
            duration_spin.setStyleSheet(self._spin_style())
            # 报警延迟时长(ms)：手动输入，示例 1000ms（同上，数值框不显示 ms）
            delay_spin = QSpinBox()
            delay_spin.setFixedWidth(time_spin_w)
            delay_spin.setRange(0, 600000)
            delay_spin.setSingleStep(100)
            delay_spin.setValue(int(plan.get("delay_ms", 1000)))
            delay_spin.setStyleSheet(self._spin_style())
            # 停机延迟(ms)：手动输入，示例 5000ms（同上，数值框不显示 ms）
            stop_delay_spin = QSpinBox()
            stop_delay_spin.setFixedWidth(time_spin_w)
            stop_delay_spin.setRange(0, 600000)
            stop_delay_spin.setSingleStep(100)
            stop_delay_spin.setValue(int(plan.get("stop_delay_ms", 5000)))
            stop_delay_spin.setStyleSheet(self._spin_style())
            row = {
                "index": i, "alias": alias, "combos": combos,
                "duration_spin": duration_spin, "delay_spin": delay_spin,
                "stop_delay_spin": stop_delay_spin,
                "widgets": [idx_lbl, alias, *combos.values(),
                            duration_spin, delay_spin, stop_delay_spin],
            }
            self._state_plan_rows.append(row)
            grid.addWidget(idx_lbl, r, 0)
            grid.addWidget(alias, r, 1)
            for col, cb in enumerate(combos.values(), start=2):
                grid.addWidget(cb, r, col)
            grid.addWidget(duration_spin, r, 7)
            grid.addWidget(delay_spin, r, 8)
            grid.addWidget(stop_delay_spin, r, 9)
        inner.addLayout(grid)

        # 导入 / 导出配置
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        import_btn = QPushButton("导入配置")
        import_btn.setFixedWidth(90)
        import_btn.setStyleSheet(self._action_btn_style())
        import_btn.clicked.connect(self._import_state_plans)
        export_btn = QPushButton("导出配置")
        export_btn.setFixedWidth(90)
        export_btn.setStyleSheet(self._action_btn_style())
        export_btn.clicked.connect(self._export_state_plans)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(export_btn)
        btn_row.addStretch()
        inner.addLayout(btn_row)

        self._on_state_plan_count_changed()
        return box

    def _on_state_plan_count_changed(self):
        """状态方案数量变化：显示前 N 行，隐藏其余行。"""
        count = self._state_plan_count_spin.value()
        for row in self._state_plan_rows:
            visible = row["index"] < count
            for w in row["widgets"]:
                w.setVisible(visible)

    def _action_btn_style(self):
        """导入/导出等辅助按钮样式。"""
        return (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent_orange']}; color: {COLORS['accent_orange']}; }}")

    def _state_plans_to_dict(self):
        """读取当前界面上的报警方案配置。"""
        count = self._state_plan_count_spin.value()
        plans = []
        for row in self._state_plan_rows[:count]:
            plan = {
                "alias": row["alias"].text().strip() or f"方案 {row['index'] + 1}",
                "red": row["combos"]["red"].currentText(),
                "green": row["combos"]["green"].currentText(),
                "yellow": row["combos"]["yellow"].currentText(),
                "buzzer": row["combos"]["buzzer"].currentText(),
                "stop": row["combos"]["stop"].currentText(),
                "duration_ms": row["duration_spin"].value(),
                "delay_ms": row["delay_spin"].value(),
                "stop_delay_ms": row["stop_delay_spin"].value(),
            }
            plans.append(plan)
        return {"count": count, "plans": plans}

    def _import_state_plans(self):
        """从 JSON 文件导入状态方案配置。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入状态方案配置", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "plans" not in data:
                raise ValueError("文件格式不正确")
            plans = data.get("plans", [])
            count = min(int(data.get("count", len(plans))), 20)
            self._state_plan_count_spin.setValue(count)
            light_states = ["闪烁", "开", "关"]
            buzzer_states = ["开", "关"]
            stop_states = ["开", "关"]
            for i, row in enumerate(self._state_plan_rows):
                if i < len(plans) and i < count:
                    p = plans[i]
                    row["alias"].setText(str(p.get("alias", f"方案 {i + 1}")))
                    for key, options in (("red", light_states), ("green", light_states),
                                         ("yellow", light_states), ("buzzer", buzzer_states),
                                         ("stop", stop_states)):
                        val = p.get(key, "关" if key == "stop" else options[0])
                        row["combos"][key].setCurrentIndex(
                            options.index(val) if val in options else 0)
                    row["duration_spin"].setValue(int(p.get("duration_ms", 3000)))
                    row["delay_spin"].setValue(int(p.get("delay_ms", 1000)))
                    row["stop_delay_spin"].setValue(int(p.get("stop_delay_ms", 5000)))
            self._on_state_plan_count_changed()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法导入状态方案配置：\n{e}")

    def _export_state_plans(self):
        """将当前状态方案配置导出为 JSON 文件。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出状态方案配置", "state_plans.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._state_plans_to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"无法导出状态方案配置：\n{e}")

    def _build_features_group(self):
        """其他报警功能：各报警开关（名称统一宽度、整行铺开便于对齐）+ 阈值；
        门开关 / 连续混料·歪斜·连料 / 急停 / 蜂鸣器支持「报警 / 停机」触发方式（默认报警）。
        注：料仓自动清零 / 料盒取出未放回超时 / OK 良品误漏剔除监控 已并入「料盒满料停机」页。"""
        box, inner = self._section_box("其他报警功能")
        # 注：以下三项已移至「料盒满料停机」页
        # 门打开报警（默认关闭）+ 触发方式（报警/停机）+ 报警方案（触发方式=报警 时显示）
        t_door = self._make_toggle("门打开报警", feature_door_alarm(), _FEAT_NAME_W)
        door_mode = self._make_mode_combo(feature_door_mode())
        dlbl = QLabel("触发方式")
        dlbl.setFixedWidth(56)
        dlbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        # 报警方案（报警方案）：仅当「触发方式 = 报警」时显示并可选择
        self._door_plan_lbl = QLabel("报警方案")
        self._door_plan_lbl.setFixedWidth(56)
        self._door_plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._door_alarm_plan_combo = self._make_plan_combo(
            state_plan_aliases(), feature_door_alarm_plan())
        door_row = QHBoxLayout()
        door_row.setSpacing(8)
        door_row.addWidget(t_door)
        door_row.addSpacing(8)
        door_row.addWidget(dlbl)
        door_row.addWidget(door_mode)
        door_row.addSpacing(12)
        door_row.addWidget(self._door_plan_lbl)
        door_row.addWidget(self._door_alarm_plan_combo)
        door_row.addStretch()
        inner.addLayout(door_row)

        def _sync_door(on):
            door_mode.setEnabled(on)
            door_mode.setStyleSheet(self._combo_style(disabled=not on))
            # 仅当「开启」且「触发方式 = 报警」时显示报警方案下拉
            show_plan = on and door_mode.currentIndex() == 0
            self._door_plan_lbl.setVisible(show_plan)
            self._door_alarm_plan_combo.setVisible(show_plan)
            self._door_alarm_plan_combo.setEnabled(show_plan)
            self._door_alarm_plan_combo.setStyleSheet(
                self._combo_style(disabled=not show_plan))

        t_door.sw.toggled.connect(_sync_door)
        door_mode.currentIndexChanged.connect(lambda _=0: _sync_door(t_door.is_on()))
        _sync_door(t_door.is_on())


        # 连续混料报警（默认关闭）+ 报警方案（可选）+ 阈值(Pcs)
        t_mix, spin_mix = self._make_feature_row(
            "连续混料报警", feature_cont_mix(), cont_mix_threshold(), " Pcs", 1, 9999, 1, name_w=_FEAT_NAME_W)
        self._cont_mix_plan_combo = self._make_plan_combo(
            state_plan_aliases(), cont_mix_plan())
        inner.addLayout(self._wrap_cont_row(
            t_mix, self._cont_mix_plan_combo, "连续混料个数", spin_mix))
        # 连续歪斜报警（默认关闭）+ 报警方案（可选）+ 阈值(Pcs)
        t_tilt, spin_tilt = self._make_feature_row(
            "连续歪斜报警", feature_cont_tilt(), cont_tilt_threshold(), " Pcs", 1, 9999, 1, name_w=_FEAT_NAME_W)
        self._cont_tilt_plan_combo = self._make_plan_combo(
            state_plan_aliases(), cont_tilt_plan())
        inner.addLayout(self._wrap_cont_row(
            t_tilt, self._cont_tilt_plan_combo, "连续歪斜个数", spin_tilt))
        # 连续连料报警（默认关闭）+ 报警方案（可选）+ 阈值(Pcs)
        t_stick, spin_stick = self._make_feature_row(
            "连续连料报警", feature_cont_stick(), cont_stick_threshold(), " Pcs", 1, 9999, 1, name_w=_FEAT_NAME_W)
        self._cont_stick_plan_combo = self._make_plan_combo(
            state_plan_aliases(), cont_stick_plan())
        inner.addLayout(self._wrap_cont_row(
            t_stick, self._cont_stick_plan_combo, "连续连料次数", spin_stick))
        # 连续飞料报警（默认关闭）+ 报警方案（可选）+ 阈值(Pcs)
        t_fly, spin_fly = self._make_feature_row(
            "连续飞料报警", feature_cont_fly(), cont_fly_threshold(), " Pcs", 1, 9999, 1, name_w=_FEAT_NAME_W)
        self._cont_fly_plan_combo = self._make_plan_combo(
            state_plan_aliases(), cont_fly_plan())
        inner.addLayout(self._wrap_cont_row(
            t_fly, self._cont_fly_plan_combo, "连续飞料个数", spin_fly))
        # 急停报警（默认开启）+ 报警方案（红灯闪 / 红灯闪+蜂鸣）
        t_estop, estop_lbl, combo_estop = self._make_estop_row(
            "急停报警", feature_estop_alarm(), estop_mode())
        _estop_row = QHBoxLayout()
        _estop_row.setSpacing(8)
        _estop_row.addWidget(t_estop)
        _estop_row.addSpacing(8)
        _estop_row.addWidget(estop_lbl)
        _estop_row.addWidget(combo_estop)
        _estop_row.addStretch()
        inner.addLayout(_estop_row)
        self._estop_mode_lbl = estop_lbl   # 「报警方案」标签（供自检/对齐参考）
        # 离子风扇异常报警（默认开启）+ 报警方案（报警方案下拉，与其它报警项一致）
        t_ion = self._make_toggle("离子风扇异常报警", feature_ion_fan_alarm(), _FEAT_NAME_W)
        ion_lbl = QLabel("报警方案")
        ion_lbl.setFixedWidth(56)
        ion_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._ion_fan_plan_combo = self._make_plan_combo(
            state_plan_aliases(), ion_fan_plan())
        _ion_row = QHBoxLayout()
        _ion_row.setSpacing(8)
        _ion_row.addWidget(t_ion)
        _ion_row.addSpacing(8)
        _ion_row.addWidget(ion_lbl)
        _ion_row.addWidget(self._ion_fan_plan_combo)
        _ion_row.addStretch()
        inner.addLayout(_ion_row)

        def _sync_ion(on_):
            ion_lbl.setEnabled(on_)
            self._ion_fan_plan_combo.setEnabled(on_)
            self._ion_fan_plan_combo.setStyleSheet(self._combo_style(disabled=not on_))

        t_ion.sw.toggled.connect(_sync_ion)
        _sync_ion(t_ion.is_on())

        # 玻璃盘上下跳动超限报警（默认开启）+ 报警方案（报警方案下拉，与其它报警项一致）
        t_glass = self._make_toggle("玻璃盘上下跳动超限报警", feature_glass_disk_jump_alarm(), _FEAT_NAME_W)
        glass_lbl = QLabel("报警方案")
        glass_lbl.setFixedWidth(56)
        glass_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._glass_disk_jump_plan_combo = self._make_plan_combo(
            state_plan_aliases(), glass_disk_jump_plan())
        _glass_row = QHBoxLayout()
        _glass_row.setSpacing(8)
        _glass_row.addWidget(t_glass)
        _glass_row.addSpacing(8)
        _glass_row.addWidget(glass_lbl)
        _glass_row.addWidget(self._glass_disk_jump_plan_combo)

        # 报警条件：连续超限次数（示例值 10 次，达到该次数才触发报警），与开关同一行
        glass_count_lbl = QLabel("连续超限次数")
        glass_count_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._glass_disk_jump_count_spin = QSpinBox()
        self._glass_disk_jump_count_spin.setFixedWidth(_SPIN_W)
        self._glass_disk_jump_count_spin.setRange(1, 9999)
        self._glass_disk_jump_count_spin.setSingleStep(1)
        self._glass_disk_jump_count_spin.setValue(feature_glass_disk_jump_count())
        self._glass_disk_jump_count_spin.setSuffix(" 次")
        self._glass_disk_jump_count_spin.setStyleSheet(self._spin_style())
        _glass_row.addSpacing(16)
        _glass_row.addWidget(glass_count_lbl)
        _glass_row.addWidget(self._glass_disk_jump_count_spin)
        _glass_row.addStretch()
        inner.addLayout(_glass_row)

        def _sync_glass(on_):
            glass_lbl.setEnabled(on_)
            self._glass_disk_jump_plan_combo.setEnabled(on_)
            self._glass_disk_jump_plan_combo.setStyleSheet(self._combo_style(disabled=not on_))
            glass_count_lbl.setEnabled(on_)
            self._glass_disk_jump_count_spin.setEnabled(on_)
            self._glass_disk_jump_count_spin.setStyleSheet(self._spin_style(disabled=not on_))

        t_glass.sw.toggled.connect(_sync_glass)
        _sync_glass(t_glass.is_on())

        self._feat_toggles = {**getattr(self, "_feat_toggles", {}), **{
            "door_alarm": t_door,
            "cont_mix": t_mix, "cont_tilt": t_tilt,
            "cont_stick": t_stick, "cont_fly": t_fly, "estop": t_estop,
            "ion_fan": t_ion, "glass_disk_jump": t_glass,
        }}
        # 注：mis_wrong/mis_miss/bin_to_spin/bin_to_mode_combo 已在「料盒满料停机」页赋值
        self._door_mode_combo = door_mode
        self._cont_mix_spin = spin_mix
        self._cont_tilt_spin = spin_tilt
        self._cont_stick_spin = spin_stick
        self._cont_fly_spin = spin_fly
        self._estop_mode_combo = combo_estop
        return box

    def _wrap_row(self, toggle, spin):
        """把 _make_feature_row 返回的 (开关, 阈值框) 拼成一行布局返回。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(toggle)
        row.addSpacing(8)
        row.addWidget(spin)
        row.addStretch()
        return row

    def _wrap_cont_row(self, toggle, plan_combo, count_text, spin):
        """把 (开关, 报警方案下拉, 个数标签文本, 阈值框) 拼成一行布局返回。

        行内顺序：开关 → 报警方案 + 下拉（可选）→ 个数标签 + 阈值框；
        开关关闭时「报警方案」标签与下拉一并禁用（阈值框由 _make_feature_row 自行同步）。
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(toggle)
        row.addSpacing(8)
        plan_lbl = QLabel("报警方案")
        plan_lbl.setFixedWidth(56)
        plan_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        row.addWidget(plan_lbl)
        row.addWidget(plan_combo)
        row.addSpacing(12)
        count_lbl = QLabel(count_text)
        count_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        row.addWidget(count_lbl)
        row.addWidget(spin)
        row.addStretch()

        def _sync(on_):
            plan_lbl.setEnabled(on_)
            plan_combo.setEnabled(on_)
            plan_combo.setStyleSheet(self._combo_style(disabled=not on_))

        toggle.sw.toggled.connect(_sync)
        _sync(toggle.is_on())
        return row

    def _make_feature_row(self, toggle_text, on, spin_val, suffix, lo, hi, step, name_w=None):
        """构造「开关 + 数值阈值」一组控件：开关关闭时禁用阈值输入框。

        返回 (toggle, spin)，由 _wrap_row 拼成一行布局、调用方存到 self 以便保存时读取。
        name_w 给定时开关名称固定宽度，保证多行开关对齐。
        """
        t = self._make_toggle(toggle_text, on, name_w=name_w)
        spin = QSpinBox()
        spin.setFixedWidth(_SPIN_W)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(spin_val)
        spin.setSuffix(suffix)
        spin.setStyleSheet(self._spin_style())

        def _sync(on_):
            spin.setEnabled(on_)
            spin.setStyleSheet(self._spin_style(disabled=not on_))

        t.sw.toggled.connect(_sync)
        _sync(t.is_on())
        return t, spin

    def _make_estop_row(self, toggle_text, on, mode):
        """构造「急停报警开关 + 报警方案标签 + 提示方式下拉」一组控件：开关关闭时禁用下拉。

        返回 (toggle, label, combo)，拼成一行、调用方存到 self 以便保存时读取。
        mode 取 'blink'（红灯闪）或 'blink_buzzer'（红灯闪+蜂鸣）。
        """
        t = self._make_toggle(toggle_text, on, name_w=_FEAT_NAME_W)
        lbl = QLabel("报警方案")
        lbl.setFixedWidth(56)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        combo = QComboBox()
        combo.addItems(["红灯闪", "红灯闪+蜂鸣"])
        combo.setFixedWidth(110)
        combo.setStyleSheet(self._combo_style())
        combo.setCurrentIndex(1 if mode == "blink_buzzer" else 0)

        def _sync(on_):
            lbl.setEnabled(on_)
            combo.setEnabled(on_)
            combo.setStyleSheet(self._combo_style(disabled=not on_))

        t.sw.toggled.connect(_sync)
        _sync(t.is_on())
        return t, lbl, combo

    def _make_mode_combo(self, default):
        """构造「报警 / 停机」触发方式下拉框，default 取 'alarm'（报警）或 'stop'（停机）。"""
        cb = QComboBox()
        cb.addItems(["报警", "停机"])
        cb.setFixedWidth(72)
        cb.setStyleSheet(self._combo_style())
        cb.setCurrentIndex(1 if default == "stop" else 0)
        return cb

    def _make_plan_combo(self, aliases, default):
        """构造「报警方案」下拉框：选项为报警方案配置中的「别名」，default 为当前选中别名。"""
        cb = QComboBox()
        cb.addItems(aliases)
        cb.setFixedWidth(110)
        cb.setStyleSheet(self._combo_style())
        if default in aliases:
            cb.setCurrentIndex(aliases.index(default))
        elif aliases:
            cb.setCurrentIndex(0)
        return cb

    def _combo_style(self, disabled=False):
        fg = COLORS["text_secondary"] if disabled else COLORS["text_primary"]
        bg = COLORS["bg_panel"] if disabled else COLORS["bg_card"]
        return (
            f"QComboBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 3px 6px; font-size: 12px; }}"
        )

    def _make_toggle(self, name, on, name_w=None):
        """构造带状态文字的开关；name_w 给定时名称标签固定宽度以便多行对齐；
        按 feature_*() 传入的默认值设定初始态（开启=绿/关闭=红），使对话框如实反映配置默认值。"""
        t = StateToggle(name, name_w=name_w)
        t.sw._on = bool(on)
        t._sync(bool(on))
        t.sw.update()
        return t

    def _spin_style(self, disabled=False):
        fg = COLORS["text_secondary"] if disabled else COLORS["text_primary"]
        bg = COLORS["bg_panel"] if disabled else COLORS["bg_card"]
        # 同时覆盖 QSpinBox 与 QDoubleSpinBox：电磁阀寿命阈值用 QDoubleSpinBox 承载超大数值
        # （5000000000 超出 QSpinBox 的 int32 上限），样式必须与其它数值输入框完全一致。
        return (
            f"QSpinBox, QDoubleSpinBox {{ background-color: {bg}; color: {fg}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button, "
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; }}"
        )

    def _clear_btn_style(self):
        return (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_orange']}; "
            f"border: 1px solid {COLORS['accent_orange']}; border-radius: 4px; "
            f"padding: 4px 10px; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_orange']}; color: white; }}")

    def _refresh_valve_usage(self):
        """刷新「电磁阀使用次数」列：从生产界面读取当前已用动作次数（次）。"""
        if self._get_valve_counts is None:
            return
        try:
            counts = self._get_valve_counts()
        except Exception:
            return
        for key, lbl in self._valve_usage_labels.items():
            used = counts.get(key, 0.0)
            lbl.setText(f"{used:.0f} 次")

    def _on_clear_valve_counts(self):
        """报警设置「清空」按钮：清除生产运行界面的电磁阀使用次数并重新计数（不改动寿命阈值）。"""
        if self._on_clear_valve is not None:
            self._on_clear_valve()
        self._refresh_valve_usage()  # 清空后立即同步显示

    def _on_clear_one_valve(self, key):
        """「已使用次数清零」按钮：仅把指定电磁阀的已使用次数清零并重新开始计数。"""
        if self._on_clear_valve is not None:
            try:
                self._on_clear_valve(key)
            except TypeError:
                self._on_clear_valve()  # 兼容旧的无参回调：退化为全部清空
        self._refresh_valve_usage()  # 清零后立即同步显示

    def _on_finished(self, _result):
        """对话框关闭时停止使用次数刷新定时器，避免后台泄漏。"""
        if self._usage_timer.isActive():
            self._usage_timer.stop()

    def _write_alarm(self):
        # 原地修改 ALARM 内部字典（生产界面实时读取最新值）
        for key in BIN_KEYS:
            ALARM["bin_full"][key] = self._spins[("bin", key)].value()
        for key in VALVE_KEYS:
            # QDoubleSpinBox.value() 返回 float，落盘统一转 int（寿命阈值为次动作整数）
            ALARM["valve_life"][key] = int(self._spins[("valve", key)].value())
        # 电磁阀使用寿命报警 / 停机阈值（百分比 + 报警方案）
        ALARM["features"]["valve_alarm_pct"] = self._valve_alarm_pct_spin.value()
        ALARM["features"]["valve_alarm_plan"] = self._valve_alarm_plan_combo.currentText()
        ALARM["features"]["valve_stop_pct"] = self._valve_stop_pct_spin.value()
        # 电磁阀寿命停机使能开关（默认关闭不启用）
        ALARM["features"]["valve_stop_enabled"] = self._valve_stop_enabled.is_on()
        for key in SQ_KEYS:
            ALARM["speed_quality"][key] = self._spins[("sq", key)].value()
            ALARM["sq_plan"][key] = self._sq_plan_combos[key].currentText()
        # 检测项良率预警的报警方案（阈值在调试界面按检测项逐行设置）
        ALARM["features"]["item_yield_plan"] = self._item_yield_plan_combo.currentText()
        # 状态方案
        ALARM["state_plans"] = self._state_plans_to_dict()
        # 误踢/漏踢监控（各自独立开关 / 报警方案 / 阈值；
        # 「料盒取出计数自动清零」已移至高级设置-运行选项，auto_clear 由此处之外的入口维护）
        ALARM["features"]["mis_wrong_alarm"] = self._feat_toggles["mis_wrong"].is_on()
        ALARM["features"]["mis_wrong_plan"] = self._mis_wrong_plan_combo.currentText()
        ALARM["features"]["mis_wrong_pcs"] = self._mis_wrong_spin.value()
        ALARM["features"]["mis_miss_alarm"] = self._feat_toggles["mis_miss"].is_on()
        ALARM["features"]["mis_miss_plan"] = self._mis_miss_plan_combo.currentText()
        ALARM["features"]["mis_miss_pcs"] = self._mis_miss_spin.value()
        ALARM["features"]["door_alarm"] = self._feat_toggles["door_alarm"].is_on()
        ALARM["features"]["door_mode"] = "stop" if self._door_mode_combo.currentIndex() == 1 else "alarm"
        ALARM["features"]["door_alarm_plan"] = self._door_alarm_plan_combo.currentText()
        # 料盒取出未放回超时报警 + 报警方案（已移除「处理方式」下拉，默认按所选报警方案处理）
        ALARM["features"]["bin_taken_timeout"] = self._feat_toggles["bin_taken_timeout"].is_on()
        ALARM["features"]["bin_taken_timeout_ms"] = self._bin_to_spin.value()
        ALARM["features"]["bin_taken_timeout_plan"] = self._bin_to_mode_combo.currentText()
        ALARM["features"]["bin_full_alarm"] = self._feat_toggles["bin_full_alarm"].is_on()
        ALARM["features"]["bin_full_plan"] = self._bin_full_plan_combo.currentText()
        ALARM["features"]["bin_full_pct"] = int(self._bin_full_pct_spin.value())
        ALARM["features"]["bin_full_stop"] = self._feat_toggles["bin_full_stop"].is_on()
        ALARM["features"]["bin_full_stop_plan"] = self._bin_full_stop_plan_combo.currentText()
        ALARM["features"]["bin_full_stop_pct"] = int(self._bin_full_stop_pct_spin.value())
        ALARM["features"]["cont_mix"] = self._feat_toggles["cont_mix"].is_on()
        ALARM["features"]["cont_mix_pcs"] = self._cont_mix_spin.value()
        ALARM["features"]["cont_mix_plan"] = self._cont_mix_plan_combo.currentText()
        ALARM["features"]["cont_tilt"] = self._feat_toggles["cont_tilt"].is_on()
        ALARM["features"]["cont_tilt_pcs"] = self._cont_tilt_spin.value()
        ALARM["features"]["cont_tilt_plan"] = self._cont_tilt_plan_combo.currentText()
        ALARM["features"]["cont_stick"] = self._feat_toggles["cont_stick"].is_on()
        ALARM["features"]["cont_stick_pcs"] = self._cont_stick_spin.value()
        ALARM["features"]["cont_stick_plan"] = self._cont_stick_plan_combo.currentText()
        ALARM["features"]["cont_fly"] = self._feat_toggles["cont_fly"].is_on()
        ALARM["features"]["cont_fly_pcs"] = self._cont_fly_spin.value()
        ALARM["features"]["cont_fly_plan"] = self._cont_fly_plan_combo.currentText()
        # 急停报警（开关与提示方式：红灯闪 / 红灯闪+蜂鸣）
        ALARM["features"]["estop_alarm"] = self._feat_toggles["estop"].is_on()
        ALARM["features"]["estop_mode"] = (
            "blink_buzzer" if self._estop_mode_combo.currentIndex() == 1 else "blink")
        # 离子风扇异常报警（开关与报警方案下拉）
        ALARM["features"]["ion_fan_alarm"] = self._feat_toggles["ion_fan"].is_on()
        ALARM["features"]["ion_fan_plan"] = self._ion_fan_plan_combo.currentText()
        # 玻璃盘上下跳动超限报警（开关与报警方案下拉 + 连续超限次数条件）
        ALARM["features"]["glass_disk_jump_alarm"] = self._feat_toggles["glass_disk_jump"].is_on()
        ALARM["features"]["glass_disk_jump_plan"] = self._glass_disk_jump_plan_combo.currentText()
        ALARM["features"]["glass_disk_jump_count"] = int(self._glass_disk_jump_count_spin.value())
        save_alarm_config()

    def _on_apply(self):
        """应用：把当前设置写入 ALARM（生产界面实时生效）并持久化，窗口保持打开。"""
        self._write_alarm()

    def _on_save(self):
        """保存：把当前设置写入 ALARM（生产界面实时生效）并持久化，随后关闭窗口。"""
        self._write_alarm()
        self.accept()
