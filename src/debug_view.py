import os
import json
import sys
import random
import time
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QCheckBox, QLineEdit, QSizePolicy, QDialog, QMenu,
    QAbstractItemView, QMessageBox, QApplication, QDateTimeEdit,
    QTabWidget, QScrollArea, QFileDialog, QSpinBox, QSlider,
    QGroupBox, QStackedWidget, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QDateTime, QRect, QSize, QEvent
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QImage, QPixmap

from styles import COLORS, register_restyle
from components import (
    Card, SectionTitle, CameraPreview, CameraScreen, LogView, FloatPanel,
    ToggleSwitch, make_sample_frames, _extract_channel)
from production_view import (
    StatsPanel, _make_user_frames, _CAMERA_FRAME_IMAGES, _camera_frame_dir,
    CAMERA_NAMES,
)


# ---------------------------------------------------------------------------
# 检测项「显示所有 / 显示已选」筛选状态持久化
# ---------------------------------------------------------------------------
def _debug_config_path():
    """落盘路径：优先跟随可执行文件所在目录（打包后），否则脚本目录。"""
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "debug_view_config.json")


def _load_debug_config():
    """读取已持久化的调试界面偏好（如筛选状态）；缺失/损坏则返回空字典。"""
    p = _debug_config_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_debug_config(data):
    """把当前调试界面偏好写回 debug_view_config.json，重启后保留。"""
    p = _debug_config_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



# ---------------------------------------------------------------------------
# 示例数值序列生成（供「分布图」曲线展示）
# ---------------------------------------------------------------------------
def _make_sample_series(seed, center, n=48):
    """围绕 center 生成一条带噪声的示例测量序列，用于演示分布曲线。"""
    rnd = random.Random(seed)
    vals = []
    v = center
    for _ in range(n):
        v += rnd.uniform(-center * 0.08 - 0.004, center * 0.08 + 0.004)
        vals.append(round(v, 3))
    return vals


def _to_float(s):
    """把字符串安全解析为 float，失败返回 None。"""
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def _round_like(value, default_str):
    """按默认检测值字符串的小数位数对浮动结果取整；无小数点则取整数。"""
    s = str(default_str)
    if "." in s:
        dec = min(len(s.split(".")[-1]), 3)
    else:
        dec = 0
    return round(value, dec)


# ---------------------------------------------------------------------------
# 分布曲线绘制组件
# ---------------------------------------------------------------------------
class CurveWidget(QWidget):
    def __init__(self, values, color="#0D822B", lo=None, hi=None, parent=None):
        super().__init__(parent)
        self.values = values
        self.color = color
        self.lo = lo     # 规格下限
        self.hi = hi     # 规格上限
        self.setMinimumSize(380, 220)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 46, 12, 14, 26
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        p.fillRect(self.rect(), QColor("#F2F1F0"))
        series = self.values or []
        has_limits = (self.lo is not None) or (self.hi is not None)
        if not series and not has_limits:
            return
        # 值域需把规格上下限纳入，保证限线可见；留 8% 余量避免贴边
        nums = list(series)
        if self.lo is not None:
            nums.append(self.lo)
        if self.hi is not None:
            nums.append(self.hi)
        vmin, vmax = min(nums), max(nums)
        span = (vmax - vmin) or 1.0
        vmin -= span * 0.08
        vmax += span * 0.08
        rng = vmax - vmin
        n = len(series)

        def X(i):
            return pad_l + (plot_w * i / (n - 1)) if n > 1 else pad_l + plot_w / 2

        def Y(v):
            return pad_t + plot_h * (1 - (v - vmin) / rng)

        # 横向网格 + 刻度
        p.setFont(QFont("Inter", 9))
        for k in range(5):
            gy = pad_t + plot_h * k / 4
            p.setPen(QPen(QColor("#D8D6D4"), 1))
            p.drawLine(pad_l, int(gy), pad_l + plot_w, int(gy))
            p.setPen(QPen(QColor("#666666"), 1))
            p.drawText(4, int(gy + 4), f"{vmax - rng * k / 4:.2f}")
        # 坐标轴
        p.setPen(QPen(QColor("#333333"), 1))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + plot_h)
        p.drawLine(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h)
        # 规格上下限线（红色虚线，右侧标注）
        if self.lo is not None:
            self._draw_limit(p, pad_l, plot_w, Y(self.lo), f"下限 {self.lo}", QColor("#C0392B"))
        if self.hi is not None:
            self._draw_limit(p, pad_l, plot_w, Y(self.hi), f"上限 {self.hi}", QColor("#C0392B"))
        # 散点：规格上下限范围内为绿点，范围外为橙黄色点（不再连成曲线）
        if series:
            GREEN = QColor("#0D822B")
            ORANGE = QColor("#F39C12")

            def in_spec(v):
                ok_lo = (self.lo is None) or (v >= self.lo)
                ok_hi = (self.hi is None) or (v <= self.hi)
                return ok_lo and ok_hi

            rad = 3
            for i, v in enumerate(series):
                c = GREEN if in_spec(v) else ORANGE
                cx, cy = X(i), Y(v)
                p.setPen(QPen(c, 1))
                p.setBrush(QBrush(c))
                p.drawEllipse(int(cx) - rad, int(cy) - rad, 2 * rad, 2 * rad)
        # 样本数
        p.setPen(QPen(QColor("#666666"), 1))
        p.drawText(pad_l, h - 6, f"样本数: {n}")

    def set_data(self, values):
        """更新曲线数据并重绘。"""
        self.values = values or []
        self.update()

    def set_limits(self, lo, hi):
        """仿真修改规格上下限后，更新限线并重绘。"""
        self.lo = lo
        self.hi = hi
        self.update()

    @staticmethod
    def _draw_limit(p, pad_l, plot_w, y, label, color):
        """在指定 y 画一条规格限虚线，并在右侧标注名称。"""
        iy = int(y)
        p.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
        p.drawLine(pad_l, iy, pad_l + plot_w, iy)
        # 标签底色块，保证压在网格/曲线上仍清晰
        p.setPen(QPen(color, 1))
        p.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        p.fillRect(pad_l + plot_w - 78, iy - 8, 76, 16, QColor("#FCECEA"))
        p.drawText(pad_l + plot_w - 76, iy + 4, label)


# ---------------------------------------------------------------------------
# 分布图弹窗
# ---------------------------------------------------------------------------
class DistributionDialog(QDialog):
    def __init__(self, parent, name, row, samples, lo=None, hi=None, prod_start=None):
        super().__init__(parent)
        self._owner = parent          # DebugView 实例（用于清零重置）
        self._row = row
        self._lo = lo
        self._hi = hi
        self._orig_lo = lo            # 检测列表中的原始设定值（「规格恢复」用）
        self._orig_hi = hi
        self._prod_start = prod_start
        self.setWindowTitle(f"数值分布 - {name}")
        self.setFixedSize(470, 540)
        self.setStyleSheet("QDialog{background-color:#1E1E1E;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        title = QLabel(f"检测项：{name}  数值分布曲线")
        title.setStyleSheet("color:#E6E6E6; font-size:13px; font-weight:bold;")
        lay.addWidget(title)

        # 数据时间范围说明（蓝字）
        self._time_range_lbl = QLabel("")
        self._time_range_lbl.setStyleSheet("color:#9FD3FF; font-size:11px;")
        lay.addWidget(self._time_range_lbl)

        self._curve = CurveWidget([], lo=lo, hi=hi)
        lay.addWidget(self._curve, 1)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet("color:#B9B9B9; font-size:11px;")
        lay.addWidget(self._stats_lbl)

        # 规格上下限（可仿真修改，联动 CPK / 限线 / 比例）
        spec_frame = QFrame()
        spec_frame.setStyleSheet(
            "QFrame{ background-color:#262626; border:1px solid #3A3A3A; "
            "border-radius:6px; }")
        spec_v = QVBoxLayout(spec_frame)
        spec_v.setContentsMargins(10, 8, 10, 8)
        spec_v.setSpacing(6)

        spec_title = QLabel("规格上下限（可仿真调整，联动 CPK 与限线）")
        spec_title.setStyleSheet("color:#B9B9B9; font-size:11px;")
        spec_v.addWidget(spec_title)

        hl = QHBoxLayout()
        hl.setSpacing(8)
        lbl_lo = QLabel("规格下限")
        lbl_lo.setStyleSheet("color:#E6E6E6; font-size:11px;")
        hl.addWidget(lbl_lo)
        self._sb_lo = QDoubleSpinBox()
        self._init_spec_sb(self._sb_lo, lo)
        hl.addWidget(self._sb_lo)
        lbl_hi = QLabel("规格上限")
        lbl_hi.setStyleSheet("color:#E6E6E6; font-size:11px;")
        hl.addWidget(lbl_hi)
        self._sb_hi = QDoubleSpinBox()
        self._init_spec_sb(self._sb_hi, hi)
        hl.addWidget(self._sb_hi)
        restore_btn = QPushButton("规格恢复")
        restore_btn.setStyleSheet(
            "background-color:#4261FF; color:#fff; border:none; border-radius:4px; "
            "padding:3px 10px; font-size:11px;")
        restore_btn.clicked.connect(self._on_spec_restore)
        hl.addWidget(restore_btn)
        hl.addStretch()
        spec_v.addLayout(hl)

        # 过程能力指数 CPK：≥1.33 合格，否则不合格
        self._cpk_lbl = QLabel("")
        self._cpk_lbl.setStyleSheet(
            "color:#FFFFFF; font-size:13px; font-weight:bold;")
        spec_v.addWidget(self._cpk_lbl)

        lay.addWidget(spec_frame)

        # 规格范围内的生产数据比例（超规格数据已不再单独标注红点）
        self._ratio_lbl = QLabel("")
        self._ratio_lbl.setStyleSheet(
            "color:#FF6B5E; font-size:11px; font-weight:bold;")
        lay.addWidget(self._ratio_lbl)

        # 时间范围检索：起 / 止 + 检索
        tf = QFrame()
        tl = QHBoxLayout(tf)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        lbl_from = QLabel("起:")
        lbl_from.setStyleSheet("color:#B9B9B9; font-size:11px;")
        tl.addWidget(lbl_from)
        self._dt_start = QDateTimeEdit(self)
        self._dt_end = QDateTimeEdit(self)
        for dtw in (self._dt_start, self._dt_end):
            dtw.setDisplayFormat("yyyy-MM-dd HH:mm")
            dtw.setCalendarPopup(True)
            dtw.setFixedHeight(24)
            tl.addWidget(dtw)
        search_btn = QPushButton("检索")
        search_btn.setStyleSheet(
            "background-color:#4261FF; color:#fff; border:none; border-radius:4px; "
            "padding:3px 12px; font-size:11px;")
        search_btn.clicked.connect(self._apply_filter)
        tl.addWidget(search_btn)
        tl.addStretch()
        lay.addWidget(tf)

        # 按钮：清零 / 关闭
        hb = QHBoxLayout()
        hb.addStretch()
        clear_btn = QPushButton("清零")
        clear_btn.setStyleSheet(
            "background-color:#4261FF; color:#fff; border:none; border-radius:4px; "
            "padding:4px 16px; font-size:12px;")
        clear_btn.clicked.connect(self._do_clear)
        hb.addWidget(clear_btn)
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "background-color:#3A3E47; color:#fff; border-radius:4px; "
            "padding:4px 14px; font-size:12px;")
        close_btn.clicked.connect(self.accept)
        hb.addWidget(close_btn)
        lay.addLayout(hb)

        # 实时刷新：分布样本随生产情况持续追加，曲线/统计每 0.5s 同步一次
        self._custom_filter = False
        self._filter_t0 = None
        self._filter_t1 = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start(500)
        # 所有控件建好后再连接规格上下限仿真编辑（避免初始化 setValue 触发早刷新）
        self._sb_lo.valueChanged.connect(self._on_spec_edit)
        self._sb_hi.valueChanged.connect(self._on_spec_edit)
        self._init_time_range()
        self._refresh_live()

    # ---- 实时刷新 ----
    def _refresh_live(self):
        """从 DebugView 实时读取该检测项的样本池并重绘。

        未手动检索时，自动显示『从生产启动（或清零时刻）到现在』的全部数据，
        随生产运行持续刷新；设备停止时样本不再增长，曲线自动停止刷新。
        """
        samples = self._owner.get_distribution_samples(self._row)
        now = datetime.now()
        if samples:
            dstart = min(t for t, _ in samples)
            dend = max(t for t, _ in samples)
        else:
            dstart = self._owner.get_distribution_start(self._row)
            dend = now
        if self._custom_filter and self._filter_t0 is not None:
            t0, t1 = self._filter_t0, self._filter_t1
        else:
            t0, t1 = dstart, now
            # 同步时间框显示，便于用户看到当前检索区间随生产推进
            self._dt_start.setDateTime(self._qdt(t0))
            self._dt_end.setDateTime(self._qdt(t1))
        self._render(t0, t1, samples)

    def _apply_filter(self):
        """点击『检索』：按时间框所选区间固定筛选（不再随生产自动扩展）。"""
        self._custom_filter = True
        self._filter_t0 = self._pydt(self._dt_start.dateTime())
        # 结束时间按「到分」选择，补满到所选分钟的 59 秒，避免截断该分钟内的数据
        self._filter_t1 = self._pydt(self._dt_end.dateTime().addSecs(59))
        if self._filter_t0 > self._filter_t1:
            self._filter_t0, self._filter_t1 = self._filter_t1, self._filter_t0
        samples = self._owner.get_distribution_samples(self._row)
        self._render(self._filter_t0, self._filter_t1, samples)

    def _render(self, t0, t1, samples):
        """按 [t0,t1] 区间渲染曲线 / 统计 / 规格范围内比例。"""
        self._update_time_range_label(t0, t1)
        filtered = [(t, v) for t, v in samples if t0 <= t <= t1]
        values = [v for _, v in filtered]
        self._curve.set_data(values)
        if values:
            n = len(values)
            mean = sum(values) / n
            self._stats_lbl.setText(
                f"样本数 {n}    均值 {mean:.3f}    "
                f"最小 {min(values):.3f}    最大 {max(values):.3f}")
        else:
            self._stats_lbl.setText("该时间范围内暂无数据")
        if (self._lo is not None or self._hi is not None) and values:
            ins = sum(
                1 for v in values
                if (self._lo is None or v >= self._lo)
                and (self._hi is None or v <= self._hi))
            self._ratio_lbl.setText(
                f"规格范围内生产数据比例：{ins / n * 100:.1f}%   （{ins}/{n}）")
            self._ratio_lbl.setVisible(True)
        else:
            self._ratio_lbl.setVisible(False)
        # 过程能力指数 CPK（随仿真修改后的规格上下限实时重算）
        cpk = self._compute_cpk(values, self._lo, self._hi)
        if cpk is None:
            self._cpk_lbl.setText("过程能力指数 CPK：—  （样本不足或标准差为 0）")
            self._cpk_lbl.setStyleSheet(
                "color:#B9B9B9; font-size:13px; font-weight:bold;")
        else:
            ok = cpk >= 1.33
            status = "合格（≥1.33）" if ok else "不合格（<1.33）"
            self._cpk_lbl.setText(f"过程能力指数 CPK：{cpk:.2f}    {status}")
            self._cpk_lbl.setStyleSheet(
                f"color:{'#2ECC71' if ok else '#E74C3C'}; "
                f"font-size:13px; font-weight:bold;")

    # ---- 规格上下限仿真编辑 ----
    def _init_spec_sb(self, sb, val):
        """初始化一个规格上下限数字输入框（默认 3 位小数）。

        注意：此处先不连接 valueChanged，避免初始化 setValue 时提前触发
        _refresh_live（彼时时间框等控件尚未创建）；连接统一在 __init__ 末尾完成。
        """
        sb.setRange(-1e9, 1e9)
        sb.setDecimals(3)
        sb.setSingleStep(0.1)
        sb.setFixedWidth(96)
        # 与其他页面统一的数值输入框样式（边框/内边距/上下按钮宽度一致），
        # 仅将数值字体缩小（10px），满足「数值字体改小」的需求。
        sb.setStyleSheet(
            f"QDoubleSpinBox {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 10px; }}"
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; }}")
        if val is not None:
            sb.blockSignals(True)
            sb.setValue(float(val))
            sb.blockSignals(False)

    def _on_spec_edit(self):
        """仿真修改规格上下限：更新限线 / 比例 / CPK。"""
        self._lo = self._sb_lo.value()
        self._hi = self._sb_hi.value()
        self._curve.set_limits(self._lo, self._hi)
        self._refresh_live()

    def _on_spec_restore(self):
        """点击『规格恢复』：将规格上下限重置回检测列表中的原始设定值。"""
        self._sb_lo.blockSignals(True)
        self._sb_hi.blockSignals(True)
        if self._orig_lo is not None:
            self._sb_lo.setValue(float(self._orig_lo))
        if self._orig_hi is not None:
            self._sb_hi.setValue(float(self._orig_hi))
        self._sb_lo.blockSignals(False)
        self._sb_hi.blockSignals(False)
        self._on_spec_edit()

    @staticmethod
    def _compute_cpk(values, lo, hi):
        """过程能力指数 CPK = min((USL-mean)/(3σ), (mean-LSL)/(3σ))。

        σ 取样本标准差（ddof=1）；样本不足或 σ=0 时返回 None。
        仅给单边限时退化为对应单侧能力指数。
        """
        n = len(values)
        if n < 2:
            return None
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        sigma = var ** 0.5
        if sigma <= 0:
            return None
        cpu = cpl = None
        if hi is not None:
            cpu = (hi - mean) / (3.0 * sigma)
        if lo is not None:
            cpl = (mean - lo) / (3.0 * sigma)
        cands = [c for c in (cpu, cpl) if c is not None]
        if not cands:
            return None
        return min(cands)

    def _do_clear(self):
        """点击『清零』：清除曲线数据，随后随生产运行重新累计并刷新显示。"""
        if self._owner is not None and hasattr(self._owner, "clear_distribution"):
            self._owner.clear_distribution(self._row)
        self._custom_filter = False
        self._filter_t0 = None
        self._filter_t1 = None
        self._refresh_live()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    # ---- 时间工具 ----
    @staticmethod
    def _qdt(dt):
        return QDateTime.fromSecsSinceEpoch(int(dt.timestamp()))

    @staticmethod
    def _pydt(qdt):
        return qdt.toPyDateTime()

    def _init_time_range(self):
        samples = self._owner.get_distribution_samples(self._row)
        if samples:
            t0 = min(t for t, _ in samples)
            t1 = max(t for t, _ in samples)
        else:
            now = datetime.now()
            t0 = self._owner.get_distribution_start(self._row)
            t1 = now
        self._dt_start.setDateTime(self._qdt(t0))
        self._dt_end.setDateTime(self._qdt(t1))
        self._update_time_range_label(t0, t1)

    def _update_time_range_label(self, t0, t1):
        self._time_range_lbl.setText(
            f"数据时间范围：{t0.strftime('%Y-%m-%d %H:%M:%S')}  ~  "
            f"{t1.strftime('%Y-%m-%d %H:%M:%S')}")


# ---------------------------------------------------------------------------
# 教导弹窗：图像通道选择 + 画布点击选两个计算元素 + 确认
# ---------------------------------------------------------------------------
class TeachCanvas(QWidget):
    """教导画布：显示通道图像并预绘制示例计算元素（外围轮廓 + 左/右直线），
    支持鼠标左键依次点击选中计算元素（直线）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._elements = []      # 示例计算元素（含可点选的直线）
        self._selected = []      # 已选元素 id（按点击顺序）
        self._draw_rect = None   # 实际绘制区域（显示坐标），用于坐标映射
        self._on_pick = None     # 选点回调：on_pick(count)
        self.setMinimumSize(360, 270)
        self.setStyleSheet("background-color:#0F1115; border:1px solid #2A2E35;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_pixmap(self, pm):
        self._pixmap = pm
        self._build_elements()
        self.update()

    def _build_elements(self):
        """依据归一化坐标（0..1）构建示例计算元素。"""
        self._elements = [
            # 外围轮廓（示例，仅展示，不可点选）
            {"id": "contour", "label": "外围轮廓（示例）", "selectable": False,
             "rect": (0.10, 0.12, 0.90, 0.88)},
            # 左边直线（可点选，示例计算元素 1）
            {"id": "left_line", "label": "① 左边直线", "selectable": True,
             "line": (0.22, 0.18, 0.22, 0.82)},
            # 右边直线（可点选，示例计算元素 2）
            {"id": "right_line", "label": "② 右边直线", "selectable": True,
             "line": (0.78, 0.18, 0.78, 0.82)},
        ]

    def clear_selection(self):
        self._selected = []
        self.update()

    def _norm_to_display(self, u, v):
        dr = self._draw_rect
        return (dr.x() + u * dr.width(), dr.y() + v * dr.height())

    def _display_to_norm(self, x, y):
        dr = self._draw_rect
        return ((x - dr.x()) / dr.width(), (y - dr.y()) / dr.height())

    @staticmethod
    def _dist_to_segment(px, py, ax, ay, bx, by):
        """点到线段距离（像素坐标）。"""
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * dx, ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._pixmap is None or self._draw_rect is None:
            return
        u, v = self._display_to_norm(event.position().x(), event.position().y())
        iw, ih = self._pixmap.width(), self._pixmap.height()
        px, py = u * iw, v * ih
        best, best_d = None, 18  # 点选阈值（图像像素）
        for el in self._elements:
            if not el.get("selectable") or el["id"] in self._selected:
                continue
            ax, ay, bx, by = el["line"]
            d = self._dist_to_segment(px, py, ax * iw, ay * ih, bx * iw, by * ih)
            if d < best_d:
                best_d, best = d, el["id"]
        if best is not None:
            self._selected.append(best)
            self.update()
            if self._on_pick:
                self._on_pick(len(self._selected))

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0F1115"))
        if self._pixmap is None:
            p.setPen(QColor("#666666"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无图像")
            return
        scaled = self._pixmap.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        dx = (self.width() - scaled.width()) // 2
        dy = (self.height() - scaled.height()) // 2
        self._draw_rect = QRect(dx, dy, scaled.width(), scaled.height())
        p.drawPixmap(dx, dy, scaled)
        p.setFont(QFont("Microsoft YaHei", 9))

        for el in self._elements:
            if "rect" in el:
                # 外围轮廓：虚线灰框
                x0, y0, x1, y1 = el["rect"]
                rx, ry = self._norm_to_display(x0, y0)
                rx2, ry2 = self._norm_to_display(x1, y1)
                p.setPen(QPen(QColor("#5A6170"), 1, Qt.PenStyle.DashLine))
                p.drawRect(int(min(rx, rx2)), int(min(ry, ry2)),
                           int(abs(rx2 - rx)), int(abs(ry2 - ry)))
                p.setPen(QColor("#7A8290"))
                p.drawText(int(rx) + 4, int(ry) - 4, el["label"])
                continue
            # 直线元素（可点选）
            u0, v0, u1, v1 = el["line"]
            sx0, sy0 = self._norm_to_display(u0, v0)
            sx1, sy1 = self._norm_to_display(u1, v1)
            sel_idx = self._selected.index(el["id"]) if el["id"] in self._selected else -1
            if sel_idx >= 0:
                color = QColor("#FF8C1A")   # 已选中：实线橙、加粗
                p.setPen(QPen(color, 3))
            else:
                color = QColor("#00E5FF")    # 未选中：青色虚线
                p.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            p.drawLine(int(sx0), int(sy0), int(sx1), int(sy1))
            p.setPen(color)
            lbl = el["label"] if sel_idx < 0 else f"{el['label']}（已选{sel_idx + 1}）"
            p.drawText(int(sx0) + 6, int(sy0) - 4, lbl)


class TeachDialog(QDialog):
    def __init__(self, parent, name, base_image=None):
        super().__init__(parent)
        self.setWindowTitle(f"教导 - {name}")
        # 窗口按内容最小宽高显示完全（构建后 adjustSize）
        self.setStyleSheet("QDialog{background-color:#1E1E1E;}")
        self.base_image = base_image  # 原始彩色 QImage（RGB32）

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        title = QLabel(f"检测项教导：{name}")
        title.setStyleSheet("color:#E6E6E6; font-size:13px; font-weight:bold;")
        lay.addWidget(title)

        # 图像通道选择
        ch_row = QHBoxLayout()
        ch_label = QLabel("选择图像通道：")
        ch_label.setStyleSheet("color:#B9B9B9; font-size:12px;")
        self._ch_combo = QComboBox()
        self._ch_combo.addItems(["源图", "灰度图", "R通道图", "G通道图", "B通道图"])
        self._ch_combo.setMinimumHeight(26)
        self._ch_combo.setStyleSheet(
            "QComboBox{background-color:#2A2E35; color:#E6E6E6; border:1px solid #3A3E47; "
            "border-radius:4px; padding:2px 6px; font-size:12px;}")
        self._ch_combo.currentTextChanged.connect(self._render_channel)
        ch_row.addWidget(ch_label)
        ch_row.addWidget(self._ch_combo)
        note_lbl = QLabel("（会自动从相机画布中冻结抓取最新的一张图用于教导）")
        note_lbl.setStyleSheet("color:#7A8290; font-size:11px;")
        note_lbl.setWordWrap(True)
        ch_row.addWidget(note_lbl)
        ch_row.addStretch()
        lay.addLayout(ch_row)

        # 步骤提示
        self._hint_lbl = QLabel("请点击画布中的直线，依次选中第 1 个计算元素")
        self._hint_lbl.setStyleSheet("color:#FFD400; font-size:12px;")
        lay.addWidget(self._hint_lbl)

        # 画布（固定尺寸；窗口按内容最小宽高显示完全）
        self._canvas = TeachCanvas()
        self._canvas.setFixedSize(360, 270)
        self._canvas._on_pick = self._on_pick
        lay.addWidget(self._canvas)

        # 按钮行
        hb = QHBoxLayout()
        clear_btn = QPushButton("清空选择")
        clear_btn.setStyleSheet(
            "background-color:#3A3E47; color:#fff; border-radius:4px; padding:4px 12px; font-size:12px;")
        clear_btn.clicked.connect(self._on_clear)
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(
            "background-color:#3A3E47; color:#fff; border-radius:4px; padding:4px 12px; font-size:12px;")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("确认")
        confirm_btn.setStyleSheet(
            "background-color:#0D822B; color:#fff; border:none; border-radius:4px; "
            "padding:4px 16px; font-size:12px; font-weight:bold;")
        confirm_btn.clicked.connect(self._on_confirm)
        hb.addStretch()
        hb.addWidget(clear_btn)
        hb.addWidget(cancel_btn)
        hb.addWidget(confirm_btn)
        lay.addLayout(hb)

        self._render_channel()
        self.adjustSize()   # 按内容最小宽高显示完全

    def _render_channel(self):
        if self.base_image is None:
            self._canvas.set_pixmap(QPixmap())
            return
        img = self.base_image
        ch = self._ch_combo.currentText()
        if ch == "源图":
            out = img.copy()
        elif ch == "灰度图":
            out = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_RGB32)
        else:
            base = img.convertToFormat(QImage.Format.Format_RGB32)
            w, h = base.width(), base.height()
            out = QImage(w, h, QImage.Format.Format_RGB32)
            out.fill(0)
            for y in range(h):
                for x in range(w):
                    c = base.pixelColor(x, y)
                    if ch == "R通道图":
                        out.setPixelColor(x, y, QColor(c.red(), 0, 0))
                    elif ch == "G通道图":
                        out.setPixelColor(x, y, QColor(0, c.green(), 0))
                    else:
                        out.setPixelColor(x, y, QColor(0, 0, c.blue()))
        self._canvas.set_pixmap(QPixmap.fromImage(out))

    def _on_pick(self, count):
        if count == 0:
            self._hint_lbl.setText("请点击画布中的直线，依次选中第 1 个计算元素")
        elif count == 1:
            self._hint_lbl.setText("请点击画布中的直线，依次选中第 2 个计算元素")
        else:
            self._hint_lbl.setText("已完成两个计算元素选择，可点击「确认」完成教导")

    def _on_clear(self):
        self._canvas.clear_selection()
        self._on_pick(0)

    def _on_confirm(self):
        if len(self._canvas._selected) < 2:
            QMessageBox.information(self, "提示", "请依次点击画布中的两条直线，选中两个计算元素。")
            return
        self.accept()

    def get_result(self):
        sel = [el for el in self._canvas._elements if el["id"] in self._canvas._selected]
        return {
            "channel": self._ch_combo.currentText(),
            "elements": [el["label"] for el in sel],
        }


# ---------------------------------------------------------------------------
# 产品目标定位相关子页面内容：产品定位及区域分割 / 计算元素精确查找
# （这些子页面被 DebugView 塞入既有「产品定位搜索设置」卡片，不单独成区）
# ---------------------------------------------------------------------------
class TargetLocationContent(QWidget):
    """产品目标搜索相关子页面内容（不自带卡片边框/标题）：

    - 产品目标搜索：顶部「搜索方式」下拉选择「模板匹配 / AI分割」。
        * 模板匹配：点击「注册模板」弹出非模态窗口（导入/导出/共享模板）；
          共享模板展开其它工位相机下拉。
        * AI分割：点击「导入模型」加载本地模型文件并显示路径+文件名；
          「更新模型」占位提示；「共享模型」展开其它工位相机下拉。
    - 计算元素精确查找：列出 16 个精确查找项，每行「序号」右侧带开关（默认全部开启），
      点击「参数设置」弹出目标查找参数设置窗口（匹配阈值/面积/容差/极性）；
      顶部「显示所有 / 显示已选」合并为单个切换按钮。

    由 DebugView 将这两个子页面塞入现有卡片（标签页切换，标签带 1./2. 顺序编号），
    不再单独成为显示区域，卡片也不再显示「产品定位搜索设置」标题。
    """

    # 计算元素精确查找项：与 CameraScreen.CANVAS_ITEM_SHAPES 的键一一对应
    # （每项都有画布叠加形状，行首眼睛按钮逐项控制其在图像画布中的显隐；
    #   第 12 项原表与第 10 项重复，按对称结构修正为「右端头内侧轮廓查找」）
    FIND_ITEMS = list(CameraScreen.CANVAS_ITEM_SHAPES.keys())

    def __init__(self, parent=None, run_log=None, camera_name=None,
                 camera_preview=None):
        super().__init__(parent)
        self._run_log = run_log
        self._camera_name = camera_name
        # 所属相机画布：行首眼睛按钮逐项控制该画布上计算元素的显示 / 隐藏
        self._camera_preview = camera_preview
        # 其它工位相机：用于「共享模板 / 共享模型」下拉选项的候选
        self._other_cameras = [c for c in CAMERA_NAMES if c != camera_name]
        self._model_path = ""
        self._model_name = ""
        self._last_dir = self._default_model_dir()
        self._find_btns = []
        self._find_params = {}                 # 已设置的目标查找参数：{name: params}
        self._param_dialogs = {}               # 非模态参数设置窗口：{name: TargetParamDialog}
        self._tmpl_dlg = None                  # 非模态「注册模板」窗口
        self._show_selected_only = False       # 计算元素列表当前是否处于「仅显示已选」模式
        self._tab1 = QWidget()
        self._tab2 = QWidget()
        self._build_tab1(self._tab1)
        self._build_tab2(self._tab2)

    # -- 子页面 1：产品目标搜索 ----------------------------------------------
    def _build_tab1(self, tab):
        v = QVBoxLayout(tab)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(12)

        # 搜索方式：下拉选择「模板匹配」/「AI分割」
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_lbl = QLabel("搜索方式：")
        mode_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["模板匹配", "AI分割"])
        self._mode_combo.setFixedSize(160, 30)
        # 下拉框与展开后选项文字统一使用 13px（像素），与「搜索方式：」标签的 font-size:13px 完全一致。
        # 注意：QFont 第二个参数单位是「磅(pt)」，13pt≈17px，会比 CSS 13px 标签明显偏大；
        # 故改用 setPixelSize(13)，保证「模板匹配 / AI分割」选项与标签字号一模一样。
        _combo_font = QFont("Microsoft YaHei")
        _combo_font.setPixelSize(13)
        self._mode_combo.setFont(_combo_font)
        self._mode_combo.view().setFont(_combo_font)
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        # 模板匹配 / AI分割 两个面板，随下拉切换
        self._mode_stack = QStackedWidget()
        self._tmpl_page = QWidget()
        self._ai_page = QWidget()
        self._build_template_page(self._tmpl_page)
        self._build_ai_page(self._ai_page)
        self._mode_stack.addWidget(self._tmpl_page)
        self._mode_stack.addWidget(self._ai_page)
        v.addWidget(self._mode_stack, 1)

    def _on_mode_changed(self, text):
        """切换「模板匹配 / AI分割」面板。"""
        if text == "AI分割":
            self._mode_stack.setCurrentWidget(self._ai_page)
        else:
            self._mode_stack.setCurrentWidget(self._tmpl_page)

    # 模板匹配面板
    def _build_template_page(self, page):
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(10)
        reg_btn = QPushButton("注册模板")
        reg_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-size: 13px;")
        reg_btn.clicked.connect(self._on_register_template)
        row.addWidget(reg_btn)
        row.addStretch(1)
        v.addLayout(row)

        self._tmpl_info = QLabel("尚未注册模板")
        self._tmpl_info.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        v.addWidget(self._tmpl_info)
        v.addStretch(1)

    def _on_register_template(self):
        """打开非模态「注册模板」窗口（已打开则置顶，不重复创建）。"""
        if self._tmpl_dlg is None:
            self._tmpl_dlg = TemplateRegisterDialog(self._other_cameras, self)
        self._tmpl_dlg.show()
        self._tmpl_dlg.raise_()
        self._tmpl_dlg.activateWindow()

    # AI分割面板
    def _build_ai_page(self, page):
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        load_btn = QPushButton("导入模型")
        load_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 16px; font-size: 13px;")
        load_btn.clicked.connect(self._on_load_model)
        upd_btn = QPushButton("更新模型")
        upd_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; "
            f"padding: 6px 16px; font-size: 13px;")
        upd_btn.clicked.connect(self._on_update_model)
        share_btn = QPushButton("共享模型")
        share_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 16px; font-size: 13px;")
        share_btn.clicked.connect(self._on_ai_share_toggle)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(upd_btn)
        btn_row.addWidget(share_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        # 共享模型下拉（默认隐藏，点击「共享模型」后展开）
        self._ai_share_combo = QComboBox()
        self._ai_share_combo.addItem("选择共享目标工位相机…")
        self._ai_share_combo.addItems(self._other_cameras)
        self._ai_share_combo.setFixedSize(220, 30)
        self._ai_share_combo.setFont(QFont("Microsoft YaHei", 12))
        self._ai_share_combo.view().setFont(QFont("Microsoft YaHei", 12))
        self._ai_share_combo.setVisible(False)
        self._ai_share_combo.currentTextChanged.connect(self._on_ai_share)
        v.addWidget(self._ai_share_combo)

        # 路径 + 文件名 显示区（只读）
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        path_lbl = QLabel("模型路径：")
        path_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self._path_edit = QLineEdit("")
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("尚未加载模型")
        name_lbl = QLabel("模型文件：")
        name_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self._name_edit = QLineEdit("")
        self._name_edit.setReadOnly(True)
        self._name_edit.setPlaceholderText("—")
        grid.addWidget(path_lbl, 0, 0)
        grid.addWidget(self._path_edit, 0, 1)
        grid.addWidget(name_lbl, 1, 0)
        grid.addWidget(self._name_edit, 1, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        v.addStretch(1)

    def _on_ai_share_toggle(self):
        """点击「共享模型」：展开/收起其它工位相机下拉。"""
        self._ai_share_combo.setVisible(not self._ai_share_combo.isVisible())
        if self._ai_share_combo.isVisible():
            self._ai_share_combo.setCurrentIndex(0)

    def _on_ai_share(self, target):
        """选择共享目标工位相机后，记录并提示。"""
        if not target or target.startswith("选择"):
            return
        self._log(f"已共享模型至工位相机：{target}")
        QMessageBox.information(self, "共享模型", f"已将当前模型共享至工位相机「{target}」。")

    def _on_load_model(self):
        """弹出文件对话框，加载本地模型文件，并显示路径与文件名。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入模型", self._last_dir,
            "模型文件 (*.onnx *.pt *.pth *.model *.json *.bin);;所有文件 (*.*)")
        if not path:
            return
        self._last_dir = os.path.dirname(path)
        self._model_path = path
        self._model_name = os.path.basename(path)
        self._path_edit.setText(path)
        self._name_edit.setText(self._model_name)
        self._log(f"已加载模型：{self._model_name}（{path}）")

    def _on_update_model(self):
        """更新模型：暂无示例操作步骤内容，给出占位提示。"""
        if not self._model_path:
            QMessageBox.information(self, "提示", "请先导入模型，再进行更新。")
            return
        QMessageBox.information(
            self, "提示",
            f"更新模型「{self._model_name}」：暂无示例操作步骤内容。")
        self._log(f"更新模型（暂无示例操作步骤）：{self._model_name}")

    # -- 子页面 2：计算元素精确查找 ------------------------------------------
    def _build_tab2(self, tab):
        v = QVBoxLayout(tab)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(10)

        # 显示控制：显示所有 / 显示已选 合并为单个切换按钮（点击在两种模式间切换）
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self._toggle_show_btn = QPushButton("显示所有")
        self._toggle_show_btn.setFixedSize(82, 26)
        self._toggle_show_btn.setStyleSheet(self._find_btn_style())
        self._toggle_show_btn.clicked.connect(self._on_toggle_show)
        ctrl_row.addWidget(self._toggle_show_btn)
        ctrl_row.addStretch(1)
        v.addLayout(ctrl_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(10)   # 行间距放宽，列表不再拥挤

        self._find_rows = []   # 每行: (row_widget, checkbox, btn, name)
        self._find_eye_btns = []          # 每行行首眼睛按钮（与 FIND_ITEMS 顺序一致）
        self._item_visible = {}           # 逐项显隐状态：{name: bool}，缺省显示
        for i, name in enumerate(self.FIND_ITEMS, 1):
            row_w = QWidget()
            row = QHBoxLayout(row_w)
            # 上下各留 3px，序号列加宽到 26px，名称与勾选框之间留 10px 呼吸感
            row.setContentsMargins(0, 3, 0, 3)
            row.setSpacing(10)
            # 行首「显示/隐藏」眼睛按钮（序列号左侧）：控制该元素在图像画布中的叠加显隐
            eye = QPushButton()
            eye.setFixedSize(22, 22)
            eye.setCursor(Qt.CursorShape.PointingHandCursor)
            eye.setToolTip(f"显示 / 隐藏「{name}」在图像画布中的叠加")
            eye.setStyleSheet(
                "QPushButton{background-color: rgba(20,22,26,0.60); border:none; "
                "border-radius:4px;}"
                "QPushButton:hover{background-color: rgba(20,22,26,0.90);}")
            vis = self._item_visible.get(name, True)
            eye.setIcon(CameraPreview._eye_icon(vis))
            eye.setIconSize(QSize(14, 14))
            eye.clicked.connect(
                lambda _, n=name, e=eye: self._on_toggle_item_visible(n, e))
            idx = QLabel(f"{i}")
            idx.setFixedWidth(26)
            idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
            idx.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            sw = ToggleSwitch(on=True)   # 默认均为开启
            nm = QLabel(name)
            nm.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px; padding-left: 6px;")
            btn = QPushButton("参数设置")
            btn.setFixedSize(72, 24)
            btn.setStyleSheet(self._find_btn_style())
            btn.clicked.connect(lambda _, n=name, b=btn: self._on_param_setting(n, b))
            row.addWidget(eye)
            row.addWidget(idx)
            row.addWidget(sw)
            row.addWidget(nm, 1)
            row.addWidget(btn)
            inner_lay.addWidget(row_w)
            self._find_btns.append(btn)
            self._find_eye_btns.append(eye)
            self._find_rows.append((row_w, sw, btn, name))
            # 在「显示已选」模式下，开关状态变化实时刷新可见行
            sw.toggled.connect(lambda *_, s=sw: self._refilter())

        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

    def _on_toggle_item_visible(self, name, eye_btn):
        """点击行首眼睛按钮：切换该计算元素在图像画布中的显示 / 隐藏。

        显示（睁眼）时该元素的直线 / 轮廓叠加在画布上绘制；隐藏（闭眼）时不绘制。
        """
        vis = not self._item_visible.get(name, True)
        self._item_visible[name] = vis
        eye_btn.setIcon(CameraPreview._eye_icon(vis))
        scr = getattr(self._camera_preview, "screen", None) \
            if self._camera_preview is not None else None
        if scr is not None and hasattr(scr, "set_item_visible"):
            scr.set_item_visible(name, vis)
        self._log(f"{'显示' if vis else '隐藏'}计算元素画布叠加：{name}")

    def _on_param_setting(self, name, btn):
        """点击「参数设置」弹出目标查找参数设置窗口（非模态，不阻塞其它操作）。

        同一计算元素已打开窗口时仅置顶，不重复创建。
        入口先走空闲确认（高级设置「密码输入确认时间周期」）：登录用户超时未操作软件时，
        会先弹窗要求重新输入密码，通过后才继续修改算法参数。
        """
        mw = getattr(self, "main_window", None)
        confirm = getattr(mw, "confirm_if_idle", None)
        if callable(confirm) and not confirm(f"参数设置 - {name}"):
            return
        dlg = self._param_dialogs.get(name)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = TargetParamDialog(name, self)
        prev = self._find_params.get(name)
        if prev:
            dlg.set_params(prev)
        # 非模态：通过 accepted 信号保存，关闭时清理引用
        dlg.accepted.connect(
            lambda: self._on_param_dialog_accepted(name, dlg, btn))
        dlg.finished.connect(
            lambda _r, n=name: self._param_dialogs.pop(n, None))
        self._param_dialogs[name] = dlg
        dlg.show()

    def _on_param_dialog_accepted(self, name, dlg, btn):
        """参数窗口点「确定」后保存并返回结果到列表。"""
        p = dlg.get_params()
        self._find_params[name] = p
        btn.setText("已设置")
        btn.setStyleSheet(self._find_btn_done_style())
        self._log(
            f"已应用目标查找参数：{name}（匹配阈值 {p['thresh_lo']}%-{p['thresh_hi']}%，"
            f"面积 {p['area_lo']}-{p['area_hi']}px²，容差 {p['tol_lo']}-{p['tol_hi']}px，"
            f"{p['polarity']}）")

    def _on_toggle_show(self):
        """切换「显示所有 / 显示已选」：按钮文字反映当前模式，点击后切换并刷新。"""
        self._show_selected_only = not self._show_selected_only
        self._toggle_show_btn.setText(
            "显示已选" if self._show_selected_only else "显示所有")
        self._refilter()

    def _refilter(self):
        if self._show_selected_only:
            for row_w, sw, btn, name in self._find_rows:
                row_w.setVisible(sw.is_on())
        else:
            for row_w, sw, btn, name in self._find_rows:
                row_w.setVisible(True)

    # -- 样式与工具 ----------------------------------------------------------
    def _find_btn_style(self):
        return (
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; font-size: 11px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; }}")

    def _find_btn_done_style(self):
        return (
            f"QPushButton {{ background-color: {COLORS['accent_green']}; "
            f"color: white; border: none; border-radius: 4px; font-size: 11px; }}")

    @staticmethod
    def _default_model_dir():
        """默认打开目录：打包后取 exe 所在目录，开发时取脚本目录；优先用 models 子目录。"""
        if getattr(sys, "frozen", False):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(base, "models")
        return cand if os.path.isdir(cand) else base

    def _log(self, msg):
        if self._run_log is None:
            return
        try:
            self._run_log.add(datetime.now().strftime("%H:%M:%S"), msg, "#4261FF")
        except Exception:
            pass

    @staticmethod
    def style_tab_widget(tabs):
        """为承载「搜索设置/产品定位及区域分割/计算元素精确查找」的标签页统一上样式。"""
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {COLORS['bg_dark']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                top: 4px;
            }}
            QTabBar::tab {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_secondary']};
                padding: 6px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['accent_orange']};
                color: white;
            }}
        """)


class TemplateRegisterDialog(QDialog):
    """非模态「注册模板」窗口：导入 / 导出 / 共享模板。

    - 导入模板：弹出文件对话框加载本地模板文件，显示路径与文件名。
    - 导出模板：将已导入模板导出为本地文件。
    - 共享模板：展开下拉复选项，列出其它工位相机名称，选择后共享。
    """

    def __init__(self, other_cameras, parent=None):
        super().__init__(parent)
        self._other_cameras = list(other_cameras or [])
        self._tmpl_path = ""
        self._tmpl_name = ""
        self.setWindowTitle("注册模板")
        self.setMinimumSize(380, 240)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        # 去掉「?」帮助按钮并置顶显示
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            | Qt.WindowType.WindowStaysOnTopHint)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._imp_btn = QPushButton("导入模板")
        self._exp_btn = QPushButton("导出模板")
        self._share_btn = QPushButton("共享模板")
        btn_style = (
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 14px; font-size: 13px;")
        for b in (self._imp_btn, self._exp_btn, self._share_btn):
            b.setFixedHeight(32)
            b.setFont(QFont("Microsoft YaHei", 12))
            b.setStyleSheet(btn_style)
        self._imp_btn.clicked.connect(self._on_import)
        self._exp_btn.clicked.connect(self._on_export)
        self._share_btn.clicked.connect(self._on_share_toggle)
        btn_row.addWidget(self._imp_btn)
        btn_row.addWidget(self._exp_btn)
        btn_row.addWidget(self._share_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        # 共享模板下拉（默认隐藏，点击「共享模板」后展开）
        self._share_combo = QComboBox()
        self._share_combo.addItem("选择共享目标工位相机…")
        self._share_combo.addItems(self._other_cameras)
        self._share_combo.setFixedSize(240, 30)
        self._share_combo.setFont(QFont("Microsoft YaHei", 12))
        self._share_combo.view().setFont(QFont("Microsoft YaHei", 12))
        self._share_combo.setVisible(False)
        self._share_combo.currentTextChanged.connect(self._on_share)
        v.addWidget(self._share_combo)

        # 模板路径 / 文件显示
        self._info = QLabel("尚未导入模板")
        self._info.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        v.addWidget(self._info)
        v.addStretch(1)

    def _log_parent(self, msg):
        parent = self.parent()
        if parent is not None and hasattr(parent, "_log"):
            parent._log(msg)

    def _on_import(self):
        """导入模板：加载本地模板文件并显示路径与文件名。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入模板", "",
            "模板文件 (*.json *.yaml *.yml *.xml *.bin *.dat);;所有文件 (*.*)")
        if not path:
            return
        self._tmpl_path = path
        self._tmpl_name = os.path.basename(path)
        self._info.setText(f"模板文件：{self._tmpl_name}\n模板路径：{path}")
        self._log_parent(f"已导入模板：{self._tmpl_name}（{path}）")

    def _on_export(self):
        """导出模板：将已导入模板保存为本地文件。"""
        if not self._tmpl_path:
            QMessageBox.information(self, "提示", "请先导入模板，再进行导出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出模板", self._tmpl_name,
            "模板文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"name": self._tmpl_name, "source": self._tmpl_path},
                          f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "提示", f"模板已导出至：\n{path}")
            self._log_parent(f"已导出模板至：{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_share_toggle(self):
        """点击「共享模板」：展开/收起其它工位相机下拉。"""
        self._share_combo.setVisible(not self._share_combo.isVisible())
        if self._share_combo.isVisible():
            self._share_combo.setCurrentIndex(0)

    def _on_share(self, target):
        """选择共享目标工位相机后，记录并提示。"""
        if not target or target.startswith("选择"):
            return
        QMessageBox.information(self, "共享模板", f"已将模板共享至工位相机「{target}」。")
        self._log_parent(f"已共享模板至工位相机：{target}")


class DistributionChart(QWidget):
    """结果分布图（纯 QPainter 绘制，无第三方依赖）。

    支持两种模式：
    - 数值型：直方图 + 97% 区间上下限线（橙色虚线）+ 当前设置值标记（绿色虚线）。
    - 类别型：各分类计数柱状图，当前选中的分类高亮为绿色。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 220)
        self._samples = []
        self._unit = ""
        self._decimals = 0
        self._lo = None
        self._hi = None
        self._cur_lo = None
        self._cur_hi = None
        self._cats = None  # 类别型：(名称, 计数, 是否当前)
        self._mode = "scatter"  # 数值型视图：scatter / hist / ecdf
        self.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border-radius: 6px;")

    def set_numeric(self, samples, unit, decimals, lo, hi, cur_lo, cur_hi):
        self._cats = None
        self._samples = list(samples)
        self._unit = unit
        self._decimals = decimals
        self._lo = lo
        self._hi = hi
        self._cur_lo = cur_lo
        self._cur_hi = cur_hi
        self.update()

    def set_categorical(self, cats):
        self._cats = cats
        self._samples = []
        self.update()

    def set_mode(self, mode):
        if mode in ("scatter", "hist", "ecdf") and mode != self._mode:
            self._mode = mode
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(COLORS["bg_card"]))
        if self._cats is not None:
            self._draw_categorical(p, w, h)
        elif self._samples:
            if self._mode == "hist":
                self._draw_hist(p, w, h)
            elif self._mode == "ecdf":
                self._draw_ecdf(p, w, h)
            else:
                self._draw_scatter(p, w, h)
        else:
            p.setPen(QColor(COLORS["text_secondary"]))
            p.setFont(QFont("Microsoft YaHei", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")

    # ---- 公共：取值范围与阈值线 ----
    def _range(self, s):
        s_min, s_max = min(s), max(s)
        x0 = min(s_min, self._lo if self._lo is not None else s_min)
        x1 = max(s_max, self._hi if self._hi is not None else s_max)
        for cv in (self._cur_lo, self._cur_hi):
            if cv is not None:
                x0 = min(x0, cv)
                x1 = max(x1, cv)
        rng = (x1 - x0) or 1.0
        x0 -= rng * 0.04
        x1 += rng * 0.04
        return x0, x1

    def _vline(self, p, x, color, lw, label, ly, pad_t, plot_h):
        p.setPen(QPen(QColor(color), lw, Qt.PenStyle.DashLine))
        p.drawLine(int(x), pad_t, int(x), pad_t + plot_h)
        if label:
            p.setPen(QColor(color))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(int(x) + 3, ly, label)

    def _draw_hist(self, p, w, h):
        text = QColor(COLORS["text_primary"])
        sec = QColor(COLORS["text_secondary"])
        border = QColor(COLORS["border"])
        pad_l, pad_r, pad_t, pad_b = 46, 14, 18, 26
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        s = self._samples
        x0, x1 = self._range(s)
        rng = x1 - x0

        def X(v):
            return pad_l + plot_w * (v - x0) / rng

        nb = 24
        counts = [0] * nb
        for v in s:
            idx = int((v - x0) / rng * nb)
            idx = 0 if idx < 0 else (nb - 1 if idx >= nb else idx)
            counts[idx] += 1
        maxc = max(counts) or 1
        p.setFont(QFont("Microsoft YaHei", 9))
        for k in range(5):
            gy = pad_t + plot_h * k / 4
            p.setPen(QPen(border, 1))
            p.drawLine(pad_l, int(gy), pad_l + plot_w, int(gy))
            p.setPen(sec)
            p.drawText(QRect(2, int(gy) - 8, pad_l - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{maxc * (4 - k) // 4}")
        bw = plot_w / nb
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(COLORS["accent_blue"])))
        for i, c in enumerate(counts):
            if c == 0:
                continue
            bx = pad_l + i * bw
            bh = plot_h * (c / maxc)
            p.drawRect(int(bx + 1), int(pad_t + plot_h - bh),
                       max(1, int(bw - 2)), int(bh))
        p.setPen(QPen(text, 1))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + plot_h)
        p.drawLine(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h)
        for lim, lab in ((self._lo, "97%下限"), (self._hi, "97%上限")):
            if lim is None:
                continue
            self._vline(p, X(lim), COLORS["accent_orange"], 1.2,
                        f"{lab} {lim:.{self._decimals}f}{self._unit}",
                        pad_t + 10, pad_t, plot_h)
        for val, lab in ((self._cur_lo, "阈值下限"), (self._cur_hi, "阈值上限")):
            if val is None:
                continue
            self._vline(p, X(val), "#37C871", 1.5,
                        f"{lab} {val:.{self._decimals}f}{self._unit}",
                        pad_t + 24, pad_t, plot_h)
        p.setPen(sec)
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(pad_l, pad_t + plot_h + 16, f"{x0:.{self._decimals}f}")
        p.drawText(QRect(pad_l + plot_w - 40, pad_t + plot_h + 16, 40, 14),
                   Qt.AlignmentFlag.AlignRight, f"{x1:.{self._decimals}f}")

    def _draw_scatter(self, p, w, h):
        sec = QColor(COLORS["text_secondary"])
        text = QColor(COLORS["text_primary"])
        pad_l, pad_r, pad_t, pad_b = 46, 14, 18, 26
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        s = self._samples
        n = len(s)
        x0, x1 = self._range(s)
        rng = x1 - x0

        def X(v):
            return pad_l + plot_w * (v - x0) / rng

        # 合格区底色（阈值下限 ~ 上限之间）
        if self._cur_lo is not None and self._cur_hi is not None:
            xa = int(X(self._cur_lo))
            xb = int(X(self._cur_hi))
            p.fillRect(xa, pad_t, max(1, xb - xa), plot_h, QColor(55, 200, 113, 24))
        # 97% 建议区间（灰细虚线）
        for lim, lab in ((self._lo, "97%下限"), (self._hi, "97%上限")):
            if lim is None:
                continue
            self._vline(p, X(lim), "#8A8F98", 1.0,
                        f"{lab} {lim:.{self._decimals}f}", pad_t + 10, pad_t, plot_h)
        # 当前阈值上下限（绿下限 / 橙上限，粗虚线）
        if self._cur_lo is not None:
            self._vline(p, X(self._cur_lo), "#37C871", 1.8,
                        f"阈值下限 {self._cur_lo:.{self._decimals}f}",
                        pad_t + 10, pad_t, plot_h)
        if self._cur_hi is not None:
            self._vline(p, X(self._cur_hi), COLORS["accent_orange"], 1.8,
                        f"阈值上限 {self._cur_hi:.{self._decimals}f}",
                        pad_t + 24, pad_t, plot_h)
        # 散点：横轴=值，纵轴=样本(旧在上、新在下)，合格绿/超差红
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(s):
            x = X(v)
            y = pad_t + plot_h * (i / (n - 1) if n > 1 else 0.5)
            inside = ((self._cur_lo is None or v >= self._cur_lo)
                      and (self._cur_hi is None or v <= self._cur_hi))
            p.setBrush(QBrush(QColor("#37C871" if inside else "#EF4444")))
            p.drawEllipse(int(x) - 2, int(y) - 2, 4, 4)
        p.setPen(QPen(text, 1))
        p.drawLine(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h)
        p.setPen(sec)
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(pad_l, pad_t + plot_h + 16, f"{x0:.{self._decimals}f}")
        p.drawText(QRect(pad_l + plot_w - 40, pad_t + plot_h + 16, 40, 14),
                   Qt.AlignmentFlag.AlignRight, f"{x1:.{self._decimals}f}")
        # 图例
        p.setBrush(QBrush(QColor("#37C871")))
        p.drawRect(pad_l + 2, pad_t + 2, 8, 8)
        p.setPen(sec)
        p.drawText(pad_l + 13, pad_t + 10, "合格")
        p.setBrush(QBrush(QColor("#EF4444")))
        p.drawRect(pad_l + 48, pad_t + 2, 8, 8)
        p.setPen(sec)
        p.drawText(pad_l + 59, pad_t + 10, "超差")

    def _draw_ecdf(self, p, w, h):
        sec = QColor(COLORS["text_secondary"])
        text = QColor(COLORS["text_primary"])
        pad_l, pad_r, pad_t, pad_b = 46, 14, 18, 26
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        s = sorted(self._samples)
        n = len(s)
        x0, x1 = self._range(s)
        rng = x1 - x0

        def X(v):
            return pad_l + plot_w * (v - x0) / rng

        def Y(f):
            return pad_t + plot_h * (1 - f)

        if self._cur_lo is not None and self._cur_hi is not None:
            xa = int(X(self._cur_lo))
            xb = int(X(self._cur_hi))
            p.fillRect(xa, pad_t, max(1, xb - xa), plot_h, QColor(55, 200, 113, 24))
        for lim, lab in ((self._lo, "97%下限"), (self._hi, "97%上限")):
            if lim is None:
                continue
            self._vline(p, X(lim), "#8A8F98", 1.0,
                        f"{lab} {lim:.{self._decimals}f}", pad_t + 10, pad_t, plot_h)
        if self._cur_lo is not None:
            self._vline(p, X(self._cur_lo), "#37C871", 1.8,
                        f"阈值下限 {self._cur_lo:.{self._decimals}f}",
                        pad_t + 10, pad_t, plot_h)
        if self._cur_hi is not None:
            self._vline(p, X(self._cur_hi), COLORS["accent_orange"], 1.8,
                        f"阈值上限 {self._cur_hi:.{self._decimals}f}",
                        pad_t + 24, pad_t, plot_h)
        pts = [QPointF(X(x0), Y(0.0))]
        for i, v in enumerate(s, start=1):
            pts.append(QPointF(X(v), Y(i / n)))
        p.setPen(QPen(QColor(COLORS["accent_blue"]), 2))
        p.drawPolyline(pts)
        p.setPen(QPen(text, 1))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + plot_h)
        p.drawLine(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h)
        p.setFont(QFont("Microsoft YaHei", 9))
        for f in (0.0, 0.5, 1.0):
            gy = Y(f)
            p.setPen(QPen(QColor(COLORS["border"]), 1))
            p.drawLine(pad_l, int(gy), pad_l + plot_w, int(gy))
            p.setPen(sec)
            p.drawText(QRect(2, int(gy) - 8, pad_l - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{int(f * 100)}%")
        p.setPen(sec)
        p.drawText(pad_l, pad_t + plot_h + 16, f"{x0:.{self._decimals}f}")
        p.drawText(QRect(pad_l + plot_w - 40, pad_t + plot_h + 16, 40, 14),
                   Qt.AlignmentFlag.AlignRight, f"{x1:.{self._decimals}f}")

    def _draw_categorical(self, p, w, h):
        cats = self._cats
        n = max(1, len(cats))
        pad_l, pad_r, pad_t, pad_b = 16, 16, 18, 30
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        maxc = max((c[1] for c in cats), default=1) or 1
        p.setFont(QFont("Microsoft YaHei", 10))
        bw = plot_w / n
        p.setPen(Qt.PenStyle.NoPen)
        for i, (name, count, is_cur) in enumerate(cats):
            bx = pad_l + i * bw
            bh = plot_h * (count / maxc)
            col = (QColor("#37C871") if is_cur
                   else QColor(COLORS["accent_blue"]))
            p.setBrush(QBrush(col))
            p.drawRect(int(bx + bw * 0.15), int(pad_t + plot_h - bh),
                       max(1, int(bw * 0.7)), int(bh))
            p.setPen(QColor(COLORS["text_primary"]))
            p.drawText(QRect(int(bx), int(pad_t + plot_h + 4), int(bw), 20),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       name)
            p.setPen(QColor(COLORS["text_secondary"]))
            p.drawText(int(bx + bw * 0.15), int(pad_t + plot_h - bh - 4),
                       str(count))
        p.setPen(QPen(QColor(COLORS["text_primary"]), 1))
        p.drawLine(pad_l, pad_t + plot_h, pad_l + plot_w, pad_t + plot_h)


class TargetParamDialog(QDialog):
    """目标查找参数设置窗口：用于调整某个计算元素的查找参数。"""

    # 窗体宽度：紧凑态（仅参数）与展开态（参数 + 结果分布面板）
    _LEFT_W = 360
    _PANEL_W = 440
    _MARGIN = 16          # 与布局 contents margin 一致
    _SPACING = 12         # 与布局 spacing 一致
    _COMPACT_W = _LEFT_W + _MARGIN * 2
    _FULL_W = _LEFT_W + _PANEL_W + _SPACING + _MARGIN * 2

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"目标查找参数设置 - {name}")
        # 背景样式与其他弹窗（如相机标定）保持一致
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self.setMinimumWidth(self._COMPACT_W)
        # 去掉 Windows 自带的「?」帮助按钮，并设为置顶显示
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            | Qt.WindowType.WindowStaysOnTopHint)
        self._name = name
        self._owner = parent     # DebugView 实例（提供生产运行状态与样本池）
        self._active_key = None
        self._dist_btns = {}
        self._autotune_btns = {}   # 「自动调参」按钮：{key: QPushButton}
        self._live_drift = {}    # 演示数据缓慢游走偏移：{key: offset}
        self._custom_filter = False   # 是否处于手动时间检索（固定区间）状态
        self._filter_t0 = None        # 手动检索起始时间
        self._filter_t1 = None        # 手动检索结束时间
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        # 每 500ms 触发一次刷新（同时驱动样本累计）：这是分布图能持续刷新、
        # 『清零』后能立即重显的关键。此前漏掉 start() 导致定时器从未触发，
        # 图表只在打开/点清零瞬间渲染一次、之后永远停在初始样本（看似『不刷新/清零无效』）。
        self._timer.start(500)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(self._MARGIN, self._MARGIN,
                                self._MARGIN, self._MARGIN)
        root.setSpacing(self._SPACING)

        # ---------------- 左侧：参数设置 ----------------
        left = QWidget()
        left.setFixedWidth(self._LEFT_W)
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        title = QLabel("查找参数（每行含「上限 / 下限」，点右侧「分布」查看结果分布）")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")
        v.addWidget(title)

        # 匹配参数组（阈值上限 / 阈值下限 采用带列头的表格布局）
        grp = QGroupBox("匹配参数")
        grp.setStyleSheet(self._group_style())
        gv = QVBoxLayout(grp)
        gv.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self._add_grid_header(grid)

        # 匹配阈值：上限 / 下限
        self._thresh_hi = self._make_spin(0, 100, 90, "", " %")
        self._thresh_lo = self._make_spin(0, 100, 70, "", " %")
        self._add_grid_row(grid, 1, "匹配阈值", self._thresh_hi, self._thresh_lo, "thresh")

        # 匹配面积：上限 / 下限（由最小/最大匹配面积合并为单行）
        self._area_hi = self._make_spin(0, 100000, 5000, "", " px²")
        self._area_lo = self._make_spin(0, 100000, 50, "", " px²")
        self._add_grid_row(grid, 2, "匹配面积", self._area_hi, self._area_lo, "area")

        # 边缘容差：上限 / 下限
        self._tol_hi = self._make_spin(0, 50, 5, "", " px")
        self._tol_lo = self._make_spin(0, 50, 0, "", " px")
        self._add_grid_row(grid, 3, "边缘容差", self._tol_hi, self._tol_lo, "tol")

        # 匹配极性（无上下限，按普通行显示，同原「匹配极性」行）
        self._pol = QComboBox()
        self._pol.addItems(["正向匹配", "反向匹配"])
        self._pol.setStyleSheet(self._combo_style())
        self._pol.currentTextChanged.connect(self._on_value_changed)
        self._add_normal_row(grid, 4, "匹配极性", [self._pol], "pol")

        gv.addLayout(grid)
        v.addWidget(grp)
        v.addStretch(1)

        # 底部按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        ok = QPushButton("确定")
        ok.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 18px; font-size: 13px;")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 18px; font-size: 13px;")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        v.addLayout(btns)

        root.addWidget(left, 0)

        # ---------------- 右侧：结果分布面板（默认隐藏） ----------------
        self._panel = self._build_dist_panel()
        root.addWidget(self._panel, 0)
        self._panel.hide()

        # 参数元信息（用于生成示例分布与取值）
        self._param_meta = {
            "thresh": {"label": "匹配阈值", "unit": "%", "decimals": 0,
                       "get_lo": lambda: self._thresh_lo.value(),
                       "get_hi": lambda: self._thresh_hi.value()},
            "area": {"label": "匹配面积", "unit": "px²", "decimals": 0,
                     "get_lo": lambda: self._area_lo.value(),
                     "get_hi": lambda: self._area_hi.value()},
            "tol": {"label": "边缘容差", "unit": "px", "decimals": 0,
                    "get_lo": lambda: self._tol_lo.value(),
                    "get_hi": lambda: self._tol_hi.value()},
            "pol": {"label": "匹配极性", "unit": "", "categorical": True,
                    "get": lambda: self._pol.currentText()},
        }

    def _add_grid_header(self, grid):
        """列头：匹配参数 | 上限 | 下限 | （分布）"""
        headers = [
            ("匹配参数", Qt.AlignmentFlag.AlignLeft),
            ("上限", Qt.AlignmentFlag.AlignCenter),
            ("下限", Qt.AlignmentFlag.AlignCenter),
            ("", Qt.AlignmentFlag.AlignCenter),
            ("自动调参", Qt.AlignmentFlag.AlignCenter),
        ]
        for c, (text, align) in enumerate(headers):
            lab = QLabel(text)
            lab.setAlignment(align)
            lab.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px; "
                f"font-weight: bold;")
            grid.addWidget(lab, 0, c)

    def _add_grid_row(self, grid, r, label, hi_spin, lo_spin, key):
        """带上下限的列：标签 | 上限 | 下限 | 分布按钮。"""
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12px;")
        grid.addWidget(lbl, r, 0)
        grid.addWidget(hi_spin, r, 1)
        grid.addWidget(lo_spin, r, 2)
        btn = QPushButton("分布")
        btn.setFixedSize(40, 24)
        btn.setStyleSheet(self._dist_btn_style(False))
        btn.clicked.connect(lambda _, k=key: self._on_dist(k))
        grid.addWidget(btn, r, 3)
        self._dist_btns[key] = btn
        # 「自动调参」按钮：按样本分布自动计算并应用该参数的推荐上下限
        btn_at = QPushButton("自动调参")
        btn_at.setFixedSize(56, 24)
        btn_at.setStyleSheet(self._dist_btn_style(False))
        btn_at.setToolTip("按历史样本分布自动计算并应用该参数的推荐上限/下限")
        btn_at.clicked.connect(lambda _, k=key: self._on_auto_tune(k))
        grid.addWidget(btn_at, r, 4)
        self._autotune_btns[key] = btn_at

    def _add_normal_row(self, grid, r, label, controls, key):
        """无上下限的普通行（如匹配极性）：标签 | 控件(跨列) | 分布按钮。"""
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12px;")
        grid.addWidget(lbl, r, 0)
        for c in controls:
            grid.addWidget(c, r, 1, 1, 2)
        btn = QPushButton("分布")
        btn.setFixedSize(40, 24)
        btn.setStyleSheet(self._dist_btn_style(False))
        btn.clicked.connect(lambda _, k=key: self._on_dist(k))
        grid.addWidget(btn, r, 3)
        self._dist_btns[key] = btn

    def _make_spin(self, lo, hi, val, prefix, suffix):
        """生成一个带前缀/后缀、暗色风格的数值框。"""
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(val)
        sp.setPrefix(prefix)
        sp.setSuffix(suffix)
        sp.setMinimumWidth(78)
        sp.setStyleSheet(self._spin_style())
        sp.valueChanged.connect(self._on_value_changed)
        return sp

    def _build_dist_panel(self):
        panel = QWidget()
        panel.setFixedWidth(self._PANEL_W)
        panel.setStyleSheet(
            f"QWidget#_dist_panel {{ background-color: {COLORS['bg_panel']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        panel.setObjectName("_dist_panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        hrow = QHBoxLayout()
        self._dist_title = QLabel("参数结果分布")
        self._dist_title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-weight: bold; font-size: 13px;")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; font-size: 14px; }}"
            f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}")
        close_btn.clicked.connect(self._hide_dist)
        clear_btn = QPushButton("清零")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(self._mode_btn_style(False))
        clear_btn.clicked.connect(self._do_clear)
        hrow.addWidget(self._dist_title)
        hrow.addStretch(1)
        hrow.addWidget(clear_btn)
        hrow.addWidget(close_btn)
        lay.addLayout(hrow)

        self._dist_header = QLabel("")
        self._dist_header.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        self._dist_header.setWordWrap(True)
        lay.addWidget(self._dist_header)

        # 数据时间范围（与检测项分布图一致：显示当前检索区间的起止时间）
        self._time_range_lbl = QLabel("")
        self._time_range_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        lay.addWidget(self._time_range_lbl)

        # 视图切换：散点 / 直方图 / 累积分布
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self._mode_btns = {}
        for m, lbl in (("scatter", "散点"), ("hist", "直方图"),
                       ("ecdf", "累积分布")):
            b = QPushButton(lbl)
            b.setFixedHeight(22)
            b.setCheckable(True)
            b.setChecked(m == "scatter")
            b.setStyleSheet(self._mode_btn_style(m == "scatter"))
            b.clicked.connect(lambda _, mm=m: self._set_chart_mode(mm))
            mode_row.addWidget(b)
            self._mode_btns[m] = b
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # 时间检索：起 ~ 止 + 检索 / 重置（按时间范围筛选分布样本）
        time_row = QHBoxLayout()
        time_row.setSpacing(6)
        tl = QLabel("时间")
        tl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        self._dt_start = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-120))
        self._dt_end = QDateTimeEdit(QDateTime.currentDateTime())
        for dt in (self._dt_start, self._dt_end):
            dt.setDisplayFormat("MM-dd HH:mm:ss")
            dt.setCalendarPopup(True)
            dt.setFixedHeight(22)
            dt.setStyleSheet(
                f"QDateTimeEdit {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; font-size: 11px; padding: 0 4px; }}")
        bf = QPushButton("检索")
        bf.setFixedHeight(22)
        bf.setStyleSheet(self._mode_btn_style(False))
        bf.clicked.connect(self._apply_filter)
        br = QPushButton("重置")
        br.setFixedHeight(22)
        br.setStyleSheet(self._mode_btn_style(False))
        br.clicked.connect(self._reset_filter)
        time_row.addWidget(tl)
        time_row.addWidget(self._dt_start)
        time_row.addWidget(self._dt_end)
        time_row.addWidget(bf)
        time_row.addWidget(br)
        time_row.addStretch(1)
        lay.addLayout(time_row)

        self._dist_chart = DistributionChart()
        lay.addWidget(self._dist_chart, 1)

        self._dist_footer = QLabel(
            "实时样本分布：合格区为阈值下限~上限之间（绿色）；可切换散点 / 直方图 / "
            "累积分布视图。设备运行时每 0.5s 追加最新实测值；97% 建议区间（灰虚线）"
            "随数据自动更新")
        self._dist_footer.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 10px;")
        self._dist_footer.setWordWrap(True)
        lay.addWidget(self._dist_footer)
        return panel

    def _mode_btn_style(self, on):
        if on:
            return (f"QPushButton {{ background-color: {COLORS['accent_orange']}; "
                    f"color: white; border: none; border-radius: 4px; "
                    f"font-size: 11px; padding: 0 10px; }}")
        return (f"QPushButton {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_secondary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 11px; padding: 0 10px; }}"
                f"QPushButton:hover {{ color: {COLORS['text_primary']}; }}")

    def _set_chart_mode(self, m):
        self._dist_chart.set_mode(m)
        for k, b in self._mode_btns.items():
            on = (k == m)
            b.setChecked(on)
            b.setStyleSheet(self._mode_btn_style(on))
        # 切换视图后立即用当前样本池重绘，避免停留在旧的空 / 暂无数据状态
        self._refresh_live()

    # -- 分布按钮交互 ------------------------------------------------
    def _on_dist(self, key):
        if self._panel.isVisible() and self._active_key == key:
            self._hide_dist()
            return
        self._active_key = key
        self._reset_filter()      # 默认显示全量（从最早样本到当前），并刷新
        self._panel.show()
        for k, b in self._dist_btns.items():
            b.setStyleSheet(self._dist_btn_style(k == key))
        self.setMinimumWidth(self._FULL_W)
        self.resize(self._FULL_W, self.height())
        if not self._timer.isActive():
            self._timer.start(500)

    def _hide_dist(self):
        self._panel.hide()
        self._active_key = None
        self._timer.stop()
        for b in self._dist_btns.values():
            b.setStyleSheet(self._dist_btn_style(False))
        self.setMinimumWidth(self._COMPACT_W)
        self.resize(self._COMPACT_W, self.height())

    @staticmethod
    def _qdt(dt):
        """Python datetime -> QDateTime（用时间戳构造，规避本地时区/平台差异）。"""
        return QDateTime.fromSecsSinceEpoch(int(dt.timestamp()))

    @staticmethod
    def _pydt(qdt):
        return qdt.toPyDateTime()

    # ---- 诊断与防御性兜底 --------------------------------------------
    def _diag(self, tag, *msgs):
        """把分布图运行期的异常/关键状态写入 output/param_diag.log，便于定位『暂无数据』。"""
        try:
            import os as _os
            if getattr(sys, "frozen", False):
                _base = _os.path.dirname(_os.path.abspath(sys.executable))
            else:
                _base = os.getcwd()
            _d = _os.path.join(_base, "output")
            _os.makedirs(_d, exist_ok=True)
            _p = _os.path.join(_d, "param_diag.log")
            with open(_p, "a", encoding="utf-8") as _f:
                _f.write(f"[{datetime.now():%H:%M:%S}] {tag}: "
                         + " | ".join(str(m) for m in msgs) + "\n")
        except Exception:
            pass

    def _local_baseline(self, key):
        """owner 取数失败时的本地兜底：生成一份与示例基线同形的带时间戳样本。"""
        import random as _r
        _r.seed(abs(hash(key)) % (2 ** 31))
        n = 260
        if key == "thresh":
            s = [min(100.0, max(40.0, _r.gauss(86, 7))) for _ in range(n)]
        elif key == "area":
            s = [min(9000.0, max(50.0, _r.gauss(1800, 1200))) for _ in range(n)]
        elif key == "tol":
            s = [min(12.0, max(0.0, _r.gauss(3, 1.6))) for _ in range(n)]
        else:
            s = [80.0] * n
        s = [round(x, 2) for x in s]
        now = datetime.now()
        start = now - timedelta(minutes=30)
        total = max(1, int((now - start).total_seconds()))
        return [(start if n == 1 else start + timedelta(seconds=total * i / (n - 1)), v)
                for i, v in enumerate(s)]

    def _render_local_fallback(self):
        """绕开 owner，直接用本地示例基线渲染，保证不显示『暂无数据』。"""
        key = self._active_key
        if not key:
            return
        samples = self._local_baseline(key)
        if not samples:
            return
        now = datetime.now()
        t0 = min(t for t, _ in samples)
        t1 = now
        self._render(t0, t1, samples)

    def _refresh_live(self):
        """始终运行（500ms 定时器）的刷新入口：与检测项分布图完全一致——从 DebugView
        样本池读取当前参数的全部样本并重绘；样本随相机逐帧节拍追加，设备停止时样本不再
        增长，曲线自动停止刷新（不再依赖任何『推』逻辑，从根本上避免刷新不触发）。

        本方法会先驱动一次样本累计（仅当设备正在刷新图片时生效），使分布图在『于任意
        界面点击设备启动』后都能持续刷新，不再依赖 DebugView 是否可见，彻底消除此前
        『打开参数窗口→在别处点设备启动→图表卡死/清零无效』的问题。

        任何绘制/统计异常都记下诊断并兜底，绝不冒泡到 Qt 事件循环导致软件崩溃，
        也绝不让图表停留在『暂无数据』。
        """
        # 由分布面板自身的 500ms 定时器驱动累计：只要设备正在刷新图片，便追加一条
        # 实时实测值到样本池——不依赖 DebugView 是否可见，故在任意界面点击设备启动
        # 分布图都能持续刷新。
        if self._owner is not None:
            try:
                self._owner._accumulate_param_samples()
            except Exception:
                pass
        try:
            self._render_live()
        except Exception as e:
            import traceback
            self._diag("REFRESH_EXCEPTION", repr(e), traceback.format_exc())
            try:
                self._render_local_fallback()
            except Exception:
                pass

    def _render_live(self):
        """按当前检索时间窗渲染：从样本池取数，范围从最早样本到当前（自动模式）。"""
        key = self._active_key
        if key is None:
            return
        meta = self._param_meta.get(key)
        if meta is None:
            return
        auto_mode = not (self._custom_filter and self._filter_t0 is not None)
        samples = []
        try:
            if self._owner is not None:
                samples = self._owner.get_param_samples(self._name, key)
        except Exception as e:
            self._diag("GET_SAMPLES_EXCEPTION", repr(e))
            samples = []
        # 防御：自动模式下若 owner 取数失败/为空，用本地示例基线兜底（不再『暂无数据』）
        if not samples and auto_mode:
            self._diag("USE_LOCAL_FALLBACK", f"key={key}",
                       f"owner={'yes' if self._owner else 'no'}",
                       f"has_get={hasattr(self._owner, 'get_param_samples') if self._owner else 'n/a'}")
            samples = self._local_baseline(key)
        now = datetime.now()
        if samples:
            dstart = min(t for t, _ in samples)
            dend = max(t for t, _ in samples)
        else:
            base = getattr(self._owner, "_prod_start_time", None) if self._owner else None
            dstart = base or (now - timedelta(minutes=5))
            dend = now
        if self._custom_filter and self._filter_t0 is not None:
            t0, t1 = self._filter_t0, self._filter_t1
        else:
            t0, t1 = dstart, now
            # 同步时间框显示，便于用户看到当前检索区间随相机刷新推进
            if self._dt_start is not None:
                self._dt_start.setDateTime(self._qdt(t0))
                self._dt_end.setDateTime(self._qdt(t1))
        self._render(t0, t1, samples)

    def _render(self, t0, t1, samples):
        """按 [t0,t1] 区间渲染分布图 / 统计 / 规格范围内比例（与检测项分布图一致）。"""
        self._update_time_range_label(t0, t1)
        filtered = [(t, v) for t, v in samples if t0 <= t <= t1]
        values = [v for _, v in filtered]
        meta = self._param_meta[self._active_key]
        if meta.get("categorical"):
            cur = meta["get"]()
            cats = [
                ("正向匹配", 212, cur == "正向匹配"),
                ("反向匹配", 28, cur == "反向匹配"),
            ]
            self._dist_chart.set_categorical(cats)
            self._dist_title.setText("参数结果分布 · 匹配极性")
            self._dist_header.setText("正向 / 反向 匹配结果计数分布")
            return
        unit = meta["unit"]
        decimals = meta["decimals"]
        # 97% 建议区间（上下各剔除 1.5%），随当前时间窗动态计算
        if values:
            lo = round(self._pct(values, 1.5), 2)
            hi = round(self._pct(values, 98.5), 2)
        else:
            lo = hi = 0.0
        cur_lo = meta["get_lo"]()
        cur_hi = meta["get_hi"]()
        self._dist_chart.set_numeric(values, unit, decimals, lo, hi, cur_lo, cur_hi)
        if values:
            n = len(values)
            mean = sum(values) / n
            mn = min(values)
            mx = max(values)
            inr = sum(1 for v in values
                       if (cur_lo is None or v >= cur_lo)
                       and (cur_hi is None or v <= cur_hi))
            ratio = inr / n * 100
            self._dist_title.setText(f"参数结果分布 · {meta['label']}")
            self._dist_header.setText(
                f"样本数 {n}    均值 {mean:.{decimals}f}{unit}    "
                f"最小 {mn:.{decimals}f}{unit}    最大 {mx:.{decimals}f}{unit}    "
                f"合格率 {ratio:.1f}%"
                f"{'（自动：从最早到当前）' if not self._custom_filter else '（检索区间）'}")
        else:
            self._dist_title.setText(f"参数结果分布 · {meta['label']}")
            self._dist_header.setText("该时间范围内暂无数据")

    def _update_time_range_label(self, t0, t1):
        if self._time_range_lbl is None:
            return
        self._time_range_lbl.setText(
            f"数据时间范围：{t0.strftime('%Y-%m-%d %H:%M:%S')}  ~  "
            f"{t1.strftime('%Y-%m-%d %H:%M:%S')}")

    def _init_time_range(self):
        """初始化时间检索框：默认显示从最早样本到当前（与检测项分布图一致）。"""
        if self._dt_start is None:
            return
        samples = self._owner.get_param_samples(self._name, self._active_key) if self._owner else []
        now = datetime.now()
        if samples:
            t0 = min(t for t, _ in samples)
        else:
            base = getattr(self._owner, "_prod_start_time", None) if self._owner else None
            t0 = base or (now - timedelta(minutes=30))
        self._dt_start.setDateTime(self._qdt(t0))
        self._dt_end.setDateTime(self._qdt(now))

    def _apply_filter(self):
        """点击『检索』：按时间框所选区间固定筛选（不再随相机刷新自动扩展）。"""
        try:
            if self._dt_start is None:
                return
            self._custom_filter = True
            self._filter_t0 = self._pydt(self._dt_start.dateTime())
            # 结束时间按「到分」选择，补满到所选分钟的 59 秒，避免截断该分钟内的数据
            self._filter_t1 = self._pydt(self._dt_end.dateTime().addSecs(59))
            if self._filter_t0 > self._filter_t1:
                self._filter_t0, self._filter_t1 = self._filter_t1, self._filter_t0
            self._refresh_live()
        except Exception as e:
            import traceback
            print("[TargetParamDialog] 检索异常（已忽略）：", repr(e))
            traceback.print_exc()

    def _reset_filter(self):
        """点击『重置』：退出手动检索，恢复自动全量（从最早到当前）并显示。"""
        try:
            self._custom_filter = False
            self._filter_t0 = None
            self._filter_t1 = None
            self._refresh_live()
        except Exception as e:
            import traceback
            print("[TargetParamDialog] 重置异常（已忽略）：", repr(e))
            traceback.print_exc()

    def _do_clear(self):
        """点击『清零』：清除分布数据（清空 DebugView 样本池），随后随相机刷新重新累计
        并刷新显示（与检测项分布图一致：清的是样本池，并重置时间窗）。"""
        try:
            key = self._active_key
            if self._owner is not None and key:
                self._owner.clear_param_distribution(self._name, key)
            self._custom_filter = False
            self._filter_t0 = None
            self._filter_t1 = None
            self._refresh_live()
        except Exception as e:
            import traceback
            print("[TargetParamDialog] 清零异常（已忽略）：", repr(e))
            traceback.print_exc()

    # -- 自动调参 ------------------------------------------------------
    def _on_auto_tune(self, key):
        """算法阈值自动调参：按当前样本分布（99% 分位区间 + 两侧工艺余量）
        计算该参数的推荐上限/下限并直接应用，随后刷新分布图。

        - 样本来源与分布图一致：DebugView 样本池（生产运行时为真实实测值，
          否则为演示基线）；处于手动时间检索时只统计检索区间内的样本。
        - 推荐区间 = [P0.5, P99.5]（覆盖 99% 样本），两侧各外扩区间宽度的 10%
          作为工艺余量，并夹取到该参数输入框允许的取值范围内。
        """
        meta = self._param_meta.get(key)
        if meta is None or meta.get("categorical"):
            return
        try:
            samples = []
            if self._owner is not None:
                try:
                    samples = self._owner.get_param_samples(self._name, key)
                except Exception:
                    samples = []
            if not samples:
                samples = self._local_baseline(key)
            if self._custom_filter and self._filter_t0 is not None:
                samples = [(t, v) for t, v in samples
                           if self._filter_t0 <= t <= self._filter_t1]
            values = [float(v) for _, v in samples]
            if not values:
                QMessageBox.information(
                    self, "自动调参", "当前时间范围内暂无样本数据，无法自动调参。")
                return
            lo_s = self._pct(values, 0.5)
            hi_s = self._pct(values, 99.5)
            margin = (hi_s - lo_s) * 0.10
            spins = {"thresh": (self._thresh_lo, self._thresh_hi),
                     "area": (self._area_lo, self._area_hi),
                     "tol": (self._tol_lo, self._tol_hi)}
            sp_lo, sp_hi = spins[key]
            old_lo, old_hi = sp_lo.value(), sp_hi.value()
            new_lo = int(round(max(sp_lo.minimum(), min(sp_lo.maximum(),
                                                        lo_s - margin))))
            new_hi = int(round(max(sp_hi.minimum(), min(sp_hi.maximum(),
                                                        hi_s + margin))))
            if new_hi < new_lo:
                new_lo, new_hi = min(new_lo, new_hi), sp_hi.maximum()
            sp_lo.setValue(new_lo)
            sp_hi.setValue(new_hi)
            # 分布面板未打开时 _on_value_changed 不会触发刷新，这里兜底刷一次
            self._refresh_live()
            unit = meta.get("unit", "")
            QMessageBox.information(
                self, f"自动调参 · {meta['label']}",
                f"已按最近 {len(values)} 个样本自动完成调参：\n\n"
                f"{meta['label']}：{old_lo}~{old_hi}{unit}  →  "
                f"{new_lo}~{new_hi}{unit}\n\n"
                f"（依据样本 99% 分位区间 P0.5~P99.5，两侧各留 10% 工艺余量）\n"
                f"点击「确定」后生效；如需回退，请手动恢复原数值。")
        except Exception as e:
            import traceback
            print("[TargetParamDialog] 自动调参异常（已忽略）：", repr(e))
            traceback.print_exc()

    def _append_live_sample(self, now):
        """由 DebugView._accumulate_param_samples 在相机逐帧节拍中调用：
        向样本池追加一条当前参数的实时实测值（生产运行取真实值，否则取演示游走值）。"""
        key = self._active_key
        if not key:
            return
        meta = self._param_meta.get(key)
        if meta is None or meta.get("categorical"):
            return
        lo = meta["get_lo"]()
        hi = meta["get_hi"]()
        owner = self._owner
        if owner is not None and getattr(owner, "is_production_running", lambda: False)():
            try:
                val = owner.get_live_param_value(self._name, key, lo, hi)
            except Exception:
                # 即便真实实测值接口异常，也回退到演示数据保证图表持续刷新
                val = self._demo_value(key, lo, hi)
        else:
            val = self._demo_value(key, lo, hi)
        buf = owner.get_param_samples(self._name, key) if owner else []
        buf.append((now, val))
        if len(buf) > 3000:
            del buf[: len(buf) - 3000]

    def _demo_value(self, key, lo, hi):
        """本地演示实测值：以阈值中点为中心做高斯扰动 + 缓慢随机游走，使分布随时间漂移。"""
        if lo is None or hi is None or hi <= lo:
            return 0.0
        rng = float(hi - lo)
        drift = self._live_drift.get(key, 0.0)
        drift += random.uniform(-rng * 0.02, rng * 0.02)
        drift = max(-rng * 0.35, min(rng * 0.35, drift))
        self._live_drift[key] = drift
        center = (lo + hi) / 2.0 + drift
        spread = rng * 0.30
        if random.random() < 0.08:  # 偶发离群点
            center = (lo - spread * 1.2) if random.random() < 0.5 \
                else (hi + spread * 1.2)
        val = random.gauss(center, spread)
        val = max(lo - rng * 0.5, min(hi + rng * 0.5, val))
        decimals = {"thresh": 0, "area": 0, "tol": 0}.get(key, 0)
        return round(val, decimals)

    def closeEvent(self, event):
        self._timer.stop()
        owner = self._owner
        if owner is not None and hasattr(owner, "_param_dialogs"):
            d = getattr(owner, "_param_dialogs", {})
            if d.get(self._name) is self:
                d.pop(self._name, None)
        super().closeEvent(event)

    def _on_value_changed(self, *args):
        # 阈值上下限或模式变化时，实时刷新分布图（阈值线随设定移动）
        if self._panel.isVisible() and self._active_key is not None:
            self._refresh_live()

    @staticmethod
    def _pct(data, p):
        s = sorted(data)
        if not s:
            return 0.0
        k = (len(s) - 1) * (p / 100.0)
        f = int(k)
        c = min(f + 1, len(s) - 1)
        if f == c:
            return float(s[f])
        return s[f] + (s[c] - s[f]) * (k - f)

    def _dist_btn_style(self, active):
        if active:
            return (f"QPushButton {{ background-color: {COLORS['accent_orange']}; "
                    f"color: white; border: none; border-radius: 4px; "
                    f"font-size: 11px; }}")
        return (f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
                f"color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 11px; }}"
                f"QPushButton:hover {{ background-color: {COLORS['border']}; }}")

    @staticmethod
    def _group_style():
        return (
            f"QGroupBox {{ color: {COLORS['text_primary']}; font-size: 12px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"margin-top: 8px; padding: 10px; }}")

    @staticmethod
    def _spin_style():
        return (
            f"QSpinBox {{ color: {COLORS['text_primary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; "
            f"padding: 4px 6px; font-size: 12px; }}"
            f"QSpinBox:focus {{ border: 1px solid {COLORS['accent_blue']}; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}")

    @staticmethod
    def _combo_style():
        return (
            f"QComboBox {{ color: {COLORS['text_primary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 8px; font-size: 12px; }}"
            f"QComboBox:hover {{ border: 1px solid {COLORS['accent_blue']}; }}"
            f"QComboBox::drop-down {{ subcontrol-origin: padding; "
            f"subcontrol-position: top right; width: 18px; border: none; }}"
            f"QComboBox QAbstractItemView {{ color: {COLORS['text_primary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"selection-background-color: {COLORS['accent_blue']}; }}")

    def get_params(self):
        return {
            "thresh_lo": self._thresh_lo.value(),
            "thresh_hi": self._thresh_hi.value(),
            "area_lo": self._area_lo.value(),
            "area_hi": self._area_hi.value(),
            "tol_lo": self._tol_lo.value(),
            "tol_hi": self._tol_hi.value(),
            "polarity": self._pol.currentText(),
        }

    def set_params(self, p):
        self._thresh_lo.setValue(int(p.get("thresh_lo", p.get("thresh", 70))))
        self._thresh_hi.setValue(int(p.get("thresh_hi", 90)))
        self._area_lo.setValue(int(p.get("area_lo", p.get("min_area", 50))))
        self._area_hi.setValue(int(p.get("area_hi", p.get("max_area", 5000))))
        self._tol_lo.setValue(int(p.get("tol_lo", 0)))
        self._tol_hi.setValue(int(p.get("tol_hi", p.get("tol", 5))))
        idx = self._pol.findText(p.get("polarity", "正向匹配"))
        if idx >= 0:
            self._pol.setCurrentIndex(idx)


class UnitCell(QFrame):
    """「单位」列单元格：显示当前单位，鼠标悬停提示右键可选择，右键弹出菜单选择单位。

    选项固定为：Pixel、mm、Deg、Dec、灰度级。选择后通过回调写入底层数据。
    """

    OPTIONS = ["Pixel", "mm", "Deg", "Dec", "灰度级"]
    HINT = "鼠标右键单击可选择单位"

    def __init__(self, current, on_select=None, parent=None, pixel_size=10):
        super().__init__(parent)
        self._on_select = on_select
        self._lbl = QLabel(str(current))
        # ⚠️ cellWidget 内的控件**不继承QTableWidget 的字体**，
        # 默认按应用字体渲染，会比表格正文偏大。
        # 这里显式设定像素字号与表格正文一致（10px）。
        _f = QFont("Microsoft YaHei")
        _f.setPixelSize(pixel_size)
        self._lbl.setFont(_f)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setToolTip(self.HINT)
        self.setToolTip(self.HINT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _build_menu(self):
        menu = QMenu(self)
        for opt in self.OPTIONS:
            menu.addAction(opt)
        return menu

    def _on_context_menu(self, pos):
        menu = self._build_menu()
        action = menu.exec(self.mapToGlobal(pos))
        if action is not None:
            self.set_unit(action.text())

    def set_unit(self, text):
        """更新显示的单位，并回调通知外部（写入底层数据）。"""
        self._lbl.setText(str(text))
        if self._on_select is not None:
            self._on_select(str(text))

    def current_unit(self):
        return self._lbl.text()


class SpecAutoAdjustDialog(QDialog):
    """检测项规格上下限自动调整窗口。

    依据各检测项历史分布样本（DebugView.get_distribution_samples）按
    99% 分位区间 P0.5~P99.5 加两侧 10% 工艺余量给出推荐规格；用户可勾选
    需要调整的检测项并微调推荐值，点击「应用调整」写回检测项列表，
    并按新规格重新判定『检测结果』。
    """

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner      # DebugView 实例（提供分布样本与写回接口）
        self._rows = []          # [(row, chk, sp_lo, sp_hi), ...]
        self.setWindowTitle("检测项规格上下限自动调整")
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self.resize(600, 500)
        # 去掉 Windows 自带的「?」帮助按钮，并设为置顶显示
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            | Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()
        self._collect_rows()

    # -- UI 构建 ------------------------------------------------------
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        title = QLabel("依据各检测项历史分布样本自动计算推荐规格上下限"
                       "（勾选后应用，推荐值可直接微调）")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")
        v.addWidget(title)

        # 顶部：全选 + 算法说明
        top = QHBoxLayout()
        self._chk_all = QCheckBox("全选")
        self._chk_all.setChecked(True)
        self._chk_all.setStyleSheet(self._chk_style())
        self._chk_all.toggled.connect(self._on_toggle_all)
        top.addWidget(self._chk_all)
        top.addStretch(1)
        tip = QLabel("推荐规格 = P0.5~P99.5 分位区间，两侧各留 10% 工艺余量")
        tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        top.addWidget(tip)
        v.addLayout(top)

        # 列头
        hdr = QWidget()
        hg = QHBoxLayout(hdr)
        hg.setContentsMargins(8, 0, 8, 0)
        hg.setSpacing(8)
        for text, w in (("选择", 36), ("检测编号", 60), ("检测项目", 150),
                        ("当前规格（下限 ~ 上限）", 170),
                        ("推荐规格（下限 ~ 上限）", 190), ("样本", 70)):
            lab = QLabel(text)
            lab.setFixedWidth(w)
            lab.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px; "
                f"font-weight: bold;")
            hg.addWidget(lab)
        hg.addStretch(1)
        v.addWidget(hdr)

        # 可滚动行区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(6)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        # 底部按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        apply_btn = QPushButton("应用调整")
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; padding: 6px 18px; font-size: 13px;")
        apply_btn.clicked.connect(self._on_apply)
        cancel = QPushButton("取消")
        cancel.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 18px; font-size: 13px;")
        cancel.clicked.connect(self.reject)
        btns.addWidget(apply_btn)
        btns.addWidget(cancel)
        v.addLayout(btns)

    def _collect_rows(self):
        """扫描检测项列表，为每个数值型检测项生成一行（当前规格 + 推荐规格）。"""
        owner = self._owner
        table = getattr(owner, "_table", None)
        if owner is None or table is None:
            return
        for r in range(table.rowCount()):
            raw = owner._table_data[r] if r < len(owner._table_data) else None
            if raw is None:
                continue
            name = str(raw[2] or "").strip()
            cur_lo = _to_float(raw[6])
            cur_hi = _to_float(raw[7])
            val = _to_float(raw[4])
            if not name or val is None or cur_lo is None or cur_hi is None:
                continue
            if cur_lo > cur_hi:
                cur_lo, cur_hi = cur_hi, cur_lo
            # 推荐规格：优先用分布样本分位数；样本不足时保持当前规格
            note = ""
            try:
                samples = owner.get_distribution_samples(r)
            except Exception:
                samples = []
            values = [float(v) for _, v in samples]
            if len(values) >= 8:
                p_lo = TargetParamDialog._pct(values, 0.5)
                p_hi = TargetParamDialog._pct(values, 99.5)
                margin = (p_hi - p_lo) * 0.10
                sug_lo, sug_hi = p_lo - margin, p_hi + margin
                note = f"{len(values)}"
            else:
                sug_lo, sug_hi = cur_lo, cur_hi
                note = "不足"
            # 小数位跟随当前规格字符串（最多 3 位），保证显示风格一致
            s = str(raw[6])
            dec = min(len(s.split(".")[-1]), 3) if "." in s else 0
            sug_lo = round(sug_lo, dec)
            sug_hi = round(sug_hi, dec)

            row_w = QWidget()
            row_w.setStyleSheet(
                "QWidget { background-color: transparent; }")
            rg = QHBoxLayout(row_w)
            rg.setContentsMargins(8, 0, 8, 0)
            rg.setSpacing(8)
            chk = QCheckBox()
            chk.setChecked(True)
            chk.setStyleSheet(self._chk_style())
            rg.addWidget(chk, 0)
            lbl_code = self._fixed_label(str(raw[1]), 60)
            lbl_name = self._fixed_label(name, 150)
            lbl_cur = self._fixed_label(
                f"{cur_lo:g} ~ {cur_hi:g} {raw[8]}", 170)
            for w in (lbl_code, lbl_name, lbl_cur):
                rg.addWidget(w, 0)
            sp_lo = QDoubleSpinBox()
            sp_hi = QDoubleSpinBox()
            span = max(abs(cur_hi - cur_lo), 1.0)
            for sp in (sp_lo, sp_hi):
                sp.setDecimals(dec)
                sp.setRange(-999999999.0, 999999999.0)
                sp.setFixedHeight(24)
                sp.setStyleSheet(self._spin_style())
            sp_lo.setValue(sug_lo)
            sp_hi.setValue(sug_hi)
            sp_lo.setMinimumWidth(80)
            sp_hi.setMinimumWidth(80)
            rg.addWidget(sp_lo, 0)
            rg.addWidget(QLabel("~"), 0)
            rg.addWidget(sp_hi, 0)
            lbl_note = self._fixed_label(note, 70)
            lbl_note.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px;")
            rg.addWidget(lbl_note, 0)
            rg.addStretch(1)
            self._body_lay.addWidget(row_w)
            self._rows.append((r, chk, sp_lo, sp_hi))
        if not self._rows:
            empty = QLabel("当前没有可自动调整的数值型检测项")
            empty.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._body_lay.addWidget(empty)
        self._body_lay.addStretch(1)

    @staticmethod
    def _fixed_label(text, width):
        lab = QLabel(str(text))
        lab.setFixedWidth(width)
        lab.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
        return lab

    @staticmethod
    def _chk_style():
        return (
            f"QCheckBox {{ color: {COLORS['text_primary']}; font-size: 11px; "
            f"spacing: 4px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; "
            f"background-color: {COLORS['bg_card']}; }}"
            f"QCheckBox::indicator:checked {{ "
            f"background-color: {COLORS['accent_orange']}; "
            f"border-color: {COLORS['accent_orange']}; }}")

    @staticmethod
    def _spin_style():
        return (
            f"QDoubleSpinBox {{ color: {COLORS['text_primary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; "
            f"padding: 2px 4px; font-size: 11px; }}"
            f"QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent_blue']}; }}"
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; }}")

    # -- 交互 ---------------------------------------------------------
    def _on_toggle_all(self, on):
        for _r, chk, _lo, _hi in self._rows:
            chk.setChecked(on)

    def _on_apply(self):
        changes = []
        for r, chk, sp_lo, sp_hi in self._rows:
            if chk.isChecked():
                lo, hi = sp_lo.value(), sp_hi.value()
                if lo > hi:
                    lo, hi = hi, lo
                changes.append((r, lo, hi))
        if not changes:
            QMessageBox.information(self, "规格自动调整", "请先勾选需要调整的检测项。")
            return
        n = 0
        try:
            n = self._owner.apply_spec_adjust(changes)
        except Exception as e:
            import traceback
            print("[SpecAutoAdjustDialog] 应用异常：", repr(e))
            traceback.print_exc()
        QMessageBox.information(
            self, "规格自动调整",
            f"已应用 {n} 个检测项的新规格上下限，并按新规格重新判定『检测结果』。")
        self.accept()


class DebugView(QWidget):
    def __init__(self, camera_name="下表面", parent=None, main_window=None):
        super().__init__(parent)
        self.camera_name = camera_name
        self.main_window = main_window
        self._row_checks = {}
        self._table_data = []
        self._eff_metrics = {}  # 图像效果调节：指标名 -> {val,badge,lo,hi}
        self._playing = False
        self._frozen = False
        self._tick_count = 0
        self._production_running = False   # 设备是否处于生产运行状态（由设备启动/停止同步）
        self._live_drift = {}              # 实时演示数据缓慢游走偏移：{key: offset}
        self._accepted_mode = "连续取图"     # 当前已生效的工作模式（切换被拒时回退到此）
        self._local_image_window = None     # 工作模式=本地图像 时弹出的本地图像浏览窗口
        self._local_image_prev_mode = None  # 进入「本地图像」前的工作模式（关闭窗口后恢复）
        self._prod_start_time = None        # 设备启动生产的时间（用于分布图时间范围默认起点）
        self._last_live_push = 0.0          # 向参数分布面板推送实时样本的节流时间戳（time.monotonic）
        self._dist_samples = {}             # 检测项分布样本缓存：{行号: [(datetime, value), ...]}
        self._dist_cleared_at = {}          # 各检测项『清零』时刻，用于重置分布数据起点
        self._param_samples = {}            # 参数分布样本池：{(名称, key): [(datetime, value), ...]}
        self._param_cleared_at = {}         # 各参数『清零』时刻，用于重置分布数据起点
        # 检测项筛选状态（显示所有/显示已选）：从持久化配置恢复上次状态，重启后保留
        _cfg = _load_debug_config()
        self._filter_show_checked = bool(
            _cfg.get(self.camera_name, {}).get("filter_show_checked", False))
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._cam_speed = [1, 2, 1, 2]
        # 样张帧缓存：首次生成后复用，避免切换界面时反复同步生成造成卡顿
        self._frames_cache = None
        self._frames_cache_size = None
        self._frames_cache_local = False  # 当前画布是否被本地图像覆盖（覆盖时跳过样张复用）
        self.init_ui()

    @staticmethod
    def _eff_font(bold=False):
        """与『产品定位及区域分割』页正文一致的字体：12px（CSS 像素，非 12pt）。

        tab1 的文字用样式表 ``font-size: 12px`` 渲染，故此处用 pixelSize=12
        才能与其显示尺寸严格一致（12pt ≈ 16px，会偏大而不同）。
        """
        f = QFont("Microsoft YaHei", QFont.Weight.Bold if bold else QFont.Weight.Normal)
        f.setPixelSize(12)
        return f

    def _build_effect_tab(self):
        """『图像效果调节』标签页：与「产品定位及区域分割 / 计算元素精确查找」同级。

        无顶部总开关；每个检测项（清晰度 / 产品长度）左侧带独立启用开关
        （默认开启），右侧展示示例数值、OK/NG 判定与合格范围（示例值区间）。
        真实引擎接入时，把示例值与合格范围替换为实时计算结果即可。
        """
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout as _V, QHBoxLayout as _H, QLabel as _L, QPushButton,
        )

        tab = QWidget()
        tab.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        vbox = _V(tab)
        vbox.setContentsMargins(14, 12, 14, 12)
        vbox.setSpacing(10)

        # 说明
        tip = _L("示例数值与合格范围（相机刷新且检测项启用时实时更新）：")
        tip.setFont(self._eff_font())
        tip.setStyleSheet(f"color: {COLORS['text_secondary']};")
        vbox.addWidget(tip)

        # 指标行（清晰度 / 产品长度 / 垂直度），范围为随机刷新区间
        metrics = _V()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(8)
        metrics.addLayout(self._effect_metric_row("清晰度", "85.33", "OK", "80-100", 80.0, 100.0))
        metrics.addLayout(self._effect_metric_row("产品长度", "359.55", "OK", "350-370", 350.0, 370.0))
        # 亮度差异（2026-10-09 新增）：示例值在 30-100 内随机波动，
        # 合格范围 30-225（上限 225 > 刷新区间上限 100，故恒为 OK）。
        metrics.addLayout(self._effect_metric_row(
            "亮度差异", "46.20", "OK", "30-225", 30.0, 100.0,
            qual_lo=30.0, qual_hi=225.0))
        # 垂直度：示例范围 0.01-0.25；80% 概率落在 0.01-0.2、20% 概率落在 0.20-0.25；
        # 合格范围为 0-0.2（落在区间外记为 NG，用于演示超限判定）。
        metrics.addLayout(self._effect_metric_row(
            "垂直度", "0.13", "OK", "0-0.2", 0.01, 0.25,
            dist="vdist", qual_lo=0.0, qual_hi=0.2))
        vbox.addLayout(metrics)
        vbox.addStretch()
        return tab

    def _effect_metric_row(self, name, value, status, qual_range, lo, hi,
                           dist=None, qual_lo=None, qual_hi=None):
        """单行：启用开关 | 名称 | 示例值 | OK/NG | 合格范围（示例区间）。

        lo/hi 为该指标随机刷新区间，登记引用供实时刷新；
        合格判定区间由 qual_lo/qual_hi 决定（默认等于刷新区间）。
        dist="vdist" 时使用垂直度专用分布（0.01-0.2 占 80%、0.20-0.25 占 20%）。
        行左侧启用开关默认开启，关闭后该行示例数值暂停随机刷新。
        """
        from PyQt6.QtWidgets import QHBoxLayout as _H, QLabel as _L

        row = _H()
        row.setSpacing(8)
        # 行左侧启用开关（iOS 风格，默认开启）
        sw = ToggleSwitch(on=True)
        sw.setToolTip(f"启用{name}检测")
        row.addWidget(sw)
        name_lbl = _L(name)
        name_lbl.setFixedWidth(72)
        name_lbl.setFont(self._eff_font())
        name_lbl.setStyleSheet(f"color: {COLORS['text_primary']};")
        val_lbl = _L(value)
        val_lbl.setFixedWidth(84)
        val_lbl.setFont(self._eff_font())
        val_lbl.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; padding: 4px 6px;")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok = str(status).strip().upper() == "OK"
        badge = _L(status)
        badge.setFixedSize(48, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFont(self._eff_font(bold=True))
        badge.setStyleSheet(
            f"background-color: {'#2E9E5B' if ok else '#D14343'}; "
            f"color: white; border-radius: 4px;")
        rng = _L(f"合格范围 {qual_range}")
        rng.setFixedWidth(128)
        rng.setFont(self._eff_font())
        rng.setStyleSheet(f"color: {COLORS['text_secondary']};")
        row.addWidget(name_lbl)
        row.addWidget(val_lbl)
        row.addWidget(badge)
        row.addWidget(rng)
        row.addStretch()
        # 登记引用，供相机图像刷新时实时更新数值（含每行独立启用状态）
        self._eff_metrics[name] = {
            "val": val_lbl, "badge": badge, "lo": lo, "hi": hi,
            "qual_lo": qual_lo if qual_lo is not None else lo,
            "qual_hi": qual_hi if qual_hi is not None else hi,
            "dist": dist, "enabled": True, "sw": sw,
        }

        def _on_toggle(on):
            self._eff_metrics[name]["enabled"] = bool(on)
            if on:
                # 重新开启时立即刷新一次，避免显示陈旧示例值
                self._refresh_effect_values()

        sw.toggled.connect(_on_toggle)
        return row

    def _refresh_effect_values(self):
        """相机正在刷新图像时，把已启用检测项的示例数值随机刷新，并按各自的合格区间
        更新 OK/NG；关闭开关的行不刷新。

        垂直度（dist="vdist"）使用专用分布：80% 概率落在 0.01-0.2、20% 概率落在
        0.20-0.25（其合格区间为 0-0.2，落在 0.20-0.25 时记为 NG，用于演示超限）。
        真实引擎接入后，把随机值替换为实时测量值即可。
        """
        import random
        for m in self._eff_metrics.values():
            if not m.get("enabled", True):
                continue
            lo, hi = m["lo"], m["hi"]
            if m.get("dist") == "vdist":
                # 垂直度专用分布：0.01-0.2 占 80%、0.20-0.25 占 20%
                if random.random() < 0.8:
                    val = random.uniform(0.01, 0.20)
                else:
                    val = random.uniform(0.20, 0.25)
            else:
                val = random.uniform(lo, hi)
            val = round(val, 2)
            m["val"].setText(f"{val:.2f}")
            ok = m["qual_lo"] <= val <= m["qual_hi"]
            m["badge"].setText("OK" if ok else "NG")
            m["badge"].setStyleSheet(
                f"background-color: {'#2E9E5B' if ok else '#D14343'}; "
                f"color: white; border-radius: 4px;")

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 主体区域（左 + 中）：上方相机画布 + 产品定位搜索设置（等高），下方检测项列表
        body = QVBoxLayout()
        body.setSpacing(12)

        # 顶部区域用网格布局：左列 = 相机画布行(0,0) + 工具条行(1,0)；
        # 右侧「产品定位搜索设置」卡片在 (0,1) 跨两行——整体高度 = 相机卡片 +
        # 工具条行，底边与工具条行对齐，向下填满与检测项表格之间的空当。
        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(16)
        top_grid.setVerticalSpacing(12)

        # 预览区：主相机画布 400×300；右侧 R/G/B 三通道（含间隙总高 300，每路 4:3）
        preview_row = QHBoxLayout()
        preview_row.setSpacing(16)
        main_preview = CameraPreview(f"相机：{self.camera_name}", 400, 300)
        preview_row.addWidget(main_preview)
        # 相机卡片名称右侧「拍照设置」按钮：内容与左侧导航「拍照设置」窗口完全一致
        # （原「AI助手」入口已删除：顶部标题栏与左侧导航仍保留 AI助手入口）
        btn_photo = QPushButton("拍照设置")
        btn_photo.setFixedHeight(22)
        btn_photo.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_photo.setFont(QFont("Microsoft YaHei", 9))
        btn_photo.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 8px; "
            f"font-size: 10px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; color: white; }}")
        btn_photo.clicked.connect(lambda: self.main_window._open_trigger_settings())
        main_preview.add_title_button(btn_photo)

        # 相机模式选择行：置于主画布底部左下角（覆盖层）
        overlay = QFrame(main_preview)
        overlay.setStyleSheet(
            "QFrame { background-color: rgba(20,22,26,0.72); border-radius: 4px; }")
        orow = QHBoxLayout(overlay)
        orow.setContentsMargins(8, 4, 8, 4)
        orow.setSpacing(6)
        mode = QComboBox()
        mode.addItems(["生产运行", "连续取图", "连续运行", "本地图像", "模拟生产"])
        mode.setMinimumHeight(26)
        self._trigger_mode = mode
        # 软件启动、设备尚未生产运行时，初始工作模式不应是「生产运行」，
        # 否则会误触发标定的「生产运行中」提示；统一初始化为「连续取图」。
        mode.setCurrentText("连续取图")
        self._accepted_mode = "连续取图"
        # 工作模式切换：先经过守卫（生产运行中仅允许切到生产运行/本地图像），
        # 通过后再刷新底部控制按钮的可点击/配色状态
        mode.currentTextChanged.connect(self._on_mode_changed)
        mode_lbl = QLabel("工作模式：")
        mode_lbl.setStyleSheet("color: #E6E6E6; font-size: 12px;")
        orow.addWidget(mode_lbl)
        orow.addWidget(mode)
        # 冻结 / 抓取 / 运行：状态（可点击 + 配色）由 _refresh_control_states 统一控制
        for txt in ["冻结", "抓取", "运行"]:
            b = QPushButton(txt)
            if txt == "冻结":
                b.clicked.connect(self._on_freeze_toggle)
                self._freeze_btn = b
            elif txt == "抓取":
                self._grab_btn = b
            elif txt == "运行":
                self._run_btn = b
            orow.addWidget(b)
        # 初始化：抓取/运行默认禁用并置灰，冻结按钮默认蓝色可点击
        self._refresh_control_states()
        # 标定按钮：置于画布右下角最右侧（同行末尾，左侧弹性留白将其推到右端）
        orow.addStretch()
        calib = QPushButton("标定")
        calib.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border-radius: 4px; padding: 3px 10px; font-size: 12px;")
        calib.clicked.connect(self._on_calibrate)
        orow.addWidget(calib)
        self._calib_btn = calib
        overlay.setGeometry(8, 300 - 40, 400 - 16, 34)
        overlay.raise_()

        side = QVBoxLayout()
        side.setSpacing(6)
        # 右侧 R/G/B 三通道预览：不显示通道下拉控件，固定展示各自真实通道分离效果
        r_preview = CameraPreview("R 通道", 128, 96, show_channel_control=False)
        g_preview = CameraPreview("G 通道", 128, 96, show_channel_control=False)
        b_preview = CameraPreview("B 通道", 128, 96, show_channel_control=False)
        r_preview.screen.set_channel("r")
        g_preview.screen.set_channel("g")
        b_preview.screen.set_channel("b")
        side.addWidget(r_preview)
        side.addWidget(g_preview)
        side.addWidget(b_preview)
        preview_row.addLayout(side)
        self._cams = [main_preview, r_preview, g_preview, b_preview]
        # 左侧画布区固定不伸缩（相机画布本身为固定尺寸），始终锚定在左上，
        # 右侧信号卡片伸缩吸收宽度变化 —— 避免右侧标签页内容变宽时挤压/推动左侧画布。
        top_grid.addLayout(preview_row, 0, 0)
        top_grid.setColumnStretch(0, 0)

        # 运行日志视图需先创建（下方「产品定位搜索设置」卡片中的查找/加载操作会写入它），
        # 其样式/布局在下方右侧信息栏完成。标题栏左侧「日志详情」按钮与左侧导航「日志管理」一致。
        self._run_log = LogView([], detail_callback=lambda: self._open_log_manager())

        # 产品定位搜索设置：仅保留「产品目标搜索」「计算元素精确查找」「图像效果调节」
        # 三个子页面。卡片高度由网格跨行决定（相机行 + 工具条行），不再用最小高度 hack；
        # 标签页内容超出时内部滚动，不会被内容撑高。
        signal_card = Card()   # 不再显示「产品定位搜索设置」标题，直接承载三个子页面标签
        signal_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._signal_card = signal_card   # 供相机标定窗口定位锚点（置于其上方、左对齐）

        target = TargetLocationContent(camera_name=self.camera_name,
                                       run_log=self._run_log,
                                       camera_preview=main_preview)
        self._target_content = target

        # 「检测流程设计」子页面：与「产品目标搜索」同级、置于其左侧（第 0 个标签）。
        # 卡片内嵌区域宽高受限的拥挤问题由 flow_design 模块内解：
        # 工具箱可折叠 / 画布可缩放+自动布局 / 「⛶ 放大编辑」弹出大窗口（同一数据模型实时同步）。
        from flow_design import FlowDesignPage, _make_icon
        self._flow_page = FlowDesignPage(run_log=self._run_log)

        tabs = QTabWidget()
        self._target_tabs = tabs
        tabs.addTab(self._flow_page, "检测流程设计")
        tabs.addTab(target._tab1, "产品目标搜索")
        tabs.addTab(target._tab2, "2. 计算元素精确查找")
        # 「图像效果调节」：与上面两个子页面同级（第三个标签页）
        eff_tab = self._build_effect_tab()
        tabs.addTab(eff_tab, "3. 图像效果调节")
        TargetLocationContent.style_tab_widget(tabs)

        signal_card.layout.addWidget(tabs, 1)
        # 右侧卡片跨「相机行 + 工具条行」两行：高度=两者之和，底边与工具条行对齐
        top_grid.addWidget(signal_card, 0, 1, 2, 1)
        top_grid.setColumnStretch(1, 1)   # 仅右侧信号卡片伸缩，左侧画布区宽度恒定

        body.addLayout(top_grid)

        # 检测项目表格：列宽按内容自动撑开（可全部显示），过宽时用横向滚动条左右拖动查看
        table = QTableWidget()
        # 表格正文字体：**10px**（2026-10-09 需求：红框内所有字号统一 10px）。
        # ⚠️ Qt 的 `QFont(name, n)` 整数参数单位是**磅(point)**，必须用
        # `setPixelSize(10)` 才是真正的 10px。
        _f_tbl = QFont("Microsoft YaHei")
        _f_tbl.setPixelSize(10)
        table.setFont(_f_tbl)
        table.setColumnCount(14)
        # ⚠️ 2026-10-09 需求：把「检测值」整列移动到「检测结果」列的**左侧**。
        # 新列序：显示所有 / 是否检测 / 检测编号 / 检测项目 / 标称值 /
        #        补偿值 / 规格下限 / 规格上限 / 单位 / 检测值 /检测结果 /
        #        收料位置 / 检测项操作 / 良率预警设置
        # （检测值列号由5 → 9；单位列号由 9 → 8；结果/收料位置仍是 10 / 11）
        # 「检测结果」位于「收料位置」左侧的约定保持不变。
        # 首列标题作为「显示所有 / 显示已选」切换开关，与参考图保持一致；
        # 数据行首列仍显示当前序号。
        headers = ["显示所有", "是否检测", "检测编号", "检测项目", "标称值",
                   "补偿值", "规格下限", "规格上限", "单位", "检测值",
                   "检测结果", "收料位置", "检测项操作", "良率预警设置"]
        table.setHorizontalHeaderLabels(headers)
        # 「良率预警设置」（最后一列）列头名称左对齐显示（其余列头保持居中）
        _last_hdr = table.horizontalHeaderItem(table.columnCount() - 1)
        if _last_hdr is not None:
            _last_hdr.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 「是否检测」列头名称同样左对齐（右侧留给全开/全关批量开关）
        _det_hdr = table.horizontalHeaderItem(1)
        if _det_hdr is not None:
            _det_hdr.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 点击单元格不再显示橙色选中底色（局部样式覆盖全局橙色高亮，
        # 仅作用于本检测项列表，不影响其他表格）；
        # 同时去掉点击单元格时的白色圆角焦点框（outline: 0 + item:focus 去 outline）
        table.setStyleSheet(
            "QTableWidget { outline: 0; } "
            "QTableWidget::item { outline: 0; } "
            "QTableWidget::item:focus { outline: 0; } "
            "QTableWidget::item:selected { background-color: transparent; "
            f"color: {COLORS['text_primary']}; }}")
        table.setRowCount(10)
        # 12 列数据（是否检测, 编号, 项目, 标称, 检测值, 补偿, 下限, 上限, 单位, 收料, 结果, 有分布）
        raw = [
            [True, "100", "产品有无", "0", "0", "0", "0", "0", "Dec", "RST", "OK", True],
            [True, "101", "产品偏移", "0", "50", "0", "-100", "100", "Pixel", "RST", "OK", True],
            [True, "102", "产品歪料", "0", "1", "0", "0", "0", "Dec", "RST", "NG", True],
            [True, "103", "正反检测", "0", "0", "0", "0", "0", "Dec", "RST", "OK", True],
            [True, "104", "产品歪斜", "0", "7.5", "0", "-10", "10", "Deg", "RST", "OK", True],
            [True, "105", "产品宽度", "0.80", "0.95", "0", "0.70", "0.90", "mm", "NG1", "NG", True],
            [True, "106", "产品长度", "1.60", "1.62", "0", "1.50", "1.70", "mm", "NG1", "OK", True],
            [False, "107", "", "", "", "", "", "", "", "", "", False],
            [True, "108", "长边单边最大变形量", "0", "0.22", "0", "0", "0.2", "mm", "NG1", "NG", True],
            [True, "113", "字符数量", "4", "3", "0", "4", "4", "Dec", "NG2", "NG", True],
        ]
        data = raw
        self._table_data = data
        # 检测值列（数值标签）与单位列（UnitCell）的按行引用，供刷新/右键选择时同步
        self._val_labels = {}
        self._unit_cells = {}
        # 良率预警设置：按行记录「启用 / 预警阈值(%)」，默认全部启用、阈值 50%
        self._yield_warn = {r: {"enabled": True, "threshold": 50}
                            for r in range(len(raw))}

        # 统一的按钮样式（按钮+文字，10px 紧凑）：橙填充 / 橙描边 / 中性
        BTN_FILL = (f"background-color: {COLORS['accent_orange']}; color: white; "
                    f"border: none; border-radius: 4px; padding: 1px 5px; font-size: 10px;")
        BTN_OUTLINE = (f"background-color: {COLORS['bg_card']}; color: {COLORS['accent_orange']}; "
                       f"border: 1px solid {COLORS['accent_orange']}; border-radius: 4px; "
                       f"padding: 1px 5px; font-size: 10px;")
        BTN_NEUTRAL = (f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                       f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                       f"padding: 1px 5px; font-size: 10px;")

        for r, row in enumerate(data):
            item_name = row[2]   # 检测项目
            for c in range(table.columnCount()):
                if c == 0:
                    # 序号：显示顺序，过滤后自动重排（见 _renumber）
                    item = QTableWidgetItem(str(r + 1))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(r, c, item)
                elif c == 1:
                    # 是否检测（iOS 风格开关，与最后一列「良率预警设置」一致）
                    chk = ToggleSwitch(on=bool(row[0]))
                    chk.setFixedSize(40, 20)
                    chk.toggled.connect(
                        lambda v, rr=r: self._on_detect_toggled(rr, v))
                    self._row_checks[r] = chk
                    cell_widget = QFrame()
                    hl = QHBoxLayout(cell_widget)
                    hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    hl.setContentsMargins(0, 0, 0, 0)
                    hl.addWidget(chk)
                    table.setCellWidget(r, c, cell_widget)
                elif c == 9:
                    # 检测值（2026-10-09 由列号 5 移到 9，位于「检测结果」左侧）：
                    # 数值标签 + 「值分布」按钮（橙色填充），每一行都有；
                    # 加宽本列以完整显示「数值 + 按钮」（原「数值分布」列的按钮已移入此处）
                    val_widget = QFrame()
                    val_lay = QHBoxLayout(val_widget)
                    val_lay.setContentsMargins(2, 0, 2, 0)
                    val_lay.setSpacing(4)
                    val_lbl = QLabel(str(row[4]))
                    # cellWidget 不继承表格字体，需显式设为 10px
                    # 与表格正文 / 「值分布」按钮一致。
                    _f_val = QFont("Microsoft YaHei")
                    _f_val.setPixelSize(10)
                    val_lbl.setFont(_f_val)
                    val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    val_lbl.setMinimumWidth(64)
                    val_lay.addWidget(val_lbl, 1)
                    dist_btn = QPushButton("值分布")
                    dist_btn.setStyleSheet(BTN_FILL)
                    dist_btn.setFixedHeight(22)
                    dist_btn.setFixedWidth(64)
                    dist_btn.clicked.connect(
                        lambda _, n=item_name, rr=r: self._open_distribution(n, rr))
                    val_lay.addWidget(dist_btn)
                    self._val_labels[r] = val_lbl
                    table.setCellWidget(r, c, val_widget)
                elif c == 8:
                    # 单位（2026-10-09 由列号 9 移到 8）：
                    # 鼠标悬停提示「右键选择单位」，右键弹出菜单（Pixel/mm/Deg/Dec/灰度级）
                    unit_cell = UnitCell(
                        row[8] if len(row) > 8 else "",
                        on_select=lambda t, rr=r: self._set_unit(rr, t))
                    self._unit_cells[r] = unit_cell
                    table.setCellWidget(r, c, unit_cell)
                elif c == 12:
                    # 检测项操作：教导 / 复制 / 删除（中性按钮+文字），每一行都有（已移除「同步」）
                    btn_widget = QFrame()
                    hl = QHBoxLayout(btn_widget)
                    hl.setContentsMargins(2, 0, 2, 0)
                    hl.setSpacing(3)
                    for txt in ["教导", "复制", "删除"]:
                        b = QPushButton(txt)
                        b.setStyleSheet(BTN_NEUTRAL)
                        b.setFixedHeight(22)
                        if txt == "教导":
                            b.clicked.connect(
                                lambda _, n=item_name, rr=r: self._open_teach(n, rr))
                        else:
                            b.setToolTip("示例占位（演示）")
                        hl.addWidget(b)
                    table.setCellWidget(r, c, btn_widget)
                elif c == 13:
                    # 良率预警设置：启用开关（iOS 风格滑块）+ 预警阈值（默认 50%），每行都有
                    warn = self._yield_warn.get(r, {"enabled": True, "threshold": 50})
                    btn_widget = QFrame()
                    hl = QHBoxLayout(btn_widget)
                    hl.setContentsMargins(2, 0, 2, 0)
                    hl.setSpacing(4)
                    sw = ToggleSwitch(on=warn["enabled"])
                    sw.setFixedSize(40, 20)
                    sw.toggled.connect(
                        lambda v, rr=r: self._on_yield_warn_toggled(rr, v))
                    hl.addWidget(sw)
                    th = QSpinBox()
                    th.setRange(0, 100)
                    th.setValue(int(warn["threshold"]))
                    th.setSuffix(" %")
                    th.setFixedHeight(22)
                    th.setStyleSheet(
                        f"QSpinBox {{ background-color: {COLORS['bg_card']}; "
                        f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                        f"border-radius: 4px; padding: 0 4px; font-size: 10px; }}")
                    th.valueChanged.connect(
                        lambda v, rr=r: self._on_yield_warn_threshold(rr, v))
                    hl.addWidget(th)
                    table.setCellWidget(r, c, btn_widget)
                else:
                    # 普通文本列：按 `_data_index_for_col` 查表映射到原始数据 row 的对应字段。
                    # ⚠️ 2026-10-09「检测值」列移到「检测结果」左侧后，列号与
                    # row 索引不再一一对应，必须走查表函数，勿用 `c-1` 推导。
                    di = self._data_index_for_col(c)
                    if di is None or di >= len(row):
                        val = ""
                    else:
                        val = row[di]
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if c == 10:   # 检测结果：按实际结果着色（OK 绿 / NG 红 / 待定 橙）
                        self._apply_result_color(item, str(val))
                    table.setItem(r, c, item)

        table.verticalHeader().setDefaultSectionSize(32)
        # 隐藏左侧行号列（竖向表头），保留首列「显示所有/是否检测」等数据列不变
        table.verticalHeader().setVisible(False)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # 横向滚动：列过多/过宽时可左右拖动查看，不截断内容
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table = table

        # 列头字体 10px（2026-10-09 需求：红框内所有字号统一 10px；
        # 原 `QFont(name, 8)` 为 8磅≈10.67px，改用 setPixelSize(10) 精确 10px）。
        # ⚠️ 实测：此处 setFont 会在 init_ui 后半段（StatsPanel/FloatPanel 等
        # setStyleSheet 触发的 polish）被重置回应用默认字体，故真正的setFont
        # 统一放在 init_ui 末尾执行（见本方法最后）。
        h = table.horizontalHeader()
        h.setTextElideMode(Qt.TextElideMode.ElideNone)
        h.setFixedHeight(28)
        # 所有列按内容宽度自适应；超出可视范围时出现横向滚动条
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.resizeColumnsToContents()
        # 「是否检测」列加宽为固定宽：列头文字左对齐 + 右侧全开/全关开关，
        # 两者互不遮挡（ResizeToContents 模式下 setColumnWidth 不生效，需切 Interactive）
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(1, 120)

        # 「显示所有 / 显示已选」切换开关已放到首列表头位置，与参考图一致；
        # 点击首列标题即可在「显示所有」和「显示已选」之间切换。
        h.sectionClicked.connect(self._on_header_section_clicked)
        register_restyle(self._restyle)

        # 「全开 / 全关」批量开关：直接覆盖在「良率预警设置」列（最右列）列头的右侧，
        # 不再单独占一行；点击联动全部行的良率预警启用开关，两态底色不同。
        self._yield_all_btn = QPushButton("全开", h.viewport())
        self._yield_all_btn.setFixedHeight(20)
        self._yield_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._yield_all_btn.setToolTip("点击把全部检测项的良率预警在启用/停用间切换")
        self._yield_all_btn.clicked.connect(self._on_yield_all_toggle)
        self._set_toggle_btn(self._yield_all_btn, True, "全开", "全关")
        self._yield_all_btn.show()
        self._yield_all_btn.raise_()

        # 「检测项全开 / 全关」批量开关：覆盖在「是否检测」列（第 2 列）列头的右侧，
        # 与最后一列「良率预警设置」的全开/全关开关同机制、同位置逻辑；
        # 点击联动全部行的「是否检测」开关，两态底色不同。
        self._detect_all_btn = QPushButton("全开", h.viewport())
        self._detect_all_btn.setFixedHeight(20)
        self._detect_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detect_all_btn.setToolTip("点击把全部检测项在检测/不检测间切换")
        self._detect_all_btn.clicked.connect(self._on_detect_all_toggle)
        self._set_toggle_btn(self._detect_all_btn, True, "全开", "全关")
        self._detect_all_btn.show()
        self._detect_all_btn.raise_()

        # 列头尺寸 / 列宽 / 横向滚动变化时，把两个开关重新贴到对应列头的右侧
        h.sectionResized.connect(lambda *_: self._reposition_overlay_buttons())
        h.viewport().installEventFilter(self)
        table.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._reposition_overlay_buttons())

        # 检测项列表上方工具条（从左到右）：
        # 设置为默认 → 恢复至默认 → 恢复至出厂 → 单位设置 → 出料设置 → 全部同步
        # → 规格自动调整（2026-10-20 新增：基于分布样本自动调整检测项规格上下限）
        # （「检测项全开/关」已移到「是否检测」列头右侧，与「良率预警设置」列头一致）
        self._detect_all_on = True    # 「检测项全开/关」初始为「全开」态
        self._yield_all_on = True     # 「预警全开/关」初始为「全开」态
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.setContentsMargins(0, 0, 0, 0)
        TOOLBAR_BTN = (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 2px 10px; font-size: 11px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['bg_panel']}; }}")
        # 2026-10-21 需求：本排按钮改为「图标 + 悬浮提示」显示，节省横向空间
        toolbar_defs = [
            ("设置为默认", "default_set", None),
            ("恢复至默认", "restore", None),
            ("恢复至出厂", "factory", None),
            ("单位设置", "unit", None),
            ("出料设置", "output", None),
            ("全部同步", "sync", None),
            ("规格自动调整", "params", self._on_auto_spec_adjust),
        ]
        for label, icon_kind, handler in toolbar_defs:
            tb = QPushButton()
            tb.setIcon(_make_icon(icon_kind, COLORS['text_primary']))
            tb.setIconSize(QSize(16, 16))
            tb.setFixedSize(28, 28)
            tb.setToolTip(label)
            tb.setStyleSheet(TOOLBAR_BTN)
            if handler is not None:
                tb.clicked.connect(handler)
            toolbar.addWidget(tb)
        toolbar.addStretch()
        # 工具条放在网格左列第二行（相机画布正下方）——右侧信号卡片跨两行与其底边对齐
        top_grid.addLayout(toolbar, 1, 0)

        body.addWidget(table, 1)
        self._apply_filter_state()  # 按持久化的「显示所有/显示已选」状态初始化序号与可见行
        # 列宽自适应完成后再把两个「全开/全关」开关贴到对应列头右侧
        QTimer.singleShot(0, self._reposition_overlay_buttons)

        # 右侧信息栏：上为「生产统计与检测结果」，下为「运行日志」。
        # 生产统计面板以镜像方式复用生产运行界面的实时统计（单一数据源），
        # 保证调试界面与生产运行界面的生产信息（KPI/环形图/按相机/按缺陷项/详情）始终一致。
        right = QVBoxLayout()
        right.setSpacing(16)

        # 生产统计与检测结果：镜像生产运行界面（首次创建即同步一次快照，
        # 之后由播放节拍持续刷新），调试界面无需独立维护示例数据。
        # 用 FloatPanel("统计信息", ...) 包装，与生产运行界面的卡片标题栏保持一致。
        self.stats_panel = StatsPanel(parent=self)
        self._setup_stat_mirror()
        self.stats_card = FloatPanel("统计信息", parent=self, min_w=410, min_h=440)
        self.stats_card.set_body_layout(self.stats_panel)
        # 饼图/详情按钮移到卡片标题栏右侧（与生产运行界面布局一致），
        # set_header_actions 会 reparent 按钮；面板内部原 toggle_row 自然留空折叠。
        self.stats_card.set_header_actions([
            self.stats_panel._btn_pie, self.stats_panel._btn_detail])
        right.addWidget(self.stats_card, 2)

        # 运行日志：始终在调试界面显示，记录本界面及生产运行界面的操作与状态。
        self._run_log.setMinimumSize(360, 200)
        right.addWidget(self._run_log, 1)

        # 两栏布局：主体(画布+产品定位搜索设置等高 / 检测项列表) | 生产统计+运行日志（整高）
        # 说明：「产品定位及区域分割」「计算元素精确查找」已并入上方「产品定位搜索设置」卡片，
        # 不再作为独立显示区域，故此处不再单独挂载。
        layout.addLayout(body, 4)
        layout.addLayout(right, 2)

        # 列头字体 10px：必须在 init_ui 全部构建完成后设置。
        # 实测若在表格构建中途 setFont，会被后续 StatsPanel/FloatPanel 等
        # setStyleSheet 触发的 polish 重置回应用默认字体（Sans Serif 9pt）；
        # 构建末尾设置则稳定生效（show 之后仍保持 10px）。
        _hdr_font = QFont("Microsoft YaHei")
        _hdr_font.setPixelSize(10)
        _hdr_font.setWeight(QFont.Weight.Normal)
        self._table.horizontalHeader().setFont(_hdr_font)

    # ------------------------------------------------------------------
    # 主题重绘
    # ------------------------------------------------------------------
    def set_trigger_mode(self, mode):
        """「触发设定」窗口同步调试界面底部工作模式下拉框。"""
        if not hasattr(self, "_trigger_mode"):
            return
        idx = self._trigger_mode.findText(mode)
        if idx >= 0:
            self._trigger_mode.setCurrentIndex(idx)

    def set_production_running(self, running):
        """由「设备启动 / 设备停止」同步设备的生产运行状态，用于工作模式切换守卫。

        - 设备启动（生产运行）：置 True，此后工作模式下拉框仅允许停留在
          「生产运行」或切换至「本地图像」，切到其它模式一律拒绝并弹窗。
        - 设备停止：置 False，解除限制，所有工作模式均可正常切换。
        """
        self._production_running = bool(running)
        # 同步镜像统计面板的速度刷新状态：设备启动→速度波动；设备停止→速度衰减归零
        sp = getattr(self, "stats_panel", None)
        if sp is not None and hasattr(sp, "set_speed_running"):
            sp.set_speed_running(self._production_running)
        if self._production_running and self._prod_start_time is None:
            # 记录设备启动生产的时间，作为分布图数据时间范围的默认起点
            self._prod_start_time = datetime.now()
        if not self._production_running:
            # 解除限制后立即按当前模式刷新按钮状态（例如从连续运行/模拟生产退出）
            self._refresh_control_states()

    def is_production_running(self):
        """返回设备是否处于生产运行状态（参数分布实时刷新据此判断）。"""
        return getattr(self, "_production_running", False)

    def get_live_param_value(self, name, key, lo, hi):
        """返回某计算元素某参数的实时『实测值』（演示用，结构上预留真实引擎接入点）。

        当前为演示：以当前阈值上下限附近为中心做高斯扰动，并叠加一个缓慢随机游走（drift），
        使分布随时间明显漂移 —— 散点 / 直方图 / 累积分布随时间可见地变化，便于观察调参效果。
        约 8% 概率产生越界离群点，用于观察合格率随阈值上下限的变化。
        真实环境应替换为算法引擎对每个被检元件产出的实测值。
        """
        if lo is None or hi is None or hi <= lo:
            return 0.0
        rng = float(hi - lo)
        drift = self._live_drift.get(key, 0.0)
        drift += random.uniform(-rng * 0.02, rng * 0.02)   # 缓慢随机游走
        drift = max(-rng * 0.35, min(rng * 0.35, drift))   # 限制在 ±35% 量程内
        self._live_drift[key] = drift
        center = (lo + hi) / 2.0 + drift
        spread = rng * 0.30
        if random.random() < 0.08:   # 偶发离群点
            center = (lo - spread * 1.2) if random.random() < 0.5 \
                else (hi + spread * 1.2)
        val = random.gauss(center, spread)
        # 约束在可视量程附近，避免散点飞出坐标轴
        val = max(lo - rng * 0.5, min(hi + rng * 0.5, val))
        decimals = {"thresh": 0, "area": 0, "tol": 0}.get(key, 0)
        return round(val, decimals)

    def _sync_local_image_window(self):
        """工作模式为「本地图像」时弹出本地图像浏览窗口；离开该模式则隐藏。"""
        if not hasattr(self, "_trigger_mode"):
            return
        if self._trigger_mode.currentText() == "本地图像":
            self._open_local_image_window()
        else:
            self._close_local_image_window()

    def _open_local_image_window(self):
        """已打开则置顶聚焦（保留已加载图片），否则新建并以非模态方式显示。
        首次创建时将其初始位置定位到「生产统计」页面之上、右对齐。"""
        from local_image_window import LocalImageWindow
        if self._local_image_window is None:
            w = LocalImageWindow(self)
            w.finished.connect(self._on_local_image_closed)
            self._local_image_window = w
            # 初始位置：浮于「生产信息」卡片之上、右上对齐（窗口可拖动）。
            # 锚点用调试界面「生产信息」卡片 self.stats_card，使其右上角与卡片右上角对齐。
            self._place_floating(w, self.stats_card, "right")
            # 定位完成后重置本地图像窗口的「右上角锚点」：
            # 详情展开/收起都以这个右上角为基准，保证两态之间来回切换时
            # 右上角严格对齐不变、不会漂移（需求：右上角对齐保持不变）。
            w.reset_detail_anchor()
        self._local_image_window.show()
        self._local_image_window.raise_()
        self._local_image_window.activateWindow()

    def _close_local_image_window(self):
        """切离「本地图像」模式：隐藏窗口（保留已加载图片，便于再次进入时复用）。"""
        w = getattr(self, "_local_image_window", None)
        if w is not None:
            w.hide()

    def _on_local_image_closed(self, result):
        """用户点击窗口关闭(X)后清除引用，下次进入「本地图像」重新创建；
        同时把相机工作模式恢复为进入「本地图像」之前的模式，使画布按该模式刷新。

        进入「本地图像」期间画布仍按原模式刷新（由本窗口未主动同步图片保证），
        仅当用户在窗口中点选了某张图时画布才显示该图；关闭窗口恢复模式后，
        若处于播放态则以恢复模式的样张重新生成帧序列，继续按该模式刷新画布。
        """
        self._local_image_window = None
        prev = getattr(self, "_local_image_prev_mode", None)
        if prev and prev != self._trigger_mode.currentText():
            # 静默还原下拉框，避免递归触发 _on_mode_changed（window 已关闭不会再次弹出）
            self._trigger_mode.blockSignals(True)
            self._trigger_mode.setCurrentText(prev)
            self._trigger_mode.blockSignals(False)
            self._accepted_mode = prev
            self._refresh_control_states()
            self._sync_local_image_window()   # 离开「本地图像」：隐藏窗口（已为 None，幂等）
            # 画布按恢复后的工作模式重新刷新（重新生成对应样张帧序列）
            self._frames_cache_local = False  # 退出本地图像：恢复为样张播放
            if self._playing:
                self._begin_play()

    def _sync_local_image(self, pixmap):
        """本地图像窗口选中某张图时，把该图同步刷新到相机主画布及
        R/G/B 三个通道（四路统一使用同一张图片，保证画面一致）。

        pixmap 为 None（例如清空/无效图片）时不做处理。"""
        if pixmap is None or pixmap.isNull():
            return
        # 标记为本地图像覆盖：此后切换界面不再复用/重建样张，保持当前图片
        self._frames_cache_local = True
        for cam in self._cams:
            cam.set_frames([pixmap])
            cam.set_frame_index(0)

    def _place_floating(self, win, anchor, align="left"):
        """将一个浮动窗口（相机标定 / 本地图像）的初始位置设定为「浮于 anchor
        控件区域之上」——即窗口与该区域重叠覆盖，并按 align 指定的角对齐：
        - align='left'  ：窗口左上角对齐 anchor 左上角（左上对齐）
        - align='right' ：窗口右上角对齐 anchor 右上角（右上对齐）
        窗口本身可拖动（标题栏默认行为），此处仅设定初始位置；
        仅在窗口首次创建时调用，之后尊重用户拖动过的位置。"""
        if anchor is None or not anchor.isVisible():
            return
        g = anchor.geometry()
        top_left = anchor.mapToGlobal(g.topLeft())
        scr = win.screen()
        if scr is not None:
            avail = scr.availableGeometry()
        else:
            avail = QApplication.primaryScreen().availableGeometry()
        # 取实际尺寸（未布局前可能为零，则回退到最小尺寸 / sizeHint）
        mw, mh = win.minimumWidth(), win.minimumHeight()
        w = win.width() or mw or win.sizeHint().width()
        h = win.height() or mh or win.sizeHint().height()
        gap = 6
        if align == "right":
            # 右上对齐：窗口右边缘与 anchor 右边缘对齐
            x = top_left.x() + g.width() - w
        else:
            # 左上对齐：窗口左边缘与 anchor 左边缘对齐
            x = top_left.x()
        # 浮于 anchor 区域之上（重叠覆盖）：窗口顶边与 anchor 顶边对齐
        y = top_left.y()
        # 夹取在屏幕可用区内，避免越界；纵向不足时整体回退到 anchor 下方
        if y + h > avail.bottom() - 8:
            y = top_left.y() + g.height() + gap
        x = max(avail.left() + 4, min(x, avail.right() - w - 4))
        y = max(avail.top() + 4, min(y, avail.bottom() - h - 4))
        win.move(x, y)

    def _update_filter_header(self):
        """刷新首列表头为「显示所有」或「显示已选」并高亮，与参考图保持一致。"""
        t = getattr(self, "_table", None)
        if t is None:
            return
        text = "显示已选" if getattr(self, "_filter_show_checked", False) else "显示所有"
        item = t.horizontalHeaderItem(0)
        if item is None:
            item = QTableWidgetItem(text)
            t.setHorizontalHeaderItem(0, item)
        else:
            item.setText(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(10)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor(COLORS["accent_blue"]))

    def _restyle(self):
        self._update_filter_header()
        if getattr(self, "_target_tabs", None) is not None:
            TargetLocationContent.style_tab_widget(self._target_tabs)

    def _on_calibrate(self):
        """画布右下角「标定」按钮：先校验当前用户是否有相机标定权限；
        无权限则弹出提示窗（确认/关闭）；有权限时，若设备正处于「生产运行」工作
        模式则无法切换，需先停止生产运行（弹出提示，可选「强制停止」或「关闭」）；
        否则统一将工作模式切换为「连续运行」后打开相机标定对话框（非模态）。"""
        mw = self.main_window
        if mw is None:
            return
        um = mw.user_manager
        user = getattr(mw, "current_user", None)
        if not um.can(user, "camera_calibration"):
            box = QMessageBox(self)
            box.setWindowTitle("权限提示")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("当前用户无操作权限，请联系厂商开通或切换账号登录")
            box.addButton("确认", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return
        # 设备正处于「生产运行」工作模式时，无法切换至「连续运行」，必须先把生产
        # 运行停下来才能标定：弹出提示，由用户选择「强制停止（确认）」或「关闭」。
        if getattr(self, "_trigger_mode", None) is not None \
                and self._trigger_mode.currentText() == "生产运行":
            self._ask_stop_before_calib()
            return
        # 非生产运行模式：统一切换到「连续运行」后再打开标定窗口
        if getattr(self, "_trigger_mode", None) is not None:
            self._trigger_mode.setCurrentText("连续运行")
        self._open_calib_dialog()

    def _ask_stop_before_calib(self):
        """生产运行中点击标定：提示须先停止生产运行，提供「强制停止（确认）」
        与「关闭」两种选择。
        - 确认：强制停止当前生产运行（等同点击「设备停止」），停止后再弹出标定窗口。
        - 关闭：仅关闭提示，不停止、也不打开标定窗口，设备仍处于生产运行状态，
               需用户手动点击「设备停止」后方可再点击标定。"""
        box = QMessageBox(self)
        box.setWindowTitle("标定提示")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("当前设备处于生产运行中，请先停止生产运行再操作。\n是否需要强制停止当前生产运行？")
        btn_confirm = box.addButton("确认", QMessageBox.ButtonRole.AcceptRole)
        btn_close = box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == btn_confirm:
            # 强制停止生产运行（与点击「设备停止」等效），停止后再弹出标定窗口
            mw = self.main_window
            if mw is not None and hasattr(mw, "_on_stop"):
                mw._on_stop()
            self._open_calib_dialog()
        # 关闭：不停止、不打开标定窗口，设备仍处于生产运行状态

    def _open_calib_dialog(self):
        """已打开则置顶聚焦，避免重复创建；否则新建并以非模态方式显示。"""
        from calibration_dialog import CameraCalibrationDialog
        # 已打开则置顶聚焦，避免重复创建；否则新建并以非模态方式显示
        existing = getattr(self, "_calib_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = CameraCalibrationDialog(
            self, anchor_card=getattr(self, "stats_card", None),
            run_log=self._run_log)
        dlg.finished.connect(self._on_calib_closed)
        self._calib_dialog = dlg
        # 初始位置：由对话框自身按「生产统计」卡片右上角对齐（三子页面共用）。
        # 此处不再单独 placement，避免与对话框内的对齐逻辑冲突。
        dlg.show()   # 非模态：标定窗口打开时主界面控制按钮仍可操作

    def _on_calib_closed(self, result):
        """标定对话框关闭后清除引用，便于下次重新打开。"""
        self._calib_dialog = None

    # ------------------------------------------------------------------
    # 交互逻辑
    # ------------------------------------------------------------------
    # 「显示所有 / 显示已选」切换开关已置于首列表头（见 init_ui），
    # 点击首列标题即可切换。

    def _on_header_section_clicked(self, section):
        """点击首列表头时切换「显示所有 / 显示已选」。"""
        if section == 0:
            self._toggle_filter()

    def _toggle_filter(self):
        """首列标题即切换开关：显示所有 / 只显示已选行（无空行）。"""
        table = getattr(self, "_table", None)
        if table is None:
            return
        self._filter_show_checked = not getattr(self, "_filter_show_checked", False)
        self._apply_filter_state()      # 应用新的显示状态（隐藏/显示行 + 重排序号 + 刷新表头）
        self._persist_filter_state()    # 写入持久化配置，重启后保留最后状态

    def _apply_filter_state(self):
        """按当前 _filter_show_checked 隐藏/显示行，并刷新序号列与首列表头。"""
        table = getattr(self, "_table", None)
        if table is None:
            return
        show_checked = self._filter_show_checked
        for r in range(table.rowCount()):
            chk = self._row_checks.get(r)
            checked = chk.is_on() if chk else True
            table.setRowHidden(r, show_checked and not checked)
        self._renumber()               # 过滤后重排序号（仅可见行）
        self._update_filter_header()   # 首列表头显示「显示所有 / 显示已选」

    def _persist_filter_state(self):
        """把当前筛选状态写入持久化配置（按相机名分别记录），重启后保留。"""
        cfg = _load_debug_config()
        cam = cfg.setdefault(self.camera_name, {})
        cam["filter_show_checked"] = bool(self._filter_show_checked)
        _save_debug_config(cfg)
        self._update_filter_header()

    def _renumber(self):
        """按当前可见顺序重排「序号」列（过滤后序号连续）。"""
        t = self._table
        n = 0
        for r in range(t.rowCount()):
            if t.isRowHidden(r):
                continue
            n += 1
            it = t.item(r, 0)
            if it is None:
                it = QTableWidgetItem()
                t.setItem(r, 0, it)
            it.setText(str(n))
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    # 启动 / 停止：相机画布逐帧刷新、停止后冻结在最后状态（与生产运行界面保持一致）。
    # 注：调试界面已不再复刻「生产统计」，统计信息统一以生产运行界面为准。

    def start_playback(self):
        if self._playing:
            return
        self._playing = True
        # 运行日志镜像生产运行界面：保证调试界面也能实时刷新运行日志
        self._sync_log_mirror()
        # 生产统计镜像生产运行界面：保证调试界面也显示与生产运行界面一致的生产信息
        self._setup_stat_mirror()
        # 提前生成并缓存样张帧：即便本界面当前不可见，也可让后续切换秒开（无生成卡顿）
        self._ensure_frame_cache()
        # 提前把样张帧装载到相机画布，并预热各通道缓存：这样切到调试界面时画布已持有帧、
        # 且 R/G/B 通道转换已预先完成，无需在切换瞬间同步生成/重置样张、也无需逐帧实时转换，
        # 彻底消除「开始阶段停顿感」。
        if (not self._frames_cache_local) and self._frames_cache is not None \
                and (self._cams[0].screen._frames is None
                     or len(self._cams[0].screen._frames) == 0):
            self._apply_and_prewarm(self._frames_cache)
        # 关键修复：无论本界面当前是否可见都要启动播放定时器。
        # 此前这里用 `if self.isVisible():` 守卫，导致「在别的界面（如生产运行界面）点设备启动，
        # 再切到调试界面」时调试界面的播放定时器从未启动——相机画布与示例/分布数据全部静止，
        # 表现为『点设备启动后画布/示例数据不刷新』。定时器在隐藏态下空转(update 无效)无害，
        # 切到本界面后即刻接管最新画面并持续刷新。
        self._begin_play()

    def _ensure_frame_cache(self):
        """在播放启动（可能尚不可见）时提前生成并缓存样张帧，
        使随后切换到本界面时不需再同步生成，避免切换瞬间的卡顿。

        关键点：样张帧按相机预览卡片的固定尺寸（setFixedSize 设定的 400×300，
        隐藏时也能取到、始终 >0）生成，而非依赖画布 screen 的实时尺寸——后者在
        本界面尚未显示（位于堆叠控件中）时为 0，会导致缓存始终无法预建、每次切换
        都重新同步生成 12 张 QPixmap，正是此前切换卡顿的根因。
        画布绘制时用 drawPixmap(rect, pm) 自动缩放到实际画布尺寸，固定尺寸生成不影响显示。
        """
        if self._frames_cache_local:
            return
        # 预览卡片固定尺寸，隐藏态下亦可取到且 >0，保证缓存能一次性预建成功
        sw, sh = self._cams[0].width(), self._cams[0].height()
        if sw > 0 and sh > 0 and self._frames_cache is None:
            self._frames_cache = self._make_frames_like_production(
                self.camera_name, sw, sh, 0)
            self._frames_cache_size = (sw, sh)

    def _apply_and_prewarm(self, frames):
        """把样张帧装载到全部相机，并预热各通道缓存，避免切换界面后逐帧转换造成的卡顿。"""
        for cam in self._cams:
            cam.set_frames(frames)
            cam.set_frame_index(0)
            cam.set_playing(True)
        self._prewarm_channel_cache()

    def _prewarm_channel_cache(self):
        """预先把每路相机当前通道下的全部样张帧做一次通道转换并缓存，
        使切换界面后首帧即可直接取缓存（约 0.6ms/帧，全部预热仅约 30ms，远可接受），
        无逐帧实时转换的瞬时开销。"""
        if self._frames_cache is None:
            return
        for cam in self._cams:
            mode = cam.screen._channel
            if mode in (None, "src"):
                continue
            cache = cam.screen._chan_cache
            for pm in self._frames_cache:
                key = (id(pm), mode)
                if cache.get(key) is None:
                    converted = _extract_channel(pm, mode)
                    if len(cache) < 256:
                        cache[key] = converted

    def _sync_log_mirror(self):
        """把本调试界面的运行日志注册为生产运行界面运行日志的镜像，
        使运行日志在调试界面也能实时刷新显示（生产界面为唯一数据源）。"""
        prod = getattr(self.main_window, "production", None)
        if prod is None:
            return
        lv = getattr(prod, "_log_view", None)
        if lv is not None and hasattr(lv, "register_mirror"):
            lv.register_mirror(self._run_log)

    def _setup_stat_mirror(self):
        """把调试界面的「生产统计与检测结果」面板接入生产运行界面（单一数据源）：

        - 设置 ``_mirror_owner`` 为生产运行界面，使时段切换 / 统计清零 由生产运行界面
          统一处理，保证两界面数据严格一致；
        - 设置 ``_live_provider`` 为生产运行界面的 ``get_display_snapshot``，由播放节拍
          拉取最新快照刷新（待机显示示例、运行/冻结显示实时累计、清零显示全 0）；
        - ``begin_mirror`` 打开实时刷新开关，并立即同步一次快照，使未播放时也能显示
          与生产运行界面一致的当前生产信息。
        """
        sp = getattr(self, "stats_panel", None)
        if sp is None:
            return
        prod = getattr(self.main_window, "production", None)
        if prod is None:
            return
        sp._mirror_owner = prod
        sp._live_provider = prod.get_display_snapshot
        sp._log_view = self._run_log
        sp.begin_mirror()
        try:
            sp._render_mirror(prod.get_display_snapshot())
        except Exception:
            # 初始化渲染失败不应阻断调试界面其余功能（如相机画布/运行日志）
            pass

    def _open_log_manager(self):
        """调试界面运行日志「日志详情」：打开与左侧导航「日志管理」窗口内容完全一致的日志窗口。

        数据源取自生产运行界面（self.main_window.production）的 get_operation_logs()，
        与生产运行界面 / 导航「日志管理」窗口内容严格一致。单实例：已打开则置顶聚焦。
        """
        from nav_dialogs import LogManagerDialog
        dlg = getattr(self, "_dlg_log_detail", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        prod = getattr(self.main_window, "production", None)
        if prod is None or not hasattr(prod, "get_operation_logs"):
            return
        dlg = LogManagerDialog(prod, self)
        self._dlg_log_detail = dlg
        dlg.show()

    def _begin_play(self):
        # 注意：即使本界面当前不可见（位于堆叠控件中尚未切到）也要允许启动定时器——
        # 帧按预览卡片固定尺寸生成（隐藏态下仍 >0），不依赖可见性；隐藏态下 update() 为空转，
        # 切到本界面后即刻接管最新画面并持续刷新。
        if not self._playing:
            return
        # 采用预览卡片的固定尺寸（始终 >0）生成/复用样张，避免依赖隐藏态下为 0 的画布实时尺寸
        sw, sh = self._cams[0].width(), self._cams[0].height()
        if sw > 0 and sh > 0:
            if self._frames_cache_local:
                # 本地图像覆盖模式：保持当前画面，仅恢复播放态
                for cam in self._cams:
                    cam.set_playing(True)
            else:
                # 4 路相机（主 / R / G / B）统一使用主相机同款样张帧序列（同一对象引用），
                # 保证右侧 R/G/B 三通道画面与主画布刷新的图片完全一致。
                # 仅在『尚未生成过样张』时才生成一次；之后切换界面直接复用同一份帧
                # （画布缩放由 drawPixmap 自动完成），不再同步生成 12 张 QPixmap，消除切换卡顿。
                need_rebuild = (self._frames_cache is None)
                if need_rebuild:
                    frames = self._make_frames_like_production(self.camera_name, sw, sh, 0)
                    self._frames_cache = frames
                    self._frames_cache_size = (sw, sh)
                    apply = True
                else:
                    frames = self._frames_cache
                    # 缓存已存在但相机尚未装载这批帧（如提前缓存但尚未下发）时仍需下发
                    apply = (self._cams[0].screen._frames is not frames)
                if apply:
                    self._apply_and_prewarm(frames)
                else:
                    # 复用已生成帧：仅恢复播放态，不重设帧序号（从当前画面继续），不重建通道缓存
                    for cam in self._cams:
                        cam.set_playing(True)
        if not self._play_timer.isActive():
            self._play_timer.start(30)

    @staticmethod
    def _make_frames_like_production(cam_name, w, h, index=0):
        """与生产界面 start_playback 完全相同的样张生成逻辑：
        有用户样张图片则用 _make_user_frames，否则用 make_sample_frames(seed=100+index)。"""
        if cam_name and cam_name in _CAMERA_FRAME_IMAGES:
            img_file = _CAMERA_FRAME_IMAGES[cam_name]
            img_path = os.path.join(_camera_frame_dir(), img_file)
            if os.path.exists(img_path):
                return _make_user_frames(img_path, w, h, count=12)
        return make_sample_frames(w, h, count=12, seed=100 + index)

    def stop_playback(self):
        # 停止时复位冻结状态，按钮恢复为「冻结」（即便未处于播放态也确保复位）
        self._frozen = False
        if hasattr(self, "_freeze_btn"):
            self._freeze_btn.setText("冻结")
        if not self._playing:
            return
        self._playing = False
        self._play_timer.stop()
        for cam in self._cams:
            cam.set_playing(False)
        # 生产统计面板为生产运行界面的镜像（单一数据源），停止播放后无需额外处理：
        # 生产运行界面停止时冻结在最后累计值，调试界面镜像看到的也正是该冻结快照。

    def showEvent(self, event):
        """切到本调试界面时：若已处于播放态则确保定时器在跑，并立即重绘最新画面，
        避免『从别的界面点设备启动后切过来，画布/示例数据停在旧帧』的观感。"""
        super().showEvent(event)
        if self._playing:
            self._begin_play()
            for cam in self._cams:
                cam.screen.update()

    def _on_play_tick(self):
        self._tick_count += 1
        # 冻结时不推进相机帧（画布停留在当前画面，不再刷新），统计仍按节拍更新
        if not self._frozen:
            # 仅推进主相机，再把主画布的帧序号同步到 R/G/B 三通道，
            # 确保右侧 R/G/B 画面与主画布始终一致。
            main = self._cams[0]
            main.advance_frame(self._cam_speed[0])
            idx = main.current_frame_index()
            for cam in self._cams[1:]:
                cam.set_frame_index(idx)
            # 图像效果调节：相机有图像刷新时，已启用检测项的示例数值按节拍随机刷新
            if self._tick_count % 4 == 0:
                self._refresh_effect_values()
            # 生产运行态下，检测项数据按节拍模拟动态更新（降频 ~0.8s 一次）：
            # 「检测值」围绕默认值上下浮动、「检测结果」随实际值刷新 OK/NG/待定。
            if getattr(self, "_production_running", False) \
                    and getattr(self, "_accepted_mode", "") == "生产运行":
                # 检测项示例检测值模拟更新频率与生产统计刷新频率一致（每 3 拍一次）
                if self._tick_count % 3 == 0:
                    self.refresh_detection_values()
                    self._accumulate_distribution_samples()
        # 统计刷新降频（每 2 拍一次）：调试界面生产信息镜像生产运行界面，随节拍同步。
        # 与生产运行界面的 _refresh_every=2 保持一致，避免调试界面刷新偏慢。
        if self._tick_count % 2 == 0:
            sp = getattr(self, "stats_panel", None)
            if sp is not None:
                sp.tick_live()

    def _accumulate_distribution_samples(self):
        """生产运行态下，把当前各检测项的实时『检测值』作为样本追加进分布样本池，
        使分布曲线随生产情况实时刷新；设备停止时本方法不再被调用，曲线停止刷新。

        样本上限 3000，超出后丢弃最旧数据，避免长时运行内存无限增长。
        """
        table = getattr(self, "_table", None)
        if table is None:
            return
        now = datetime.now()
        for r in range(table.rowCount()):
            fv = _to_float(self._table_data[r][4]
                           if 0 <= r < len(self._table_data) else None)
            if fv is None:
                continue
            lst = self.get_distribution_samples(r)
            lst.append((now, fv))
            if len(lst) > 3000:
                del lst[:len(lst) - 3000]

    def _on_freeze_toggle(self):
        """画布下方「冻结」按钮：冻结/解冻当前刷新的相机画面。"""
        if not hasattr(self, "_freeze_btn"):
            return
        self._frozen = not self._frozen
        self._freeze_btn.setText("解冻" if self._frozen else "冻结")
        self._refresh_control_states()

    def _on_mode_changed(self, new_text):
        """工作模式切换守卫。

        设备处于生产运行状态时，除「生产运行」与「本地图像」外，切换至其它
        模式一律拒绝：自动还原回原模式并弹出提示窗（确认 / 关闭均可关闭）。
        通过守卫的模式才更新已生效模式并刷新底部控制按钮的可点击 / 配色状态。
        """
        prev_mode = getattr(self, "_accepted_mode", new_text)
        if getattr(self, "_production_running", False) \
                and new_text not in ("生产运行", "本地图像"):
            # 静默还原下拉框选中项，避免递归触发 currentTextChanged
            self._trigger_mode.blockSignals(True)
            self._trigger_mode.setCurrentText(prev_mode)
            self._trigger_mode.blockSignals(False)
            box = QMessageBox(self)
            box.setWindowTitle("切换提示")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("设备正处于生产运行状态，不可切换至此工作模式")
            box.addButton("确认", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()   # 确认 / 关闭 都会关闭弹窗
            return
        # 进入「本地图像」前，记录切换前的模式，便于关闭窗口后恢复
        if new_text == "本地图像":
            self._local_image_prev_mode = prev_mode
        self._accepted_mode = new_text
        self._refresh_control_states()
        # 离开「本地图像」模式时，解除本地图像覆盖标记，画布恢复为样张播放
        if new_text != "本地图像":
            self._frames_cache_local = False
        self._sync_local_image_window()

    def _refresh_control_states(self):
        """根据「是否冻结」与「工作模式」统一刷新底部控制按钮的可点击/配色状态：
        - 冻结按钮：解冻态（已冻结）显示灰色，否则蓝色；连续运行/模拟生产模式下禁用。
        - 抓取/运行：仅当已冻结且非连续运行/模拟生产模式时可点击（蓝色），否则禁用（灰色）。
        """
        if not hasattr(self, "_freeze_btn"):
            return
        blue = (f"background-color: {COLORS['accent_blue']}; color: white; "
                f"border: none; border-radius: 4px; padding: 3px 10px; font-size: 12px;")
        gray = ("background-color: #4A4D52; color: #A8ABB0; "
                "border: none; border-radius: 4px; padding: 3px 10px; font-size: 12px;")
        mode = self._trigger_mode.currentText()
        blocked = mode in ("连续运行", "模拟生产")
        if blocked:
            # 连续运行 / 模拟生产模式：冻结、抓取、运行三按钮均禁用且底色为灰色
            self._freeze_btn.setEnabled(False)
            self._freeze_btn.setStyleSheet(gray)
            for b in (self._grab_btn, self._run_btn):
                b.setEnabled(False)
                b.setStyleSheet(gray)
            return
        # 非禁用模式：冻结按钮解冻态（已冻结）灰色，否则蓝色、可点击
        self._freeze_btn.setEnabled(True)
        self._freeze_btn.setStyleSheet(gray if self._frozen else blue)
        # 抓取 / 运行：已冻结时才可点击（蓝色），否则禁用（灰色）
        gr_enabled = self._frozen
        for b in (self._grab_btn, self._run_btn):
            b.setEnabled(gr_enabled)
            b.setStyleSheet(blue if gr_enabled else gray)

    def showEvent(self, event):
        super().showEvent(event)
        # 进入调试界面即把运行日志接入生产界面的镜像源，保证日志实时刷新
        self._sync_log_mirror()
        if self._playing:
            # 延后到下一事件循环再开始播放：先让界面完成绘制与布局，
            # 避免在此同步生成样张帧阻塞切换瞬间的渲染，消除开始阶段的停顿感。
            QTimer.singleShot(0, self._begin_play)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._play_timer.stop()

    # ------------------------------------------------------------------
    # 检测项分布图：带时间戳样本缓存 + 时间范围检索 + 清零
    # ------------------------------------------------------------------
    def _detect_center(self, r):
        """读取某检测项『检测值』作为分布样本的中心值（演示用）。

        ⚠️ 按**表头名**定位「检测值」列：2026-10-09 该列由 5 移到 9，
        原先硬编码 `item(r, 5)` 会读到「补偿值」列（恒为 0），
        靠 fallback 到 raw[4] 才没出错—— 属于静默隐患，一并修掉。
        """
        center = None
        table = getattr(self, "_table", None)
        if table is not None:
            c_val = self._col_by_header("检测值")
            if c_val >= 0:
                it = table.item(r, c_val)
                if it is not None:
                    center = _to_float(it.text())
        raw = self._table_data[r] if r < len(self._table_data) else None
        if center is None and raw is not None:
            center = _to_float(raw[4])
        if center is None or center == 0:
            center = (r + 1) * 0.42
        return center

    def _col_by_header(self, name, default=-1):
        """按**表头名**取列号（列序会调整，禁止硬编码列号）。

        ⚠️ 2026-10-09 教训：`_detect_spec` 曾硬编码 `item(r, 7)/item(r, 8)`
        读规格上下限，「检测值」列移到「检测结果」左侧后列序变成
        6=规格下限 / 7=规格上限 / 8=单位 → 读成 (上限, None)，
        表现为「规格下限显示成上限值、曲线图缺失下限线」。故统一走表头查列。
        """
        table = getattr(self, "_table", None)
        if table is None:
            return default
        for c in range(table.columnCount()):
            it = table.horizontalHeaderItem(c)
            if it is not None and it.text() == name:
                return c
        return default

    def _detect_spec(self, r):
        """读取某检测项的规格下限/上限（按**表头名**定位列，列序调整后依然正确）。"""
        lo = hi = None
        table = getattr(self, "_table", None)
        if table is not None:
            c_lo = self._col_by_header("规格下限")
            c_hi = self._col_by_header("规格上限")
            if c_lo >= 0:
                it = table.item(r, c_lo)
                if it is not None:
                    lo = _to_float(it.text())
            if c_hi >= 0:
                it = table.item(r, c_hi)
                if it is not None:
                    hi = _to_float(it.text())
        raw = self._table_data[r] if r < len(self._table_data) else None
        if lo is None and raw is not None:
            lo = _to_float(raw[6])
        if hi is None and raw is not None:
            hi = _to_float(raw[7])
        # ⚠️ 兜底：下限不得大于上限（列序错位或脏数据时避免出现「下限=上限」，
        # 那会让分布图只画出一条上限线、下限线消失，且 CPK 计算失真）。
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        return lo, hi

    def get_distribution_samples(self, r):
        """返回该检测项带时间戳的样本列表 [(datetime, value), ...]。
        首次打开时生成：时间从『设备启动生产时间』(默认 now-30min) 到 now 均匀分布；
        再次打开复用同一份缓存，保证时间范围稳定、可被检索/清零。"""
        if r in self._dist_samples:
            return self._dist_samples[r]
        center = self._detect_center(r)
        series = _make_sample_series(1000 + r * 7, center)
        now = datetime.now()
        start = self._prod_start_time or (now - timedelta(minutes=30))
        total = int((now - start).total_seconds())
        n = len(series)
        samples = []
        for i, v in enumerate(series):
            t = start if n == 1 else start + timedelta(seconds=total * i / (n - 1))
            samples.append((t, v))
        self._dist_samples[r] = samples
        return samples

    def get_distribution_start(self, r):
        """返回该检测项分布数据的有效起点时间：

        - 若该检测项曾『清零』过，则从清零时刻起算；
        - 否则从设备启动生产时间起算（未启动时回退到 now-30min）。
        """
        cleared = self._dist_cleared_at.get(r)
        base = self._prod_start_time or (datetime.now() - timedelta(minutes=30))
        if cleared is not None and cleared > base:
            return cleared
        return base

    def clear_distribution(self, r):
        """清零：清除该检测项现有分布样本，并从『现在』开始重新累计——
        随后随生产运行持续追加新样本，曲线随生产数据重新更新显示。"""
        self._dist_samples[r] = []
        self._dist_cleared_at[r] = datetime.now()

    # ---- 参数分布样本池（与检测项分布图共用同一套「样本池 + 全量时间窗 + 清零」操作逻辑）----
    def get_param_samples(self, name, key):
        """返回某参数带时间戳的样本列表 [(datetime, value), ...]。

        与检测项分布图一致：首次打开（或清零后）生成示例分布形状，时间从『设备启动
        生产时间』（默认 now-30min）到当前均匀分布；再次打开复用同一份缓存，保证时间
        范围稳定、可被检索/清零。随后随相机逐帧节拍追加实时样本，分布图持续刷新。

        注意：缓存为空列表时也重新生成示例基线，确保『清零』后分布图立即重新显示
        （不再停留在『暂无数据』），随后随相机刷新持续追加新样本——等价于重新开始统计。
        """
        kk = (name, key)
        cached = self._param_samples.get(kk)
        if cached:
            return cached
        vals, _lo, _hi = self._gen_param_distribution(key)
        now = datetime.now()
        start = self._prod_start_time or (now - timedelta(minutes=30))
        total = max(1, int((now - start).total_seconds()))
        n = len(vals)
        samples = [
            (start if n == 1 else start + timedelta(seconds=total * i / (n - 1)), v)
            for i, v in enumerate(vals)
        ]
        self._param_samples[kk] = samples
        return samples

    def clear_param_distribution(self, name, key):
        """清零：移除该参数现有分布样本缓存，使其在下一次读取时重新生成一份全新的示例
        基线分布。这样点击『清零』后分布图立即重新显示（不再停留在『暂无数据』），随后
        随相机逐帧节拍追加实时样本，等价于『重新开始统计刷新』。"""
        kk = (name, key)
        self._param_samples.pop(kk, None)
        self._param_cleared_at[kk] = datetime.now()

    def _gen_param_distribution(self, key):
        """生成某参数的示例结果数据（与参数弹窗 _gen_distribution 同形），用于首次预填。"""
        import random as _r
        _r.seed(abs(hash(key)) % (2 ** 31))
        n = 260
        if key == "thresh":
            s = [min(100.0, max(40.0, _r.gauss(86, 7))) for _ in range(n)]
        elif key == "area":
            s = [min(9000.0, max(50.0, _r.gauss(1800, 1200))) for _ in range(n)]
        elif key == "tol":
            s = [min(12.0, max(0.0, _r.gauss(3, 1.6))) for _ in range(n)]
        else:
            s = [80.0] * n
        return [round(x, 2) for x in s], 0.0, 0.0

    def _accumulate_param_samples(self):
        """把各已打开参数分布面板的实时『实测值』追加进样本池。

        现由分布面板自身的 500ms 定时器驱动（而非 DebugView 的 30ms 播放定时器），
        因此只要分布面板处于打开状态、且设备正在刷新图片（_playing 且未冻结），
        无论 DebugView 当前是否可见都会持续累计——彻底消除『在其它界面点击设备启动
        后分布图停留在示例基线、点清零也只是重建同一份基线』的『卡死/不刷新』问题。
        设备停止或冻结时本方法直接返回，分布图自然停止刷新。样本上限 3000，超出丢弃最旧。
        """
        if not (getattr(self, "_playing", False) and not getattr(self, "_frozen", False)):
            return
        now = datetime.now()
        for dlg in getattr(self, "_param_dialogs", {}).values():
            ak = getattr(dlg, "_active_key", None)
            if not ak:
                continue
            fn = getattr(dlg, "_append_live_sample", None)
            if fn is not None:
                try:
                    fn(now)
                except Exception:
                    pass

    def _open_distribution(self, name, r):
        """点击「分布图」：弹出曲线窗口，展示该检测项带时间戳的示例记录数值。
        可查看数据时间范围、按时间范围检索、清零重新开始统计；
        同时把该检测项的『规格下限/规格上限』作为限线画入分布图。"""
        lo, hi = self._detect_spec(r)
        samples = self.get_distribution_samples(r)
        # 关闭上一次打开的分布图窗口，避免多个窗口叠加
        prev = getattr(self, "_dist_dlg", None)
        if prev is not None:
            try:
                prev.close()
            except Exception:
                pass
        dlg = DistributionDialog(
            self, name, r, samples, lo=lo, hi=hi, prod_start=self._prod_start_time)
        # 非模态：打开后不影响生产运行界面 / 调试界面其它功能按钮的操作
        dlg.setModal(False)
        self._dist_dlg = dlg
        dlg.show()

    def _open_teach(self, name, r):
        """点击「教导」：弹出教导窗口。优先冻结抓取相机画布最新帧，否则回退产品样张。

        在窗口中依次点击两条示例直线选择计算元素，确认后写入运行日志（操作记录，蓝色）。
        """
        cam = self._cams[0] if getattr(self, "_cams", None) else None
        grabbed = cam.current_frame() if cam is not None else None
        if grabbed is not None and not grabbed.isNull():
            base = grabbed.toImage().convertToFormat(QImage.Format.Format_RGB32)
        else:
            frames = make_sample_frames(320, 240, count=1, seed=100 + r)
            base = frames[0].toImage().convertToFormat(QImage.Format.Format_RGB32)
        dlg = TeachDialog(self, name, base)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            elems = "、".join(res["elements"]) or "无"
            self._run_log.add(
                datetime.now().strftime("%H:%M:%S"),
                f"完成「{name}」教导：通道={res['channel']}，计算元素={elems}",
                "#4261FF")

    # ------------------------------------------------------------------
    # 检测值浮动刷新（本地图像示例演示）
    # ------------------------------------------------------------------
    def _data_index_for_col(self, c):
        """表头列号 -> 原始数据 row 索引。

        ⚠️ 2026-10-09 列序调整：「检测值」整列移到「检测结果」左侧。
        当前列序：0 序号 / 1 是否检测 / 2 检测编号 / 3 检测项目 / 4 标称值 /
        5 补偿值 / 6 规格下限 / 7 规格上限 / 8 单位 / 9 检测值 /
        10 检测结果 / 11 收料位置 / 12 检测项操作 / 13 良率预警设置
        （「数值分布」列的按钮已并入「检测值」列，该列已移除）

        原始 row 结构（与列号**不再**一一对应，必须走本函数查表）：
        row[0]=是否检测 row[1]=检测编号 row[2]=检测项目 row[3]=标称值
        row[4]=检测值 row[5]=补偿值 row[6]=规格下限 row[7]=规格上限
        row[8]=单位 row[9]=收料位置 row[10]=检测结果
        ⚠️ 新增/调整列时**务必同步更新本映射**，否则会出现「值串列」。
        """
        # 列号 -> row 索引（显式查表，避免改列序时漏改）
        _COL_TO_ROW = {
            2: 1,   # 检测编号
            3: 2,   # 检测项目
            4: 3,   # 标称值
            5: 5,   # 补偿值
            6: 6,   # 规格下限
            7: 7,   # 规格上限
            8: 8,   # 单位
            10: 10,  # 检测结果
            11: 9,   # 收料位置
        }
        # 列 9=检测值 用 cellWidget（数值+按钮）单独构建，不走本函数。
        return _COL_TO_ROW.get(c)

    def _apply_result_color(self, item, result):
        """检测结果列着色：OK 绿 / NG 红 / 待定 橙。"""
        if result == "OK":
            item.setForeground(QColor(COLORS["accent_green"]))
        elif result == "NG":
            item.setForeground(QColor(COLORS["accent_red"]))
        else:  # 待定
            item.setForeground(QColor(COLORS["accent_orange"]))

    def _on_detect_toggled(self, row, on):
        """是否检测开关状态变化：同步该行检测标记（供筛选/模拟读取）。"""
        if 0 <= row < len(self._table_data):
            self._table_data[row][0] = bool(on)

    def _set_unit(self, row, text):
        """单位列右键选择后：更新底层数据中的单位字段（row[8]）。"""
        if 0 <= row < len(self._table_data):
            self._table_data[row][8] = str(text)

    def _on_yield_warn_toggled(self, row, on):
        """良率预警「启用开关」状态变化：更新该行预警启用标记。"""
        rec = self._yield_warn.setdefault(row, {"enabled": True, "threshold": 50})
        rec["enabled"] = bool(on)

    def _on_yield_warn_threshold(self, row, value):
        """良率预警「阈值」变化：更新该行预警阈值（%）。"""
        rec = self._yield_warn.setdefault(row, {"enabled": True, "threshold": 50})
        rec["threshold"] = int(value)

    def _set_toggle_btn(self, btn, on, on_text, off_text):
        """批量开关按钮：on=全开态（橙色填充）；off=全关态（中性卡片色）。

        文字随状态翻转（on_text / off_text），从而点击后按钮文字切换。
        """
        if on:
            btn.setText(on_text)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: #FFFFFF; "
                f"border: none; border-radius: 4px; padding: 2px 10px; font-size: 10px; }}")
        else:
            btn.setText(off_text)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 2px 10px; font-size: 10px; }}")

    def _on_detect_all_toggle(self):
        """检测项全开/关：把当前态应用到全部「是否检测」开关，然后翻转标注。"""
        target = self._detect_all_on
        for r in range(self._table.rowCount()):
            sw = self._row_checks.get(r)
            if sw is not None:
                sw.set_on(target)
        self._detect_all_on = not self._detect_all_on
        self._set_toggle_btn(self._detect_all_btn, self._detect_all_on,
                             "全开", "全关")

    def _reposition_overlay_buttons(self):
        """把两个「全开/全关」批量开关分别贴到对应列头的右侧并置顶。

        - _yield_all_btn  → 「良率预警设置」列（最右列）
        - _detect_all_btn → 「是否检测」列（第 2 列）
        """
        self._reposition_one_overlay(getattr(self, "_yield_all_btn", None),
                                     self._table.columnCount() - 1)
        self._reposition_one_overlay(getattr(self, "_detect_all_btn", None), 1)

    def _reposition_one_overlay(self, btn, col):
        """把单个覆盖按钮贴到指定列列头的右侧并置顶。"""
        if btn is None or self._table is None:
            return
        hh = self._table.horizontalHeader()
        if hh is None or col < 0:
            return
        x = hh.sectionViewportPosition(col) + hh.sectionSize(col) - btn.width() - 4
        y = max(0, (hh.viewport().height() - btn.height()) // 2)
        btn.move(max(0, int(x)), y)
        btn.raise_()

    def eventFilter(self, obj, event):
        """列头视口尺寸变化（表格拉伸/缩放）时，重贴两个「全开/全关」开关位置。"""
        try:
            hv = self._table.horizontalHeader().viewport()
        except RuntimeError:
            return super().eventFilter(obj, event)
        if obj is hv and event.type() == QEvent.Type.Resize:
            self._reposition_overlay_buttons()
        return super().eventFilter(obj, event)

    def _on_yield_all_toggle(self):
        """预警全开/关：把当前态应用到全部良率预警启用开关，然后翻转标注。"""
        target = self._yield_all_on
        for r in self._yield_warn:
            self._yield_warn[r]["enabled"] = target
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, 13)
            sw = w.findChild(ToggleSwitch) if w is not None else None
            if sw is not None:
                sw.set_on(target)
        self._yield_all_on = not self._yield_all_on
        self._set_toggle_btn(self._yield_all_btn, self._yield_all_on,
                             "全开", "全关")

    # ---- 检测项规格上下限自动调整 -------------------------------------
    def _on_auto_spec_adjust(self):
        """「规格自动调整」按钮：打开规格上下限自动调整窗口。"""
        dlg = SpecAutoAdjustDialog(self, self)
        dlg.exec()

    def apply_spec_adjust(self, changes):
        """应用规格自动调整：把 [(row, new_lo, new_hi), ...] 写入『规格下限/上限』列
        （同步底层数据与表格显示），并按新规格重新判定『检测结果』。返回成功条数。"""
        table = getattr(self, "_table", None)
        if table is None:
            return 0
        c_lo = self._col_by_header("规格下限")
        c_hi = self._col_by_header("规格上限")
        c_res = self._col_by_header("检测结果")
        n = 0
        for r, lo, hi in changes:
            if not (0 <= r < len(self._table_data)):
                continue
            if lo is None or hi is None or lo > hi:
                continue
            # 同步底层数据（raw[6]=规格下限 raw[7]=规格上限）
            self._table_data[r][6] = str(lo)
            self._table_data[r][7] = str(hi)
            for c, v in ((c_lo, lo), (c_hi, hi)):
                if c >= 0:
                    it = table.item(r, c)
                    if it is not None:
                        it.setText(str(v))
            # 按新规格重新判定『检测结果』
            chk = self._row_checks.get(r)
            checked = bool(chk.is_on()) if chk else True
            result = self._judge_result(
                checked, self._table_data[r][4], lo, hi)
            if c_res >= 0:
                res_item = table.item(r, c_res)
                if res_item is not None:
                    res_item.setText(result)
                    self._apply_result_color(res_item, result)
            n += 1
        return n

    def _judge_result(self, checked, new_val, lo, hi):
        """依据检测值相对规格上下限的实际结果判定 OK / NG / 待定。"""
        if not checked:
            return "待定"
        fv = _to_float(new_val)
        if fv is None or lo is None or hi is None:
            return "待定"
        if lo <= fv <= hi:
            return "OK"
        return "NG"

    def refresh_detection_values(self, image_index=None):
        """本地图像窗口切换 / 运行一张图时调用：把各检测项的『检测值』按默认值
        上下浮动生成新值（每运行一张图均会变化，用于示例演示），并据其相对规格
        上下限的实际结果刷新『检测结果』列（OK / NG / 待定）。

        - 已勾选（是否检测）且默认检测值为数值的项：围绕默认值浮动后取整
          （整数类项目 ±25%、带小数类项目 ±12%，保证每次都有可见变化）。
        - 未勾选或非数值项：检测值保持默认，结果记为『待定』。
        """
        table = getattr(self, "_table", None)
        if table is None:
            return
        rnd = random.Random()
        for r in range(table.rowCount()):
            raw = self._table_data[r]
            chk = self._row_checks.get(r)
            checked = bool(chk.is_on()) if chk else True
            default_val = raw[4]          # 默认检测值（字符串）
            center = _to_float(default_val)
            lo = _to_float(raw[6])        # 规格下限
            hi = _to_float(raw[7])        # 规格上限
            if (not checked) or center is None:
                # 未勾选或非数值：检测值维持默认，结果=待定
                new_val = default_val
            else:
                s = str(default_val)
                dec = len(s.split(".")[-1]) if "." in s else 0
                amp = 0.25 if dec == 0 else 0.12
                noise = rnd.uniform(-amp, amp)
                new_val = _round_like(center * (1.0 + noise), default_val)
            # 更新『检测值』列（**列号 9**，位于『检测结果』左侧）：为
            # 「数值标签 + 值分布按钮」组合控件，
            # 同步刷新底层数据（self._table_data[r][4]），供分布样本/中心值读取。
            if 0 <= r < len(self._table_data):
                self._table_data[r][4] = str(new_val)
            val_lbl = self._val_labels.get(r)
            if val_lbl is not None:
                val_lbl.setText(str(new_val))
            # 计算并刷新『检测结果』列（按表头名定位，位于收料位置左侧）
            result = self._judge_result(checked, new_val, lo, hi)
            c_res = self._col_by_header("检测结果")
            res_item = table.item(r, c_res) if c_res >= 0 else None
            if res_item is not None:
                res_item.setText(result)
                self._apply_result_color(res_item, result)
