import json
import math
import os
import sys
import random
import time
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QDialog, QInputDialog, QScrollArea, QFrame,
    QStackedWidget, QStackedLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QApplication, QMenu, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QColor, QFont, QFontMetrics, QPainter, QPixmap, QIcon, QPen, QBrush, QAction

from styles import COLORS, register_restyle
from components import (
    FloatPanel, EditableKpiGrid, DonutChart, LogView, CameraPreview, StateToggle,
    make_sample_frames
)
from alarm_config import (
    BIN_KEYS, VALVE_KEYS, SQ_KEYS, sq_threshold,
    bin_full_threshold, valve_life_threshold,
    alarm_duration_ms, alarm_delay_ms,
    feature_auto_clear, feature_mis_wrong, mis_wrong_plan, mis_wrong_threshold,
    feature_mis_miss, mis_miss_plan, mis_miss_threshold,
    feature_door_alarm, feature_door_mode, feature_buzzer,
    feature_bin_taken_timeout, bin_taken_timeout_ms, bin_taken_timeout_plan, feature_bin_taken_timeout_mode,
    feature_bin_full_alarm, bin_full_plan, bin_full_pct,
    feature_bin_full_stop, bin_full_stop_pct,
    state_plan_by_alias,
    feature_cont_mix, cont_mix_threshold,
    feature_cont_tilt, cont_tilt_threshold,
    feature_cont_stick, cont_stick_threshold,
    feature_estop_alarm, estop_mode,
    valve_alarm_pct, valve_alarm_plan, valve_stop_pct,
    feature_door_alarm_plan, sq_plan,
    feature_ion_fan_alarm, ion_fan_plan,
)

# 设备状态实时行的显示名（报警 / 恢复日志用，避免「旋转盘」与「转盘速度」混用）
_LIVE_DISP = {
    "总气源": "总气源",
    "旋转盘": "转盘速度",
    "负压": "负压",
    "静电": "静电",
}
# 料盒取出状态文案：False=未取出，True=取出
BIN_STATE_TEXT = {False: "未取出", True: "取出"}

# 急停按钮（示例演示）：常态「未开启」，仅以极低概率随机触发一次。
# 触发时刻取 5~60 分钟的三角分布（众数约 10 分钟）：
# 最快也要运行 5 分钟才可能触发，多数在 10 分钟左右，偶尔要 1 小时。
_ESTOP_MIN_MINUTES = 5.0
_ESTOP_MAX_MINUTES = 60.0
_ESTOP_PEAK_MINUTES = 10.0

# 实时良品率的「比例反馈」增益：每批良品概率按（目标良率 − 已累计良率）×该增益修正，
# 使显示良率稳定在 95~97%（小样本纯随机抽样会漂出该区间）。
_YIELD_FEEDBACK = 2.5

# 离子风扇异常出现概率（每个运行节拍，约 33 拍/秒）→ ≈ 每 1 分钟出现一次异常（演示节奏）
_ION_FAN_TRIGGER_P = 0.0005

# 播放节拍时长（秒）：与 _play_timer.start(30) 对应，用于把「供料速度 Pcs/Min」折算为每节拍产品数
_PLAY_TICK_SECONDS = 0.03

# 「统计配置 / 统计清零」按钮统一样式：蓝色底、白字、点击后不变色
_BLUE_BTN_STYLE = (
    f"background-color: {COLORS['accent_blue']}; color: white; "
    f"border: none; border-radius: 4px; font-size: 11px; "
    f"padding: 4px 10px;"
)

# 速度 / 良率报警项恢复日志的中文名
_SQ_RECOVERY = {
    "detect_low": "检测速度过低",
    "detect_high": "检测速度过高",
    "good_low": "综合良率低",
    "cam_yield_low": "单相机良率低",
    "recheck_high": "重检率过高",
}

# 各电磁阀每次统计刷新（约每 2 个播放节拍）的已用动作次数增量（次），
# 让寿命百分比在生产运行期间可见地实时增长。
VALVE_RATE = {"OK": 1.2, "NG1": 0.6, "NG2": 0.5, "RST": 0.4}

# 各料盒每次统计刷新（约每 2 个播放节拍）的累计件数增量（件），
# 让满料百分比在生产运行期间可见地实时增长（OK 基数大增量也大，其余依次冲到满料）。
BIN_RATE = {"OK": 25, "NG1": 1, "NG2": 1, "RST": 1}

# 与导航栏、调试界面保持一致的相机清单（8 路）
CAMERA_NAMES = [
    "上表面", "下表面",
    "内侧面", "外侧面",
    "后端面", "前端面",
    "飞料监测", "ZiGAA",
]
# ZiGAA 品牌展示相机：始终固定显示 ZiGAA 图片、不参与逐帧刷新（恒为最后一格）
ZIGAA_CAM_INDEX = 7


def _make_zigaa_pixmap(w, h, font_family="Microsoft YaHei") -> "QPixmap":
    """生成 ZiGAA 品牌展示图（橙底白字圆角卡片），用于相机网格固定展示位。"""
    pm = QPixmap(w, h)
    pm.fill(QColor("#15171B"))  # 与相机画布背景一致
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    m = max(6, int(min(w, h) * 0.04))
    card = QRect(m, m, w - 2 * m, h - 2 * m)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(COLORS["accent_orange"]))
    p.drawRoundedRect(card, 14, 14)
    # 白色 ZiGAA 字样居中（自适应缩放）
    text = "ZiGAA"
    margin = min(w, h) * 0.12
    max_w = w - 2 * margin
    max_h = h - 2 * margin
    font = QFont(font_family, int(min(w, h) * 0.5))
    font.setBold(True)
    p.setFont(font)
    fm = QFontMetrics(font)
    tw = fm.horizontalAdvance(text)
    th = fm.height()
    scale = min(max_w / tw, max_h / th)
    font.setPointSizeF(font.pointSizeF() * scale)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


# 用户提供的 6 路真实相机样张（前 6 路：上/下/内/外/后/前端面）
_CAMERA_FRAME_IMAGES = {
    "上表面": "上表面.png",
    "下表面": "下表面.png",
    "内侧面": "内侧面.png",
    "外侧面": "外侧面.png",
    "后端面": "后端面.png",
    "前端面": "前端面.png",
}


def _camera_frame_dir() -> str:
    """相机样张目录：开发时取项目根目录 assets/camera_frames，打包后取 exe 同级目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "camera_frames")


def _diag_dir() -> str:
    """诊断日志目录：frozen 下用 exe 所在目录(output)，源码下用项目 output/。

    关键：frozen 模式下 __file__ 指向 PyInstaller 解包目录(_internal/src/...)，
    dirname(__file__)/../output 并不是项目真正的 output/，会导致日志写到临时目录、
    真机上看不到。这里与项目既有约定(_camera_frame_dir 在 frozen 下用
    dirname(sys.executable))保持一致。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def _playback_diag_path() -> str:
    """播放链路诊断日志路径（与 startup_diag.log 同目录：output/）。"""
    return os.path.join(_diag_dir(), "playback_diag.log")


def _pd(tag: str, *parts):
    """追加写入播放链路诊断（真机复现『点设备启动后画面不刷新』用）。"""
    try:
        import datetime
        d = _diag_dir()
        os.makedirs(d, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{ts}] {tag} " + " ".join(str(p) for p in parts)
        with open(os.path.join(d, "playback_diag.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _make_user_frames(image_path: str, w: int, h: int, count: int = 12) -> list:
    """把用户提供的相机样张生成一组轻微漂移的帧，模拟真实相机的动态刷新。

    对原图进行约 5% 放大后按正弦轨迹小范围平移裁剪，保持主体可见同时产生轻微抖动/扫描感。
    """
    src = QPixmap(image_path)
    if src.isNull():
        return make_sample_frames(w, h, count=count, seed=0)
    over_w = max(8, int(w * 0.05))
    over_h = max(8, int(h * 0.05))
    big = src.scaled(
        w + over_w, h + over_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    frames = []
    for i in range(count):
        pm = QPixmap(w, h)
        pm.fill(QColor("#15171B"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        angle = i * 2 * math.pi / count
        dx = int(round(4 * math.sin(angle)))
        dy = int(round(3 * math.cos(angle)))
        sx = (big.width() - w) // 2 + dx
        sy = (big.height() - h) // 2 + dy
        p.drawPixmap(-sx, -sy, big)
        p.end()
        frames.append(pm)
    return frames

# ============ 多时段示例数据（当前运行 / 指定时间段 / 白班 / 中班 / 晚班）============
# 以基础数据按倍数缩放生成，供「统计时段」下拉切换演示。
_BASE_CAM = [
    ("相机1", 9887, 108, 5), ("相机2", 9987, 3, 10), ("相机3", 9765, 235, 0),
    ("相机4", 9934, 64, 2), ("相机5", 9876, 115, 9), ("相机6", 9875, 115, 10),
    ("相机7", 9900, 80, 5), ("相机8", 9850, 150, 15),
]
# 缺陷类型（按缺陷项统计表的所有行；新增多项后表体可滚动显示）
_DEFECT_TYPES = [
    "产品长度", "产品宽度", "端头不一", "瓷体缺损",
    "产品歪斜", "产品偏位", "产品变形", "端面漏瓷",
    "瓷体发黑", "瓷体划痕", "爬镀", "电极突出", "电极横向内延",
]
# 缺陷项饼图配色（按 _DEFECT_TYPES 顺序循环使用）
_DEFECT_COLORS = [
    "#4261FF", "#0D822B", "#C81435", "#F9AA0B", "#FF8A80",
    "#2F80ED", "#7B61FF", "#00B8A9", "#F94144", "#577590",
    "#F3722C", "#43AA8B", "#90BE6D",
]
# 各检测项（缺陷项）SPC 规格：标称值 / 规格下限 / 规格上限（仅用于「按缺陷项统计」SPC 表展示）
_DEFECT_SPEC = {
    "产品长度":     ("5.00", "4.90", "5.10"),
    "产品宽度":     ("3.20", "3.10", "3.30"),
    "端头不一":     ("0.50", "0.35", "0.65"),
    "瓷体缺损":     ("1.00", "0.85", "1.15"),
    "产品歪斜":     ("0.20", "0.10", "0.30"),
    "产品偏位":     ("0.30", "0.15", "0.45"),
    "产品变形":     ("0.10", "0.05", "0.15"),
    "端面漏瓷":     ("1.00", "0.80", "1.20"),
    "瓷体发黑":     ("0.50", "0.20", "0.80"),
    "瓷体划痕":     ("0.30", "0.15", "0.45"),
    "爬镀":         ("0.40", "0.25", "0.55"),
    "电极突出":     ("0.60", "0.45", "0.75"),
    "电极横向内延": ("0.50", "0.35", "0.65"),
}
# 各检测项不良在「超下限 / 超上限」之间的基准分摊比例（二者之和=1），用于由总不良数折算超下限数/超上限数
_DEFECT_SPLIT = {
    "产品长度":     (0.55, 0.45),
    "产品宽度":     (0.50, 0.50),
    "端头不一":     (0.70, 0.30),
    "瓷体缺损":     (0.40, 0.60),
    "产品歪斜":     (0.45, 0.55),
    "产品偏位":     (0.65, 0.35),
    "产品变形":     (0.50, 0.50),
    "端面漏瓷":     (0.30, 0.70),
    "瓷体发黑":     (0.50, 0.50),
    "瓷体划痕":     (0.50, 0.50),
    "爬镀":         (0.40, 0.60),
    "电极突出":     (0.60, 0.40),
    "电极横向内延": (0.35, 0.65),
}
# 各缺陷在「权重=1 相机」上的本班次基准数量
_DEFECT_BASE = {
    "产品长度": 45, "产品宽度": 30, "端头不一": 80, "瓷体缺损": 60,
    "产品歪斜": 25, "产品偏位": 20, "产品变形": 15, "端面漏瓷": 12,
    "瓷体发黑": 10, "瓷体划痕": 35, "爬镀": 8, "电极突出": 18, "电极横向内延": 14,
}
# 各相机相对权重：刻意保持接近均匀（仅 ±3% 微偏差），使各相机处理的产品总数基本一致，
# 仅存在用户可接受的微小差异（符合「原则上各相机总数要一样、实际可有一点点偏差」）。
_CAM_WEIGHTS = {
    "相机1": 0.98, "相机2": 1.02, "相机3": 1.00, "相机4": 0.97,
    "相机5": 1.01, "相机6": 0.99, "相机7": 1.00, "相机8": 0.98,
}
_BASE_DEF = []
for _cam in [f"相机{i}" for i in range(1, 9)]:
    _w = _CAM_WEIGHTS[_cam]
    _BASE_DEF.append((_cam, [(d, max(0, int(round(_DEFECT_BASE[d] * _w))))
                             for d in _DEFECT_TYPES]))


def _distribute(total, weights):
    """将 total 按 weights 比例拆为整数列表，且各项之和严格等于 total。

    用于把每批产品的良/不良、缺陷数量按比例分摊到 8 路相机（权重各异），
    保证拆分后总和不丢不重，避免统计数字对不上。
    """
    if total <= 0 or not weights:
        return [0] * len(weights)
    sw = sum(weights) or 1
    raw = [total * w / sw for w in weights]
    floor = [int(x) for x in raw]
    rem = total - sum(floor)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - floor[i], reverse=True)
    for i in range(rem):
        floor[order[i % len(order)]] += 1
    return floor


def _distribute_f(total, weights):
    """将浮点 total 按 weights 比例拆为浮点列表（各项之和严格等于 total）。

    用于把每批的不良数（浮点）按比例分摊到各相机，保持全局与分相机口径一致。
    """
    if not weights:
        return []
    sw = sum(weights) or 1
    return [total * w / sw for w in weights]


_BASE_DONUT = {
    "按剔除口统计": [("OK", 9500, "#0D822B"), ("NG1", 280, "#C81435"),
                    ("NG2", 120, "#FF8A80"), ("RST", 100, "#F9AA0B")],
    "按缺陷项统计": [("划痕", 180, "#C81435"), ("脏污", 120, "#F9AA0B"),
                    ("缺料", 60, "#4261FF"), ("变形", 40, "#0D822B")],
    "按相机统计": [("上表面", 260, "#4261FF"), ("下表面", 240, "#0D822B"),
                  ("内侧面", 300, "#C81435"), ("外侧面", 200, "#F9AA0B")],
}


def _make_camera_stats(rows):
    """rows: (相机名, 良品数, 不良品数, 重检数) -> {相机: 6 项指标}。

    总数 = 良品数 + 不良品数 + 重检数，与实时累计口径（_build_live_camera_stats）保持一致，
    保证「按相机统计」总数与 KPI / 按剔除口详情表 各口径完全一致。
    """
    out = {}
    for cam, good, bad, rechk in rows:
        total = good + bad + rechk
        out[cam] = {
            "总数": str(total),
            "良品数": str(good),
            "不良品数": str(bad),
            "重检数": str(rechk),
            "良率": f"{good / total * 100:.2f}%",
            "重检率": f"{rechk / total * 100:.2f}%",
        }
    return out


def _make_defects(rows):
    """rows: (相机名, [(缺陷名, 数量), ...]) -> {相机: [(缺陷, 数量, 占比)]}。"""
    out = {}
    for cam, items in rows:
        s = sum(q for _, q in items) or 1
        out[cam] = [(name, str(q), f"{q / s * 100:.2f}%") for name, q in items]
    return out


def _defect_totals_from_data(camera_defects):
    """从「相机→缺陷明细」结构（静态示例或实时累计，元素为 (缺陷, 数量[, 占比])）
    汇总出：逐相机各缺陷总数 per_cam[相机][缺陷]=数量，以及全局聚合 agg[缺陷]=总数。"""
    per_cam = {}
    agg = {}
    for cam, items in camera_defects.items():
        dct = {}
        for entry in items:
            d = entry[0]
            qty = int(entry[1]) if len(entry) > 1 else 0
            dct[d] = qty
            agg[d] = agg.get(d, 0) + qty
        per_cam[cam] = dct
    return per_cam, agg


def _split_defect(defect, total):
    """把某缺陷的总不良数按 _DEFECT_SPLIT 基准比例拆为 (超下限数, 超上限数)。"""
    if total <= 0:
        return 0, 0
    fb, fa = _DEFECT_SPLIT.get(defect, (0.5, 0.5))
    below = int(round(total * fb))
    above = total - below
    return below, above


# 统计时段：当前运行 / 指定时间段 / 白班 / 中班 / 晚班
# 各时段示例数据：scale=相对本班次基准的倍数；yield=良品率(%)；rechk=重检率(%)
# 三者各时段不同，使切换时段时 KPI / 环形图 / 相机统计 / 缺陷数据都有区分度。
# 统计时段：当前运行 / 指定时间段 / 白班 / 中班 / 晚班
# 各时段示例数据：scale=相对本班次基准的倍数；yield=良品率(%)；rechk=重检率(%)
# 良品率约束在 95~97% 波动、重检率约束在 0~1% 波动，且 良率+不良率+重检率=100%。
# 统计时段：当前运行 / 指定时间段 / 白班 / 中班 / 晚班
# 各时段示例数据：scale=相对本班次基准的倍数；yield=良品率(%)；rechk=重检率(%)
# 良品率约束在 95~97% 波动（目标带居中 95.5~96.5）、重检率约束在 0~1% 波动，
# 且 良率+不良率+重检率=100%。
_PERIOD_PROFILE = {
    "当前运行":   (1, 96.0, 1.0),
    "指定时间段": (8, 96.3, 1.0),
    "白班":       (4, 96.2, 1.0),
    "中班":       (3, 95.7, 1.0),
    "晚班":       (2, 96.5, 1.0),
}
# 示例数据标定：使「反推速度」与统计卡片显示的「平均速度（约 11000 Pcs/Min）」一致。
# 每个 scale 单位对应 30 分钟运行时长（11000 Pcs/Min × 30 Min = 330000），
# 单位产量 = 11000 Pcs/Min × 30 Min = 330000；当前运行 = 1 单位 ≈ 30 分钟 → 约 11000 Pcs/Min。
_EXAMPLE_SPEED = 11000        # Pcs/Min，与统计卡片「平均速度」同源
_EXAMPLE_UNIT_MIN = 30        # 每个 scale 单位对应的运行时长（分钟）
_EXAMPLE_BASE = int(round(_EXAMPLE_SPEED * _EXAMPLE_UNIT_MIN))   # 330000

PERIOD_DATA = {}
for _p in ["当前运行", "指定时间段", "白班", "中班", "晚班"]:
    _f, _yield, _rechk = _PERIOD_PROFILE[_p]
    _total = _EXAMPLE_BASE * _f
    _good = int(round(_total * _yield / 100))
    _rechk_n = max(1, int(round(_total * _rechk / 100)))
    # 不良 = 总数 - 良品 - 重检，保证 良品率+不良率+重检率=100%，
    # 且环形图 RST（重检）与 KPI 重检数完全一致（修复「详情重检之和与概览不符」）。
    _bad = _total - _good - _rechk_n
    if _bad < 0:
        _bad = 0
    _kpi = [
        ("总数", str(_total), COLORS["text_primary"]),
        ("良品数", str(_good), COLORS["accent_green"]),
        ("不良品数", str(_bad), COLORS["accent_red"]),
        ("重检数", str(_rechk_n), COLORS["accent_yellow"]),
        ("良品率", f"{_good / _total * 100:.2f}%", COLORS["accent_green"]),
        ("不良率", f"{_bad / _total * 100:.2f}%", COLORS["accent_red"]),
        ("重检率", f"{_rechk_n / _total * 100:.2f}%", COLORS["accent_yellow"]),
    ]
    # 按剔除口统计：OK=良品数，不良品按基准比例分摊到 NG1/NG2，RST=重检数（与 KPI 重检数一致），
    # 使 良品+不良+重检=总数、环形图 OK 扇区比例与时段良品率一致、中心良率数字正确更新。
    _ng1 = int(round(_bad * 280 / 400))
    _ng2 = _bad - _ng1
    _rst = _rechk_n
    donut_toukou = [("OK", _good, "#0D822B"), ("NG1", _ng1, "#C81435"),
                    ("NG2", _ng2, "#FF8A80"), ("RST", _rst, "#F9AA0B")]
    # 按缺陷项统计的环形图总量须与 KPI 不良品总数一致，避免「饼图总和与概览对不上」
    _defect_donut_vals = _distribute(
        _bad, [v for _, v, _ in _BASE_DONUT["按缺陷项统计"]])
    _defect_donut = [(l, _defect_donut_vals[i], c)
                     for i, (l, _, c) in enumerate(_BASE_DONUT["按缺陷项统计"])]
    _donut = {
        "按剔除口统计": donut_toukou,
        "按缺陷项统计": _defect_donut,
        "按相机统计": [(l, v * _f, c) for l, v, c in _BASE_DONUT["按相机统计"]],
    }
    # 相机统计按 KPI 的 良品/不良/重检 总数做比例拆分，保证各相机之和与全局一致
    _cam_good = _distribute(_good, [g for _, g, _, _ in _BASE_CAM])
    _cam_bad = _distribute(_bad, [b for _, _, b, _ in _BASE_CAM])
    _cam_rechk = _distribute(_rechk_n, [r for _, _, _, r in _BASE_CAM])
    _cam_stats = _make_camera_stats([
        (c, _cam_good[i], _cam_bad[i], _cam_rechk[i])
        for i, (c, _, _, _) in enumerate(_BASE_CAM)
    ])
    # 缺陷明细按各相机的不良数缩放，使「按缺陷项统计」饼图/详情右侧数量之和 = 不良品总数
    _cam_def = _make_defects([
        (c, list(zip(
            [d for d, _ in items],
            _distribute(_cam_bad[i], [q for _, q in items])
        )))
        for i, (c, items) in enumerate(_BASE_DEF)
    ])
    PERIOD_DATA[_p] = {"kpi": _kpi, "donut": _donut,
                       "camera_stats": _cam_stats, "camera_defects": _cam_def,
                       "yield": f"{_good / _total * 100:.2f}%", "rechk": _rechk}

# 模块级默认（当前运行），供各视图未注入数据时回退
CAMERA_STATS_DATA = PERIOD_DATA["当前运行"]["camera_stats"]
CAMERA_DEFECTS_DATA = PERIOD_DATA["当前运行"]["camera_defects"]


# ============ 统计时段默认时间（白班/中班/晚班等，修改后持久化）============
def _config_dir():
    """配置目录：打包后为 exe 所在目录，开发时为脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


SHIFT_DEFAULTS_PATH = os.path.join(_config_dir(), "shift_defaults.json")

# 各时段的出厂默认开始/结束时间
_DEFAULT_PERIOD_TIMES = {
    "当前运行": ("运行开始", "现在"),
    "指定时间段": ("开始日期", "结束日期"),
    "白班": ("08:00", "16:00"),
    "中班": ("16:00", "24:00"),
    "晚班": ("00:00", "08:00"),
}


def load_period_times():
    """读取持久化的时段默认时间；缺失或损坏时回退到出厂默认值。"""
    merged = {k: list(v) for k, v in _DEFAULT_PERIOD_TIMES.items()}
    try:
        with open(SHIFT_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if k in merged and isinstance(v, (list, tuple)) and len(v) == 2:
                merged[k] = [str(v[0]), str(v[1])]
    except Exception:
        pass
    return {k: tuple(v) for k, v in merged.items()}


def save_period_times(times):
    """将时段默认时间写回磁盘，供下次启动加载。"""
    try:
        with open(SHIFT_DEFAULTS_PATH, "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in times.items()},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# 紧凑表格通用样式：字体 9px、单元格内边距收紧，避免拥挤观感
# 表头取消蓝色高亮，改为中性灰，仅作区分。改为函数：主题切换时可重建刷新。
def compact_table_style():
    return f"""
    QTableWidget {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        gridline-color: {COLORS['border']};
        color: {COLORS['text_primary']};
        font-size: 9px;
    }}
    QTableWidget::item {{
        padding: 1px 2px;
        border: 1px solid {COLORS['border']};
    }}
    QHeaderView::section {{
        background-color: {COLORS['bg_panel']};
        color: {COLORS['text_secondary']};
        padding: 2px 3px;
        border: 1px solid {COLORS['border']};
        font-weight: bold;
        font-size: 9px;
    }}
    QTableWidget::item:selected {{ background-color: transparent; }}
"""


class CameraGrid(QWidget):
    """8 路相机网格：2 列 × 4 行，填充面板高度。

    - 相机总高占据整个面板（即整个窗口高度）
    - 相机之间留间隙（GAP）
    - 每个相机保持 4:3，即 画布宽 = 画布高 × 1.333
    """

    COLS = 2
    ROWS = 4
    GAP = 12

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.cams = [CameraPreview(n) for n in names]
        for c in self.cams:
            c.setParent(self)
        self.relayout()

    def relayout(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        gap = self.GAP
        camH = int((h - (self.ROWS - 1) * gap) / self.ROWS)
        camW = int(camH * 4 / 3)
        totalW = self.COLS * camW + (self.COLS - 1) * gap
        offX = max(0, (w - totalW) // 2)
        for i, c in enumerate(self.cams):
            r = i // self.COLS
            col = i % self.COLS
            c.set_canvas_size(camW, camH)
            c.move(offX + col * (camW + gap), r * (camH + gap))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()


class CameraStatsView(QWidget):
    """按相机统计视图：相机标签页 + 项目统计表 + 缺陷统计表。

    样式参考用户截图：顶部横向相机标签，默认选中相机 4；
    中间为项目×相机的数据表；下方为当前选中相机的缺陷统计表。
    """

    ROW_LABELS = ["总数", "良品数", "不良品数", "重检数", "良率", "重检率"]

    def __init__(self, parent=None, camera_stats_data=None, camera_defects_data=None):
        super().__init__(parent)
        self.current_cam = "相机4"
        self.cameras = [f"相机{i}" for i in range(1, 9)]
        self._cam_buttons = {}
        self._cleared = False
        self.camera_stats_data = camera_stats_data or CAMERA_STATS_DATA
        self.camera_defects_data = camera_defects_data or CAMERA_DEFECTS_DATA
        self._build()
        self.load_example()

    def set_data(self, camera_stats_data, camera_defects_data):
        """切换统计时段时整体替换数据并刷新。"""
        self.camera_stats_data = camera_stats_data
        self.camera_defects_data = camera_defects_data
        self.load_example()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # 顶部相机标签页：充当项目统计表的列头，并与下方相机列精确对齐。
        # 用 QGridLayout 与表格列结构完全一致：第 0 列=「项目」占位(64px)，列1-8=相机(等宽)。
        tabs = QGridLayout()
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setHorizontalSpacing(0)
        tabs.setVerticalSpacing(0)
        tabs.setColumnMinimumWidth(0, 64)
        tabs.setColumnStretch(0, 0)
        for i in range(len(self.cameras)):
            tabs.setColumnStretch(i + 1, 1)
        proj = QLabel("项目")
        proj.setFixedWidth(64)
        proj.setAlignment(Qt.AlignmentFlag.AlignCenter)
        proj.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px; font-weight: bold;")
        tabs.addWidget(proj, 0, 0)
        for i, cam in enumerate(self.cameras):
            b = QPushButton(cam)
            b.setFixedHeight(24)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(self._tab_style(False))
            b.clicked.connect(lambda checked, c=cam: self._select_camera(c))
            self._cam_buttons[cam] = b
            tabs.addWidget(b, 0, i + 1)
        lay.addLayout(tabs)

        # 项目统计表：列0=项目(固定宽64)，列1..8=相机(拉伸)
        # 隐藏表格表头（相机列头由上方标签页充当）；去边框/网格线并关闭横滚，消除像素偏移以保证与标签页对齐
        self.summary_table = QTableWidget(len(self.ROW_LABELS), 1 + len(self.cameras))
        self.summary_table.setHorizontalHeaderLabels(["项目"] + self.cameras)
        self.summary_table.horizontalHeader().setVisible(False)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setShowGrid(False)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.summary_table.setColumnWidth(0, 64)
        for c in range(1, 1 + len(self.cameras)):
            self.summary_table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.Stretch)
        self.summary_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.summary_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.summary_table.setStyleSheet(self._table_style() + "\nQTableWidget { border: none; }")
        self.summary_table.setMaximumHeight(150)
        lay.addWidget(self.summary_table, 1)

        # 缺陷统计表：缺陷 / 数量 / 比例
        self.defect_table = QTableWidget(0, 3)
        self.defect_table.setHorizontalHeaderLabels(["缺陷", "数量", "比例"])
        self.defect_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.defect_table.verticalHeader().setVisible(False)
        self.defect_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.defect_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.defect_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.defect_table.setStyleSheet(self._table_style())
        self.defect_table.setMaximumHeight(120)
        lay.addWidget(self.defect_table, 1)

        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        register_restyle(self._restyle)

    def _tab_style(self, active):
        if active:
            return (
                f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 9px; padding: 0 2px; font-weight: bold; }}"
            )
        return (
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; color: {COLORS['text_secondary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; font-size: 9px; padding: 0 2px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; color: {COLORS['text_primary']}; }}"
        )

    def _table_style(self):
        return compact_table_style()

    def _restyle(self):
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        for name, btn in self._cam_buttons.items():
            btn.setStyleSheet(self._tab_style(name == self.current_cam))
        self.summary_table.setStyleSheet(self._table_style() + "\nQTableWidget { border: none; }")
        self.defect_table.setStyleSheet(self._table_style())
        self._populate_summary()
        self._select_camera(self.current_cam)

    def _populate_summary(self):
        # 第 0 列：行标签（总数 / 良品数 / 不良品数 / 重检数 / 良率 / 重检率）
        for r, label in enumerate(self.ROW_LABELS):
            item = QTableWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(COLORS["text_secondary"]))
            self.summary_table.setItem(r, 0, item)
        # 列 1..8：各相机数据
        for col, cam in enumerate(self.cameras):
            data = self.camera_stats_data[cam]
            for row, key in enumerate(self.ROW_LABELS):
                item = QTableWidgetItem(data[key])
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.summary_table.setItem(row, col + 1, item)

    def _populate_defect(self, cam):
        self.defect_table.setRowCount(0)
        for name, qty, pct in self.camera_defects_data.get(cam, []):
            row = self.defect_table.rowCount()
            self.defect_table.insertRow(row)
            for col, txt in enumerate([name, qty, pct]):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.defect_table.setItem(row, col, item)

    def load_example(self):
        """重新载入示例数据。"""
        self._cleared = False
        self._populate_summary()
        self._select_camera(self.current_cam)

    def clear_data(self):
        """清空所有示例数据。"""
        self._cleared = True
        self.summary_table.clearContents()
        self.defect_table.setRowCount(0)

    def set_cleared(self, flag):
        if flag:
            self.clear_data()
        else:
            self.load_example()

    def _select_camera(self, cam):
        self.current_cam = cam
        for name, btn in self._cam_buttons.items():
            btn.setChecked(name == cam)
            btn.setStyleSheet(self._tab_style(name == cam))
        # 高亮当前相机对应的表格列（与上方标签页对齐）
        col_idx = self.cameras.index(cam) + 1
        for r in range(self.summary_table.rowCount()):
            for c in range(1, 1 + len(self.cameras)):
                item = self.summary_table.item(r, c)
                if item:
                    if c == col_idx:
                        item.setBackground(QColor(COLORS["accent_blue"]))
                        item.setForeground(QColor("white"))
                    else:
                        item.setBackground(QColor(COLORS["bg_card"]))
                        item.setForeground(QColor(COLORS["text_primary"]))
        # 刷新缺陷表（仅在非清零状态填充）
        if not self._cleared:
            self._populate_defect(cam)


class DefectStatsView(QWidget):
    """按缺陷项统计：所有相机汇总后的 缺陷项 / 数量 / 占比（不含各相机分列）。"""

    def __init__(self, parent=None, camera_defects_data=None):
        super().__init__(parent)
        self.defect_types = [d[0] for d in (camera_defects_data or CAMERA_DEFECTS_DATA)["相机1"]]
        self.cameras = [f"相机{i}" for i in range(1, 9)]
        self._cleared = False
        self.camera_defects_data = camera_defects_data or CAMERA_DEFECTS_DATA
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.table = QTableWidget(len(self.defect_types), 3)
        self.table.setHorizontalHeaderLabels(["缺陷项", "数量", "占比"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # 缺陷项较多时允许纵向滚动；行高下限 30px 保证可读性
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setMinimumSectionSize(30)
        self.table.setStyleSheet(self._table_style())
        lay.addWidget(self.table, 1)
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self.load_example()
        register_restyle(self._restyle)

    def _table_style(self):
        return compact_table_style()

    def _restyle(self):
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self.table.setStyleSheet(self._table_style())
        self._populate()

    def _cell(self, text, bold=False):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def set_data(self, camera_defects_data):
        """切换统计时段时整体替换缺陷数据并刷新。"""
        self.camera_defects_data = camera_defects_data
        self.defect_types = [d[0] for d in camera_defects_data["相机1"]]
        self.table.setRowCount(len(self.defect_types))
        self.load_example()

    def _populate(self):
        # 聚合所有相机：每个缺陷项的总数量与全局占比
        total_per_defect = {d: 0 for d in self.defect_types}
        grand = 0
        for cam in self.cameras:
            for d, qty, _ in self.camera_defects_data.get(cam, []):
                n = int(qty)
                total_per_defect[d] += n
                grand += n
        for r, d in enumerate(self.defect_types):
            self.table.setItem(r, 0, self._cell(d, bold=True))
            self.table.setItem(r, 1, self._cell(str(total_per_defect[d])))
            ratio = (total_per_defect[d] / grand * 100) if grand else 0
            self.table.setItem(r, 2, self._cell(f"{ratio:.2f}%"))

    def load_example(self):
        self._cleared = False
        self._populate()

    def clear_data(self):
        self._cleared = True
        self.table.clearContents()


class DefectSPCStatTable(QTableWidget):
    """按缺陷项统计 SPC 七列表：检测项 / 标称值 / 规格下限 / 规格上限 / 超下限数 / 超上限数 / 比例。

    set_rows 接收 [(检测项, 标称值, 规格下限, 规格上限, 超下限数, 超上限数, 比例), ...]；
    比例列（最右）以强调色突出，检测项列加粗。
    """

    COLUMNS = ["检测项", "标称值", "规格下限", "规格上限", "超下限数", "超上限数", "比例"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(compact_table_style())
        # 缺陷项较多时允许纵向滚动；行高下限保证可读性
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 行高下限从 26 降到 20，使 13 行缺陷项在常规面板高度内尽量完整显示
        self.verticalHeader().setMinimumSectionSize(20)
        self.verticalHeader().setDefaultSectionSize(20)

    def set_rows(self, rows):
        self.setRowCount(len(rows))
        for r, (d, nom, lo, hi, below, above, ratio) in enumerate(rows):
            vals = [d, nom, lo, hi, str(below), str(above), f"{ratio:.2f}%"]
            for c, txt in enumerate(vals):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    item.setForeground(QColor(COLORS["text_primary"]))
                    # 检测项列保持加粗，但字号必须与其它列的 9px 样式表一致（避免 9pt ≈ 12px 显得更大）
                    f = QFont("Microsoft YaHei", QFont.Weight.Bold)
                    f.setPixelSize(9)
                    item.setFont(f)
                elif c == 6:
                    item.setForeground(QColor(COLORS["accent_blue"]))
                self.setItem(r, c, item)

    def clear_all(self):
        self.setRowCount(0)


class DefectStatsContainer(QWidget):
    """按缺陷项统计：饼图（聚合各缺陷项占比）+ 详情（逐相机 SPC 七列）切换容器。

    饼图页：左侧环形图按各缺陷项占比展示 + 右侧图例（缺陷项名称/不良数量/比例，三列左对齐）；
    详情页：相机标签（含「全部」）+ 该相机（或全部相机）SPC 七列表（检测项/标称值/规格下限/
    规格上限/超下限数/超上限数/比例）。
    """

    def __init__(self, parent=None, camera_defects_data=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self._data = camera_defects_data or CAMERA_DEFECTS_DATA
        self._defect_types = [d[0] for d in self._data["相机1"]]
        self._cameras = [f"相机{i}" for i in range(1, 9)]
        self._current_cam = "全部"
        self._cleared = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._stack = QStackedWidget()

        # --- 饼图页：聚合缺陷饼图 + 右侧图例 + 汇总表 ---
        pie_page = QWidget()
        pie_page.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        pie_lay = QVBoxLayout(pie_page)
        pie_lay.setContentsMargins(0, 0, 0, 0)
        pie_lay.setSpacing(6)

        self._chart = DonutChart([])
        # 饼图缩小，给下方 13 行汇总表留出更多纵向空间，避免表格被压到滚动/看不到
        self._chart.setFixedSize(120, 120)
        self._chart.center_value = ""  # 缺陷饼图不显示中心数值
        chart_h = QHBoxLayout()
        chart_h.setContentsMargins(0, 0, 0, 0)
        chart_h.setSpacing(10)
        chart_h.addWidget(self._chart)
        chart_h.setAlignment(self._chart, Qt.AlignmentFlag.AlignVCenter)

        # 右侧图例：缺陷项名称 + 缺陷数量 + 缺陷比例（三列左对齐，列宽自适应内容；
        # 用滚动区包裹，行数显示不全时出现上下滚动条）
        legend_widget = QWidget()
        legend_widget.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        legend_lay = QGridLayout(legend_widget)
        legend_lay.setContentsMargins(0, 0, 0, 0)
        legend_lay.setHorizontalSpacing(10)
        legend_lay.setVerticalSpacing(2)
        # 注意：不拉伸名称列，使各列宽度自适应内容，避免「缺陷项」与「数量」列间距过大
        self._legend_layout = legend_lay
        legend_scroll = QScrollArea()
        legend_scroll.setWidgetResizable(True)
        legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        legend_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        legend_scroll.setFrameShape(QFrame.Shape.NoFrame)
        legend_scroll.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: none;")
        legend_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        legend_scroll.setWidget(legend_widget)
        self._legend_widget = legend_widget
        self._legend_scroll = legend_scroll
        chart_h.addWidget(legend_scroll, 1)
        pie_lay.addLayout(chart_h)

        self._stack.addWidget(pie_page)

        # --- 详情页：相机标签 + 该相机检测项表格 ---
        detail_page = QWidget()
        detail_page.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        detail_lay = QVBoxLayout(detail_page)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(6)

        cam_row = QHBoxLayout()
        cam_row.setSpacing(4)
        self._cam_buttons = {}
        # 「全部」按钮固定在最左侧：显示所有相机的所有检测项
        all_btn = QPushButton("全部")
        all_btn.setFixedHeight(20)
        all_btn.setCheckable(True)
        all_btn.setStyleSheet(self._cam_btn_style(False))
        all_btn.clicked.connect(lambda _checked: self._select_camera("全部"))
        self._cam_buttons["全部"] = all_btn
        cam_row.addWidget(all_btn)
        for cam in self._cameras:
            b = QPushButton(cam)
            b.setFixedHeight(20)
            b.setCheckable(True)
            b.setStyleSheet(self._cam_btn_style(False))
            b.clicked.connect(lambda _checked, c=cam: self._select_camera(c))
            self._cam_buttons[cam] = b
            cam_row.addWidget(b)
        cam_row.addStretch(1)
        detail_lay.addLayout(cam_row)

        self._detail_table = DefectSPCStatTable()
        detail_lay.addWidget(self._detail_table, 1)

        self._stack.addWidget(detail_page)
        lay.addWidget(self._stack, 1)

        register_restyle(self._restyle)
        # 详情页默认选中「全部」（蓝底高亮），进入详情时即显示全部相机的聚合数据
        self._select_camera("全部")
        self._set_view("pie")

    def _cam_btn_style(self, active):
        if active:
            return (
                f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 10px; "
                f"padding: 0 6px; font-weight: bold; }}")
        return (
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; color: {COLORS['text_secondary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; font-size: 10px; "
            f"padding: 0 6px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; color: {COLORS['text_primary']}; }}")

    def _set_view(self, mode):
        self._stack.setCurrentIndex(0 if mode == "pie" else 1)
        if mode == "pie":
            self._update_chart()
        else:
            self._refresh_detail()

    def set_view(self, mode):
        """供外部饼图/详情按钮调用。"""
        self._set_view(mode)

    def _select_camera(self, cam):
        self._current_cam = cam
        for c, b in self._cam_buttons.items():
            b.setChecked(c == cam)
            b.setStyleSheet(self._cam_btn_style(c == cam))
        self._refresh_detail()

    def _aggregated_rows(self):
        """聚合所有相机的缺陷总数，按 SPC 七列汇总（比例列之和恒为 100%）。"""
        _, agg = _defect_totals_from_data(self._data)
        grand = sum(agg.values()) or 1
        rows = []
        for d in self._defect_types:
            total = agg.get(d, 0)
            below, above = _split_defect(d, total)
            ratio = total / grand * 100
            nom, lo, hi = _DEFECT_SPEC.get(d, ("-", "-", "-"))
            rows.append((d, nom, lo, hi, below, above, ratio))
        return rows

    def _camera_rows(self, cam):
        """单相机缺陷明细，按 SPC 七列展示（比例列=该相机内占比，之和=100%）。"""
        per_cam, _ = _defect_totals_from_data(self._data)
        counts = per_cam.get(cam, {})
        cam_total = sum(counts.values()) or 1
        rows = []
        for d in self._defect_types:
            total = counts.get(d, 0)
            below, above = _split_defect(d, total)
            ratio = total / cam_total * 100
            nom, lo, hi = _DEFECT_SPEC.get(d, ("-", "-", "-"))
            rows.append((d, nom, lo, hi, below, above, ratio))
        return rows

    def _refresh_detail(self):
        if self._current_cam == "全部" and not self._cleared:
            rows = self._all_rows()
        else:
            rows = self._camera_rows(self._current_cam) if not self._cleared else []
        self._detail_table.set_rows(rows)

    def _all_rows(self):
        """「全部」：按缺陷项聚合所有相机的不良数（同名缺陷跨相机求和），检测项列不拼相机名。

        比例按该缺陷占全局总量的百分比；与 _aggregated_rows 口径一致（逐缺陷跨相机求和）。
        """
        per_cam, _ = _defect_totals_from_data(self._data)
        sum_counts = {}
        for counts in per_cam.values():
            for d, q in counts.items():
                sum_counts[d] = sum_counts.get(d, 0) + q
        grand = sum(sum_counts.values()) or 1
        rows = []
        for d in self._defect_types:
            total = sum_counts.get(d, 0)
            below, above = _split_defect(d, total)
            ratio = total / grand * 100
            nom, lo, hi = _DEFECT_SPEC.get(d, ("-", "-", "-"))
            rows.append((d, nom, lo, hi, below, above, ratio))
        return rows

    def _update_chart(self):
        _, agg = _defect_totals_from_data(self._data)
        data = [
            (d, agg.get(d, 0), _DEFECT_COLORS[i % len(_DEFECT_COLORS)])
            for i, d in enumerate(self._defect_types)
        ]
        self._chart.data = data
        self._chart.center_value = ""
        self._chart.update()
        self._refresh_legend()

    def _refresh_legend(self):
        """在环形图右侧刷新缺陷项图例：三列左对齐（缺陷项名称 / 不良数量 / 缺陷比例）。"""
        grid = self._legend_layout
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # 表头（三列左对齐）
        hdr = "font-size: 10px; font-weight: bold; color: %s;" % COLORS["text_primary"]
        h_name = QLabel("缺陷项")
        h_name.setStyleSheet(hdr)
        h_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(h_name, 0, 1)
        h_cnt = QLabel("数量")
        h_cnt.setStyleSheet(hdr)
        h_cnt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(h_cnt, 0, 2)
        h_ratio = QLabel("比例")
        h_ratio.setStyleSheet(hdr)
        h_ratio.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(h_ratio, 0, 3)
        # 数据行
        rows = self._aggregated_rows()
        for i, (d, _, _, _, below, above, ratio) in enumerate(rows):
            total = below + above
            color = _DEFECT_COLORS[i % len(_DEFECT_COLORS)]
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(dot, i + 1, 0)
            name = QLabel(d)
            name.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 10px;")
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(name, i + 1, 1)
            cnt = QLabel(str(total))
            cnt.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 10px;")
            cnt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(cnt, i + 1, 2)
            rt = QLabel(f"{ratio:.2f}%")
            rt.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 10px;")
            rt.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(rt, i + 1, 3)
        # 固定图例内容高度为实际行高：缺陷项较多、超出可视区时由 QScrollArea 显示上下滚动条
        self._legend_widget.layout().activate()
        self._legend_widget.adjustSize()
        self._legend_widget.setFixedHeight(self._legend_widget.height())

    def _restyle(self):
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self._chart._restyle()
        self._detail_table.setStyleSheet(compact_table_style())
        if self._stack.currentIndex() == 0:
            self._update_chart()
        else:
            self._select_camera(self._current_cam)

    def set_data(self, camera_defects_data):
        """整体替换缺陷数据（时段切换 / 实时累计时调用）。"""
        self._data = camera_defects_data
        self._defect_types = [d[0] for d in next(iter(camera_defects_data.values()), [])]
        self._update_chart()
        self._refresh_detail()

    def load_example(self):
        self._cleared = False
        self._update_chart()
        self._refresh_detail()

    def clear_data(self):
        self._cleared = True
        self._chart.data = [
            (d, 0, _DEFECT_COLORS[i % len(_DEFECT_COLORS)])
            for i, d in enumerate(self._defect_types)
        ]
        self._chart.update()
        self._detail_table.clear_all()
        # 清空饼图右侧图例
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class RejectDetailView(QWidget):
    """按相机展示良品率 / 总数 / 良品数 / 不良1数 / 不良2数 / 重检数 的详情表。

    相机名放在行表头（左侧），列头依次为：良品率、总数、良品数、不良1数、不良2数、重检数。
    """

    COLUMNS = [
        ("良品率", None),
        ("总数", None),
        ("良品数", COLORS["accent_green"]),
        ("不良1数", "#C81435"),
        ("不良2数", "#FF8A80"),
        ("重检数", COLORS["accent_yellow"]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        for i in range(len(self.COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.Stretch)
        # 行表头（左侧）显示相机名
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # 行表头左上角加上「相机」列头（行表头与列表头的交汇角标）
        corner = QLabel("相机")
        corner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        corner.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"font-size: 10px; font-weight: bold; border: none;")
        self.table.setCornerWidget(corner)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet(self._table_style())
        lay.addWidget(self.table)
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self._rows = []
        register_restyle(self._restyle)

    def _table_style(self):
        return (
            compact_table_style()
            + f"\n    QTableWidget {{ font-size: 10px; }}"
            + f"\n    QHeaderView::section {{ font-size: 10px; }}"
        )

    def _restyle(self):
        self.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        self.table.setStyleSheet(self._table_style())
        self._populate()

    def _cell(self, text, color=None):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            item.setForeground(QColor(color))
        return item

    def set_data(self, rows):
        """rows: [(相机, 良品率, 总数, 良品数, 不良1数, 不良2数, 重检数), ...]"""
        self._rows = rows
        self._populate()

    def _populate(self):
        rows = getattr(self, "_rows", [])
        self.table.setRowCount(len(rows))
        colors = [None, None, COLORS["accent_green"], "#C81435", "#FF8A80", COLORS["accent_yellow"]]
        for r, item in enumerate(rows):
            cam = item[0]
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(cam))
            for c, txt in enumerate(item[1:]):
                self.table.setItem(r, c, self._cell(txt, colors[c]))


def _make_info_icon(px: int = 18) -> QIcon:
    """绘制『设备详情』信息图标：蓝色圆形按钮上的白色 i 字形。

    笔画（圆点 + 竖笔）全部用 QPainter 几何绘制，不依赖任何字体/外部资源，
    避免在离屏/无 GUI 构建环境出现豆腐块；一看图标即知是『信息/详情』。
    """
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    cx = int(round(px * 0.5))
    # i 上方圆点
    d = max(2, int(round(px * 0.14)))
    dot_y = int(round(px * 0.27))
    p.drawEllipse(QRect(cx - d // 2, dot_y - d // 2, d, d))
    # i 竖笔（带圆角）
    bw = max(2, int(round(px * 0.14)))
    bh = max(4, int(round(px * 0.40)))
    p.drawRoundedRect(QRect(cx - bw // 2, int(round(px * 0.42)), bw, bh),
                      int(round(px * 0.07)), int(round(px * 0.07)))
    p.end()
    return QIcon(pm)


def _make_gc_icon(px: int = 18, color: QColor = QColor(255, 255, 255)) -> QIcon:
    """绘制「玻璃清洁」图标：圆角窗格 + 一道斜向擦拭痕 + 小水滴。

    用指定颜色（color）几何绘制，不依赖字体/外部资源，离屏构建安全；
    窗格轮廓与擦拭痕随按钮状态用蓝/白两色切换，一看即知是「清洁玻璃」。
    """
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pad = int(round(px * 0.15))
    # 玻璃窗格：圆角方框轮廓
    pen = QPen(color)
    pen.setWidth(max(1, int(round(px * 0.11))))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRect(pad, pad, px - 2 * pad, px - 2 * pad),
                      int(px * 0.20), int(px * 0.20))
    # 斜向擦拭痕（刮水器的一道）
    pen.setWidth(max(1, int(round(px * 0.16))))
    p.setPen(pen)
    p.drawLine(int(px * 0.32), int(px * 0.66), int(px * 0.66), int(px * 0.32))
    # 小水滴
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    r = max(1, int(round(px * 0.08)))
    p.drawEllipse(QRect(int(px * 0.70 - r), int(px * 0.68 - r), 2 * r, 2 * r))
    p.end()
    return QIcon(pm)


def _product_display_label(p: dict) -> str:
    """产品下拉筛选项显示名：

    - 优先使用「自定义类型 + 自定义型号」（两者或其一非空时）；
    - 自定义为空则回退到「产品类型 + 产品型号」（如「电容 0402」）。
    """
    if not isinstance(p, dict):
        return "未命名产品"
    t = (p.get("custom_type_display") or "").strip()
    m = (p.get("custom_model_display") or "").strip()
    if t or m:
        return (t + ((" " + m) if m else "")).strip()
    pt = (p.get("product_type", "") or "").strip()
    pm = (p.get("product_model", "") or "").strip()
    return (pt + ((" " + pm) if pm else "")).strip() or "未命名产品"


class ProductFilterCombo(QWidget):
    """「统计信息」卡片检索按钮左侧的多选产品筛选下拉。

    下拉项为「新建过的产品」（取自主窗口的产品列表），可复选；
    下拉项名称显示自定义类型/型号，若自定义为空则显示产品类型/型号。
    选中项随「检索」生效（仅作用于当次检索的筛选条件）。
    """

    selectionChanged = pyqtSignal()

    def __init__(self, parent=None, provider=None):
        super().__init__(parent)
        self._provider = provider or (lambda: [])
        self._products = []
        self._checked = set()  # 已勾选产品的 id 集合

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._btn = QPushButton("产品筛选 ▾")
        self._btn.setFixedHeight(28)
        self._btn.setMinimumWidth(96)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 8px; "
            f"font-size: 10px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; color: white; }}")
        self._menu = QMenu(self)
        self._menu.aboutToShow.connect(self._on_about_to_show)
        self._btn.setMenu(self._menu)
        lay.addWidget(self._btn)

        self._update_text()

    # ------------------------------------------------------------------
    def _on_about_to_show(self):
        """每次展开下拉都从 provider 重新拉取最新产品列表（新建/删除后即时生效）。"""
        try:
            self._products = list(self._provider() or [])
        except Exception:
            self._products = []
        ids = {p.get("id") for p in self._products if isinstance(p, dict) and p.get("id")}
        self._checked &= ids
        self._repopulate()
        self._update_text()

    def _repopulate(self):
        self._menu.clear()
        if not self._products:
            act = QAction("（暂无已建产品）", self._menu)
            act.setEnabled(False)
            self._menu.addAction(act)
            return
        for p in self._products:
            label = _product_display_label(p)
            act = QAction(label, self._menu)
            act.setCheckable(True)
            pid = p.get("id")
            act.setData(pid)
            act.setChecked(pid in self._checked)
            act.toggled.connect(lambda _checked, a=act: self._on_toggle(a))
            self._menu.addAction(act)
        self._menu.addSeparator()
        all_act = QAction("清除筛选（全部产品）", self._menu)
        all_act.triggered.connect(self._clear)
        self._menu.addAction(all_act)

    def _on_toggle(self, act: QAction):
        pid = act.data()
        if act.isChecked():
            self._checked.add(pid)
        else:
            self._checked.discard(pid)
        self._update_text()
        self.selectionChanged.emit()

    def _clear(self):
        self._checked.clear()
        self._update_text()
        self.selectionChanged.emit()

    def _update_text(self):
        if not self._checked:
            self._btn.setText("产品筛选 ▾")
            return
        names = [_product_display_label(p) for p in self._products
                 if isinstance(p, dict) and p.get("id") in self._checked]
        if len(names) <= 2:
            self._btn.setText("、".join(names) + " ▾")
        else:
            self._btn.setText(f"已选{len(names)}个产品 ▾")

    # ------------------------------------------------------------------
    def selected_products(self):
        """返回当前勾选的产品字典列表（引用主窗口产品列表中的对象）。"""
        return [p for p in self._products
                if isinstance(p, dict) and p.get("id") in self._checked]


class _ReportExportMixin:
    """「统计信息」卡片「导出」按钮 → 生产报表弹窗的共用逻辑。

    StatsPanel（调试界面）与 ProductionView（生产运行界面）都持有同名状态
    （period / period_times / _kpi_example / stat_datasets / camera_stats_view），
    故抽出共用，避免两处重复维护。
    """

    def _resolve_products(self):
        """向上查找已创建的产品列表（主窗口 self.products）。

        兼容两种挂载方式：① 父链 / 顶层窗口直接持有 .products；
        ② 调试界面通过 .main_window 间接持有主窗口（其 .products）。
        """
        candidates = []
        obj = self
        while obj is not None:
            candidates.append(obj)
            mw = getattr(obj, "main_window", None)
            if mw is not None:
                candidates.append(mw)
            obj = obj.parent()
        win = self.window()
        if win is not None:
            candidates.append(win)
            mw = getattr(win, "main_window", None)
            if mw is not None:
                candidates.append(mw)
        for o in candidates:
            products = getattr(o, "products", None)
            if isinstance(products, list):
                return products
        return []

    def _on_stat_filter_changed(self):
        """产品筛选下拉勾选变化：同步当前勾选的产品列表（供检索/报表使用）。"""
        combo = getattr(self, "_product_filter", None)
        if combo is not None:
            self._stat_filter_products = combo.selected_products()

    def _report_product_info(self):
        """报表「筛选数据」的示例值：取自程序当前配置（产品类型/型号）与设备信息（料号/批号）。

        若「统计信息」卡片已勾选产品筛选，则优先以勾选产品展示（多选时合并显示）。
        """
        flt = getattr(self, "_stat_filter_products", None)
        if flt:
            labels = [_product_display_label(p) for p in flt]
            if labels:
                joined = "、".join(labels)
                return {
                    "产品类型": joined if len(labels) == 1 else f"{joined}（共{len(labels)}项）",
                    "产品型号": "多选筛选" if len(labels) > 1 else (
                        (flt[0].get("custom_model_display") or "").strip()
                        or str(flt[0].get("product_model", "") or "").strip() or "0402"),
                    "产品料号": "—",
                    "产品批号": "—",
                }
        prod = getattr(self, "_report_product", None) or {}
        ptype = (prod.get("custom_type_display") or "").strip() or \
            str(prod.get("product_type", "") or "").strip()
        pmodel = (prod.get("custom_model_display") or "").strip() or \
            str(prod.get("product_model", "") or "").strip()
        pn = ""
        lot = ""
        pn_edit = getattr(self, "pn_edit", None)
        lot_edit = getattr(self, "lot_edit", None)
        if pn_edit is not None:
            pn = (pn_edit.text() or "").strip()
        if lot_edit is not None:
            lot = (lot_edit.text() or "").strip()
        return {
            "产品类型": ptype or "电容",
            "产品型号": pmodel or "0402",
            "产品料号": pn or "—",
            "产品批号": lot or "—",
        }

    def _open_production_report(self):
        """收集当前统计时段的数据与产品信息，打开生产报表弹窗。"""
        period = getattr(self, "period", "当前运行")
        pd = PERIOD_DATA.get(period, PERIOD_DATA["当前运行"])
        start, end = (getattr(self, "period_times", {}) or {}).get(period, ("", ""))
        kpi = getattr(self, "_kpi_example", None) or pd["kpi"]
        donut = (getattr(self, "stat_datasets", {}) or {}).get("按剔除口统计") \
            or pd["donut"]["按剔除口统计"]
        cam = getattr(getattr(self, "camera_stats_view", None),
                      "camera_stats_data", None) or pd["camera_stats"]
        open_production_report(self, period, start, end, kpi, donut, cam,
                               product=self._report_product_info())

    def _search_period(self):
        """当前「检索方式」：取统计时段下拉框文本（无下拉框时回退 self.period）。"""
        cb = getattr(self, "period_cb", None)
        return (cb.currentText() if cb is not None else "") \
            or getattr(self, "period", "当前运行")

    def _refresh_search_btn(self, *_):
        """「检索」按钮的文案与可用性：

        - 返回模式（已点过「检索」）→ 文案变「返回」，可点击，点击后恢复默认统计状态；
        - 检索方式为「当前运行」→ 文案「检索」且置灰（当前运行本身实时刷新，无需检索）；
        - 指定时间段 / 白班 / 中班 / 晚班 → 文案「检索」、可点击，点击后统计固定显示不再刷新。
        """
        btn = getattr(self, "_btn_search_stat", None)
        if btn is None:
            return
        if getattr(self, "_search_return_mode", False):
            btn.setText("返回")
            btn.setEnabled(True)
            btn.setToolTip("返回到默认统计状态：当前运行 - 运行开始 - 现在")
            return
        enabled = self._search_period() != "当前运行"
        btn.setText("检索")
        btn.setEnabled(enabled)
        btn.setToolTip("按检索方式与时间范围刷新统计数据，并固定显示不再刷新"
                       if enabled else "「当前运行」为实时刷新，无需检索")

    def _on_search_stats(self):
        """「检索 / 返回」切换：

        - 返回模式（已点过「检索」）下点击：解除冻结、恢复实时刷新；
        - 非返回模式：按当前「检索方式」冻结当前统计显示，按钮变「返回」可一键恢复。

        镜像模式（调试界面）下：检索 / 返回只作用于本面板显示（冻结 / 解冻），
        **绝不向生产运行界面转发时段切换**，因此不会改动生产数据的实时累计
        （避免清零 / 从 0 重计）；生产运行界面自身的检索逻辑不受影响。
        """
        if getattr(self, "_search_return_mode", False):
            # 当前处于「返回」状态：解除冻结，恢复实时刷新（镜像面板不影响生产计数）
            self._search_return_mode = False
            if getattr(self, "_mirror", False):
                # 镜像面板：仅解除本面板冻结，恢复实时镜像刷新；生产计数保持不变
                self._stat_frozen = False
                self._refresh_search_btn()
                return
            if getattr(self, "_mirror_owner", None) is not None:
                self._mirror_owner._search_return_mode = False
            cb = getattr(self, "period_cb", None)
            if cb is not None:
                cb.blockSignals(True)
                cb.setCurrentText("当前运行")
                cb.blockSignals(False)
            self._set_period("当前运行")
            return
        period = self._search_period()
        if period == "当前运行":
            # 「当前运行」实时刷新，检索按钮本应置灰；此处兜底直接忽略
            self._refresh_search_btn()
            return
        if getattr(self, "_mirror", False):
            # 镜像面板：检索 = 冻结当前显示（详细数据固定显示），
            # 不向生产界面转发时段切换，故不影响生产数据的正常统计。
            log = getattr(self, "log_operation", None)
            if callable(log):
                log(getattr(self, "_op_user", "操作员"),
                    f"检索统计（调试界面冻结显示）：{period}，统计固定显示")
            self._stat_frozen = True
            self._search_return_mode = True
            self._refresh_search_btn()
            return
        # 非镜像（生产运行界面）：按检索方式与时间范围刷新并固定显示
        d_start = getattr(self, "d_start", None)
        d_end = getattr(self, "d_end", None)
        start = d_start.text() if d_start is not None else ""
        end = d_end.text() if d_end is not None else ""
        # 记录检索动作（两个界面的日志区都会出现）
        flt = getattr(self, "_stat_filter_products", None) or []
        flt_labels = [_product_display_label(p) for p in flt]
        flt_text = "全部产品" if not flt_labels else ("、".join(flt_labels))
        log = getattr(self, "log_operation", None)
        if callable(log):
            log(getattr(self, "_op_user", "操作员"),
                f"检索统计数据：{period}（{start} ~ {end}），产品筛选[{flt_text}]，统计固定显示")
        # 先落盘时间范围，再按该时段刷新全部统计（KPI / 环形图 / 相机 / 缺陷项）
        if hasattr(self, "period_times"):
            self.period_times[period] = (start, end)
            save_period_times(self.period_times)
        # 冻结统计显示：周期刷新不再改写统计数据，直到切回「当前运行」
        self._stat_frozen = True
        self._set_period(period)
        # 进入「返回」模式：按钮变「返回」，再次点击恢复默认统计状态
        if getattr(self, "_mirror_owner", None) is not None:
            self._mirror_owner._search_return_mode = True
        self._search_return_mode = True
        self._refresh_search_btn()


class StatsPanel(_ReportExportMixin, QFrame):
    """生产统计与检测结果面板（可独立复用的组件）：

    与生产运行界面中的「生产统计与检测结果」板块完全一致——含统计时段筛选、
    可编辑 KPI、环形图 + 图例、按剔除口 / 按缺陷项 / 按相机统计三种视图、
    速度指标与统计操作按钮（统计配置 / 统计清零 / 三种统计方式切换）。
    该面板自身维护示例数据与清零状态，可独立放置于任意界面（如各相机调试界面），
    无需依赖生产运行界面的播放逻辑。
    """

    def __init__(self, parent=None, period="当前运行", period_times=None):
        super().__init__(parent)
        # 样式仅作用于面板自身（ID 选择器）：若用宽泛的 QFrame 类型选择器，
        # 规则会级联到所有子孙 QLabel/QFrame（QLabel 继承 QFrame），
        # 导致 KPI 单元格、图例圆点等被画上一圈边框（调试界面出现"小窗口"）。
        self.setObjectName("statsPanel")
        self.setStyleSheet(
            f"#statsPanel {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; }}")
        self.period = period
        self._cleared = False
        # 检索固定显示：点「检索」后统计 UI 冻结（周期刷新不再改写），切回「当前运行」自动解冻
        self._stat_frozen = False
        # 检索按钮「返回」模式：点「检索」后按钮变「返回」，再点恢复默认统计状态
        self._search_return_mode = False
        # 产品筛选（检索按钮左侧多选下拉）当前勾选的产品列表
        self._stat_filter_products = []
        self._live = False
        self._live_total = 0
        self._live_good = 0.0
        self._live_bad = 0.0
        self.period_times = period_times or load_period_times()
        self.stat_mode = "按剔除口统计"
        self.stat_datasets = {}
        self._period_yield = ""
        # 镜像模式：调试界面在生产运行态下复用生产运行界面的实时统计（单一数据源），
        # 由外部 provider 提供快照、由 owner 统一处理时段/清零，保证两界面数据一致。
        self._live_provider = None
        self._mirror = False
        self._mirror_owner = None
        self._live_yield_target = None
        self._live_rechk_target = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 统计时段筛选：切换后所有示例数据联动刷新
        frow = QHBoxLayout()
        frow.setSpacing(8)
        cb = QComboBox()
        cb.addItems(["当前运行", "指定时间段", "白班", "中班", "晚班"])
        cb.setMinimumHeight(28)
        cb.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        cb.currentTextChanged.connect(
            lambda t: self.log_operation(getattr(self, "_op_user", "操作员"),
                                         f"切换了统计时段为 {t}"))
        d1 = QLineEdit("开始日期")
        d1.setMinimumHeight(28)
        d1.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        d2 = QLineEdit("结束日期")
        d2.setMinimumHeight(28)
        d2.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        frow.addWidget(cb)
        frow.addWidget(d1, 1)
        frow.addWidget(d2, 1)
        # 「检索」按钮左侧的产品多选筛选下拉：列出新建过的产品，可复选；选中项随检索生效
        self._product_filter = ProductFilterCombo(provider=lambda: self._resolve_products())
        self._product_filter.selectionChanged.connect(self._on_stat_filter_changed)
        frow.addWidget(self._product_filter)
        # 该行按钮（自左向右）：「检索」按检索方式+时间范围刷新统计并固定显示；「导出」弹出生产报表页面
        self._btn_search_stat = QPushButton("检索")
        self._btn_search_stat.setFixedHeight(28)
        self._btn_search_stat.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_search_stat.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 6px; "
            f"font-size: 9px; }}"
            f"QPushButton:hover:!disabled {{ background-color: {COLORS['accent_blue']}; color: white; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']}; }}")
        self._btn_search_stat.clicked.connect(self._on_search_stats)
        # 该行最右侧「导出」按钮：点击弹出生产报表页面
        self._btn_export_report = QPushButton("导出")
        self._btn_export_report.setFixedHeight(28)
        self._btn_export_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export_report.setToolTip("导出生产报表")
        self._btn_export_report.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 6px; "
            f"font-size: 9px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; color: white; }}")
        self._btn_export_report.clicked.connect(self._open_production_report)
        frow.addWidget(self._btn_search_stat)
        frow.addWidget(self._btn_export_report)
        lay.addLayout(frow)

        # KPI：单行 7 项，数值双击可编辑（数据取自当前时段）
        kpi_items = PERIOD_DATA[self.period]["kpi"]
        self.kpi_grid = EditableKpiGrid(kpi_items, cols=7)
        self._kpi_example = kpi_items
        lay.addWidget(self.kpi_grid)

        # 环形图 + 图例 + 按相机 / 按缺陷项统计视图
        self.stat_datasets = {m: [tuple(x) for x in PERIOD_DATA[self.period]["donut"][m]]
                              for m in PERIOD_DATA[self.period]["donut"]}
        # 饼图 / 详情 视图模式（与生产运行界面一致：默认饼图）
        self._chart_view_mode = "pie"
        data = self.stat_datasets[self.stat_mode]
        self.chart_stack = QStackedWidget()

        # 饼图 / 详情 切换按钮（与生产运行界面卡片标题栏右侧一致），需在 _set_chart_view 之前创建
        self._btn_pie = QPushButton("饼图")
        self._btn_detail = QPushButton("详情")
        for b in (self._btn_pie, self._btn_detail):
            b.setFixedHeight(22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont("Microsoft YaHei", 9))
        self._btn_pie.clicked.connect(lambda: self._set_chart_view("pie"))
        self._btn_detail.clicked.connect(lambda: self._set_chart_view("detail"))

        # 第 0 页：饼图 / 详情 可切换容器（默认显示饼图）
        chart_container = QWidget()
        chart_container.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        container_layout = QVBoxLayout(chart_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        self._inner_stack = QStackedWidget()

        donut_page = QWidget()
        donut_page.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        chart_box = QHBoxLayout(donut_page)
        chart_box.setContentsMargins(0, 0, 0, 0)
        chart_box.setSpacing(20)
        chart_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.donut_chart = DonutChart(data)
        self.donut_chart.setFixedSize(160, 160)
        chart_box.addWidget(self.donut_chart)
        # 右侧图例：剔除口 / 数量 / 比例 三列左对齐（网格布局保证列对齐，列间隙适中）
        self.legend_layout = QGridLayout()
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setHorizontalSpacing(12)
        self.legend_layout.setVerticalSpacing(6)
        self._refresh_legend(data)
        chart_box.addLayout(self.legend_layout)
        self._inner_stack.addWidget(donut_page)

        # 详情页：各相机不同剔除口的数量及比例（与生产运行界面「详情」一致）
        self._reject_detail_view = RejectDetailView()
        self._inner_stack.addWidget(self._reject_detail_view)

        container_layout.addWidget(self._inner_stack, 1)
        self.chart_stack.addWidget(chart_container)

        # 第 1 页：按相机统计（标签页 + 双表）
        self.camera_stats_view = CameraStatsView(
            camera_stats_data=PERIOD_DATA[self.period]["camera_stats"],
            camera_defects_data=PERIOD_DATA[self.period]["camera_defects"])
        self.chart_stack.addWidget(self.camera_stats_view)

        # 第 2 页：按缺陷项统计（饼图 / 详情 切换容器，与生产运行界面一致）
        self.defect_stats_view = DefectStatsContainer(
            camera_defects_data=PERIOD_DATA[self.period]["camera_defects"])
        self.chart_stack.addWidget(self.defect_stats_view)

        # 默认显示饼图，并初始化详情表
        self._set_chart_view("pie")

        # 速度指标（同一行显示，颜色区分）
        srow = QHBoxLayout()
        srow.setSpacing(12)
        s1 = QLabel("平均速度：0 Pcs/Min")
        s1.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        s2 = QLabel("瞬时速度：0 Pcs/Min")
        s2.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        self.s1 = s1
        self.s2 = s2
        srow.addWidget(s1)
        srow.addStretch()
        srow.addWidget(s2)
        lay.addLayout(srow)

        # 速度示例值：平均 / 瞬时速度随机波动（演示用，每秒刷新一次）
        self._avg_speed = 0
        self._inst_speed = 0.0
        self._stop_elapsed = 0
        self._speed_running = False
        self._speed_stopped = False
        self._speed_timer = QTimer(self)
        self._speed_timer.timeout.connect(self._tick_speed)
        self._speed_timer.start(1000)
        self._tick_speed()

        # 饼图 / 详情 切换按钮行（按钮已在上方创建）：置于图表区上方（与卡片标题栏右侧一致）
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(6)
        toggle_row.addStretch(1)
        toggle_row.addWidget(self._btn_pie)
        toggle_row.addWidget(self._btn_detail)
        lay.addLayout(toggle_row)
        lay.addWidget(self.chart_stack, 1)

        # 统计操作按钮（同一行显示）：仅保留「统计配置」「统计清零」两个操作按钮
        self.stat_mode_buttons = {}
        op_names = ["统计配置", "统计清零"]
        brow = QHBoxLayout()
        self._stats_btn_row = brow
        brow.setSpacing(6)
        for name in op_names:
            b = QPushButton(name)
            b.setMinimumHeight(28)
            if name == "统计清零":
                b.clicked.connect(self._toggle_clear)
                self._clear_btn = b
                self._style_clear_button(b, False)
            elif name == "统计配置":
                # 统计配置：蓝色底、白字，点击后底色不变（暂未绑定具体配置对话框）
                self._config_btn = b
                b.setStyleSheet(_BLUE_BTN_STYLE)
            else:
                b.setStyleSheet(
                    f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                    f"font-size: 10px; padding: 4px 10px;")
            brow.addWidget(b)
        brow.addStretch(1)
        # 统计方式切换按钮：移到最右侧（与生产运行界面、调试界面保持一致）
        for name in ("按剔除口统计", "按缺陷项统计"):
            b = QPushButton(name)
            b.setMinimumHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont("Microsoft YaHei", 9))
            b.clicked.connect(lambda checked, m=name: self._set_stat_mode(m))
            self.stat_mode_buttons[name] = b
            self._style_mode_button(b, name == self.stat_mode)
            brow.addWidget(b)
        lay.addLayout(brow)

        # 时段切换联动
        self.period_cb = cb
        self.d_start = d1
        self.d_end = d2
        cb.currentTextChanged.connect(self._set_period)
        cb.currentTextChanged.connect(self._refresh_search_btn)
        d1.textChanged.connect(self._on_time_edited)
        d2.textChanged.connect(self._on_time_edited)
        # 初始化：回填当前时段的默认起止时间并渲染示例数据
        self._set_period(self.period)
        register_restyle(self._restyle)

    def _restyle(self):
        # 与 __init__ 一致：ID 选择器仅作用于面板自身，避免级联给子孙控件画出边框
        self.setStyleSheet(
            f"#statsPanel {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; }}")
        for name, btn in self.stat_mode_buttons.items():
            self._style_mode_button(btn, name == self.stat_mode)
        if getattr(self, "_clear_btn", None) is not None:
            self._style_clear_button(self._clear_btn, self._cleared)
        if getattr(self, "_config_btn", None) is not None:
            self._config_btn.setStyleSheet(_BLUE_BTN_STYLE)
        if hasattr(self, "_btn_pie"):
            self._style_chart_view_button(self._btn_pie, self._chart_view_mode == "pie")
            self._style_chart_view_button(self._btn_detail, self._chart_view_mode == "detail")
        self.s1.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        self.s2.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")

    def _style_mode_button(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"background-color: {COLORS['accent_orange']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 10px; "
                f"padding: 4px 10px; font-weight: bold;")
        else:
            btn.setStyleSheet(
                f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 10px; padding: 4px 10px;")

    def _set_chart_view(self, mode):
        """饼图 / 详情 视图切换（按剔除口统计 与 按缺陷项统计 下可见），与生产运行界面一致。"""
        self._chart_view_mode = mode
        self._style_chart_view_button(self._btn_pie, mode == "pie")
        self._style_chart_view_button(self._btn_detail, mode == "detail")
        if self.stat_mode == "按缺陷项统计":
            # 缺陷项统计容器：饼图（聚合缺陷分布）+ 详情（逐相机 SPC 七列）
            self.defect_stats_view.set_view(mode)
        else:
            self._inner_stack.setCurrentIndex(0 if mode == "pie" else 1)
            if mode == "detail":
                self._refresh_reject_detail()

    def _style_chart_view_button(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"background-color: {COLORS['accent_orange']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 12px; "
                f"padding: 2px 12px; font-weight: bold;")
        else:
            btn.setStyleSheet(
                f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 12px; padding: 2px 12px;")

    def _set_stat_mode(self, mode):
        self.stat_mode = mode
        # 按缺陷项统计 -> 第 2 页（缺陷项 × 相机 矩阵，含饼图/详情切换）
        # 按剔除口统计（默认）-> 第 0 页（环形图 / 详情 可切换容器）
        if mode == "按缺陷项统计":
            self.chart_stack.setCurrentIndex(2)
            show_toggle = True
        else:
            # 默认「按剔除口统计」：刷新环形图与图例，并回到饼图视图
            self.chart_stack.setCurrentIndex(0)
            show_toggle = True
            if mode == "按剔除口统计":
                self._set_chart_view("pie")
            data = self.stat_datasets[mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = self._period_yield
            self.donut_chart.update()
            self._refresh_legend(data)
        # 饼图/详情 切换按钮在两种统计方式下均可见
        self._btn_pie.setVisible(show_toggle)
        self._btn_detail.setVisible(show_toggle)
        # 进入「按缺陷项统计」时，默认回到饼图视图
        if show_toggle and mode != "按剔除口统计":
            self._set_chart_view("pie")
        for name, btn in self.stat_mode_buttons.items():
            self._style_mode_button(btn, name == mode)

    def _build_reject_detail_rows(self, data, stats):
        """由当前「按剔除口统计」环形图与各相机统计，生成详情明细行。

        每行：(相机, 良品率, 总数, 良品数, 不良1数, 不良2数, 重检数)。
        总数 = 良品数 + 不良1数 + 不良2数 + 重检数。
        重检数按「各相机(良品+不良)占全局之比」从环形图 RST（== KPI 重检数）分摊，
        保证「表格重检数之和 == 概览 KPI 重检数」严格一致；不良1/2 数对应 NG1/NG2
        按其在环形图占比分摊到各相机。各相机总数因权重近均匀而基本一致（仅微小偏差）。
        """
        ng1 = ng2 = rst = 0
        for l, v, _ in data:
            if l == "NG1":
                ng1 = v
            elif l == "NG2":
                ng2 = v
            elif l == "RST":
                rst = v
        s = ng1 + ng2
        ng_w = [ng1 / s, ng2 / s] if s > 0 else [0.0, 0.0]
        # 收集各相机的 良品数 / 不良品数，作为重检分摊基数
        cam_infos = []
        for cam in getattr(self.camera_stats_view, "cameras", []):
            cam_data = stats.get(cam)
            if cam_data is None:
                continue
            good = int(cam_data.get("良品数", 0))
            bad = int(cam_data.get("不良品数", 0))
            cam_infos.append((cam, good, bad))
        base = sum(g + b for _, g, b in cam_infos) or 1
        rows = []
        for cam, good, bad in cam_infos:
            rechk = int(round(rst * (good + bad) / base))
            counts = _distribute(bad, ng_w) if bad > 0 else [0, 0]
            ng1_c, ng2_c = counts[0], counts[1]
            total = good + ng1_c + ng2_c + rechk
            rate = f"{good / total * 100:.2f}%" if total else "0.00%"
            row = (
                cam,
                rate,
                str(total),
                str(good),
                str(ng1_c),
                str(ng2_c),
                str(rechk),
            )
            rows.append(row)
        return rows

    def _refresh_reject_detail(self):
        """刷新「详情」页：按相机显示良品率 / 总数 / 良品数 / 不良1数 / 不良2数 / 重检数。"""
        if not hasattr(self, "_reject_detail_view"):
            return
        if self._cleared:
            self._reject_detail_view.set_data([])
            return
        data = self.stat_datasets.get("按剔除口统计", [])
        stats = getattr(self.camera_stats_view, "camera_stats_data", {}) or {}
        rows = self._build_reject_detail_rows(data, stats)
        self._reject_detail_view.set_data(rows)

    def set_speed_running(self, running):
        """由设备启动/停止同步速度刷新状态：
        - running=True：进入生产运行态，平均/瞬时速度复位到 11000 并开始波动刷新；
        - running=False：进入停止态，平均速度缓慢衰减（每秒 ×0.96）；瞬时速度独立快速
          衰减，5 秒内明显下降、10 秒后归零（衰减快于平均速度）。"""
        running = bool(running)
        self._speed_running = running
        if running:
            self._speed_stopped = False
            self._avg_speed = 11000
            self._inst_speed = 11000.0
            self._stop_elapsed = 0
        else:
            self._speed_stopped = True
            self._stop_elapsed = 0
        self._tick_speed()

    def _tick_speed(self):
        """刷新速度示例值。

        - 生产运行态（_speed_running=True）：平均速度围绕 11000 ±150 随机游走并钳制在
          [10850, 11150]；瞬时速度随机比平均速度大或小（演示用，每秒刷新一次）。
        - 停止后（_speed_stopped=True）：平均速度缓慢衰减（每秒 ×0.96）；瞬时速度独立
          快速衰减（每秒 ×0.70），5 秒内明显下降、第 10 秒归零，衰减快于平均速度。
        - 未启动（idle）：保持 0，不刷新。"""
        if self._speed_running:
            self._avg_speed = max(
                10850, min(11150, self._avg_speed + random.uniform(-150, 150)))
            avg = int(round(self._avg_speed))
            sign = random.choice([-1, 1])
            self._inst_speed = max(0.0, avg + sign * random.uniform(80, 400))
            inst = int(round(self._inst_speed))
        elif self._speed_stopped:
            # 平均速度：缓慢衰减（与原有行为一致）
            if self._avg_speed > 0:
                self._avg_speed = self._avg_speed * 0.96
                if self._avg_speed < 60:
                    self._avg_speed = 0
            avg = int(round(self._avg_speed))
            # 瞬时速度：独立快速衰减，第 10 秒归零（明显快于平均速度）
            self._stop_elapsed = getattr(self, "_stop_elapsed", 0) + 1
            if self._stop_elapsed >= 10:
                self._inst_speed = 0.0
            else:
                self._inst_speed = max(0.0, getattr(self, "_inst_speed", 0.0) * 0.70)
                if self._inst_speed < 30:
                    self._inst_speed = 0.0
            inst = int(round(self._inst_speed))
        else:
            avg = 0
            inst = 0
        self.s1.setText(f"平均速度：{avg} Pcs/Min")
        self.s2.setText(f"瞬时速度：{inst} Pcs/Min")

    def _refresh_legend(self, data):
        """按剔除口统计饼图右侧图例：剔除口 / 数量 / 比例 三列左对齐（带颜色点）。"""
        grid = self.legend_layout
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        total = sum(v for _, v, _ in data)
        # 表头（三列左对齐）
        hdr = "font-size: 10px; font-weight: bold; color: %s;" % COLORS["text_primary"]
        for c, txt in enumerate(["剔除口", "数量", "比例"]):
            h = QLabel(txt)
            h.setStyleSheet(hdr)
            h.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(h, 0, c + 1)
        # 数据行：颜色点 + 剔除口 + 数量 + 比例，各列左对齐
        for i, (label, value, color) in enumerate(data):
            pct = (value / total * 100) if total else 0
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(dot, i + 1, 0)
            l = QLabel(label)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            l.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(l, i + 1, 1)
            v = QLabel(str(value))
            v.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            v.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(v, i + 1, 2)
            p = QLabel(f"{pct:.1f}%")
            p.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            p.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(p, i + 1, 3)

    def _set_period(self, period):
        if self._mirror and self._mirror_owner is not None:
            # 镜像模式：本面板仅为显示镜像，时段切换不应反向驱动生产运行界面
            # （否则会触发其 _reset_live() 重置实时累计，造成「检索/切换即清零」）。
            # 生产运行界面通过快照（get_display_snapshot）驱动本面板显示，故此处仅维护
            # 本地面板状态（如「当前运行」时解除冻结），不再向 owner 转发。
            self.period = period
            if period == "当前运行":
                self._stat_frozen = False   # 切回当前运行 → 解除固定显示
                self._search_return_mode = False  # 退出「返回」模式
            self._refresh_search_btn()
            return
        if period not in PERIOD_DATA:
            return
        self.period = period
        # 「当前运行」= 实时刷新，切回后自动解冻（恢复按正常示例数据刷新）；
        # 同时退出「返回」模式，按钮复位为「检索」
        if period == "当前运行":
            self._stat_frozen = False
            self._search_return_mode = False
        self._refresh_search_btn()
        pd = PERIOD_DATA[period]
        self._kpi_example = pd["kpi"]
        self._period_yield = pd["yield"]
        if self._live:
            # 播放中切换时段：实时累计重置，按新时段良品率继续累计
            self._live_total = 0
            self._live_good = 0.0
            self._live_bad = 0.0
            self._live_tick()
            return
        self.stat_datasets = {m: [tuple(x) for x in pd["donut"][m]] for m in pd["donut"]}
        # 回填该时段的默认起止时间（白班/中班/晚班等），阻断信号避免误触发持久化
        start, end = self.period_times.get(period, ("", ""))
        self.d_start.blockSignals(True)
        self.d_end.blockSignals(True)
        self.d_start.setText(start)
        self.d_end.setText(end)
        self.d_start.blockSignals(False)
        self.d_end.blockSignals(False)
        # StatsPanel 以示例数据呈现（调试界面等场景无需实时累计）
        self.camera_stats_view.set_data(pd["camera_stats"], pd["camera_defects"])
        self.defect_stats_view.set_data(pd["camera_defects"])
        if self._cleared:
            self._apply_cleared_state()
        else:
            self.kpi_grid.set_values(self._kpi_example)
            if self.stat_mode not in ("按相机统计", "按缺陷项统计"):
                data = self.stat_datasets[self.stat_mode]
                self.donut_chart.data = data
                self.donut_chart.center_value = self._period_yield
                self.donut_chart.update()
                self._refresh_legend(data)
            self.camera_stats_view.set_cleared(False)
            self.defect_stats_view.load_example()
            self._refresh_reject_detail()

    def _on_time_edited(self, *_):
        self.period_times[self.period] = (self.d_start.text(), self.d_end.text())
        save_period_times(self.period_times)

    def _style_clear_button(self, btn, active):
        btn.setStyleSheet(_BLUE_BTN_STYLE)

    def _apply_cleared_state(self):
        self.kpi_grid.set_values(
            [(lab, "0.00%" if "%" in val else "0", col)
             for lab, val, col in self._kpi_example])
        for mode in self.stat_datasets:
            self.stat_datasets[mode] = [
                (lab, 0, col) for lab, _, col in self.stat_datasets[mode]]
        if self.stat_mode not in ("按相机统计", "按缺陷项统计"):
            data = self.stat_datasets[self.stat_mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = "0.00%"
            self.donut_chart.update()
            self._refresh_legend(data)
        self.camera_stats_view.set_cleared(True)
        self.defect_stats_view.clear_data()
        self._refresh_reject_detail()

    def log_operation(self, actor, action):
        """记录一次操作日志（与 ProductionView 同名方法保持一致，供统计时段切换、
        统计清零等回调使用）。

        StatsPanel 在调试界面等场景下独立使用，通常不持有运行日志视图，故仅本地
        保留记录；若外部通过 ``_log_view`` 注入了带 ``add`` 方法的日志视图，则同步追加显示。
        """
        if not hasattr(self, "_op_logs"):
            self._op_logs = []
        ts = datetime.now().strftime("%H:%M:%S")
        self._op_logs.append((ts, actor, action))
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            lv.add(ts, f"操作记录：{actor} {action}", "#2F80ED")

    def _toggle_clear(self):
        if self._mirror and self._mirror_owner is not None:
            # 镜像模式：统计清零委托生产运行界面统一处理
            self._mirror_owner.toggle_clear_mirror()
            return
        self._cleared = not self._cleared
        self._style_clear_button(self._clear_btn, self._cleared)
        self.log_operation(getattr(self, "_op_user", "操作员"),
                           "清零了生产统计" if self._cleared else "恢复了示例数据")
        if self._live:
            # 播放中：清零=实时值归零冻结；恢复=从零继续累计
            if self._cleared:
                self._live_total = 0
                self._live_good = 0.0
                self._live_bad = 0.0
            self._live_tick()
            return
        if self._cleared:
            self._apply_cleared_state()
        else:
            self._set_period(self.period)

    # ------------------------------------------------------------------
    # 实时累计（点击启动后由调试界面定时器驱动 tick_live 逐拍累计）：
    # 像生产运行界面一样，KPI / 环形图 / 按相机统计 / 按缺陷项统计 随时间增长。
    # ------------------------------------------------------------------
    def tick_live(self):
        if self._live:
            if self._mirror and self._live_provider is not None:
                if getattr(self, "_stat_frozen", False):
                    # 已冻结（点「检索」后）：保持当前显示的统计快照，不再拉取新数据，
                    # 实现「详细数据固定显示」，且不影响生产运行界面的实时累计。
                    return
                try:
                    snap = self._live_provider()
                except Exception:
                    snap = None
                if snap is not None:
                    self._render_mirror(snap)
                else:
                    self._live_tick()
            elif not getattr(self, "_stat_frozen", False):
                # 非镜像（独立使用）时：点「检索」后固定显示，不再逐拍累计刷新
                self._live_tick()

    def begin_mirror(self):
        """进入镜像模式：置位 _mirror 与 _live，由外部 provider 提供快照驱动刷新，
        不重置计数器（实时累计由 owner（生产运行界面）统一维护）。"""
        self._mirror = True
        self._live = True

    def _render_mirror(self, snap):
        """把外部提供的实时统计快照刷新到本面板（与 _apply_live 等价，但数据来自共享源）。"""
        self.kpi_grid.set_values(snap["kpi"])
        self.stat_datasets["按剔除口统计"] = [tuple(x) for x in snap["donut"]]
        self._period_yield = snap["period_yield"]
        if self.stat_mode == "按剔除口统计":
            self.donut_chart.data = self.stat_datasets["按剔除口统计"]
            self.donut_chart.center_value = self._period_yield
            self.donut_chart.update()
            self._refresh_legend(self.stat_datasets["按剔除口统计"])
        self.camera_stats_view.set_data(snap["camera_stats"], snap["defect_stats"])
        self.defect_stats_view.set_data(snap["defect_stats"])
        self._refresh_reject_detail()

    def _live_yield_pct(self):
        try:
            return float(str(PERIOD_DATA[self.period]["yield"]).rstrip("%"))
        except Exception:
            return 95.0

    def _live_rechk_pct(self):
        return PERIOD_DATA[self.period].get("rechk", 1.0)

    def _live_tick(self):
        # 良品率目标随机游走（带均值回归），使累计良率/不良率可见波动
        base_y = self._live_yield_pct()
        tgt = self._live_yield_target if self._live_yield_target is not None else base_y
        band = max(2.0, base_y * 0.08)
        tgt = tgt + random.uniform(-0.6, 0.6) + (base_y - tgt) * 0.05
        tgt = max(base_y - band, min(base_y + band, tgt))
        self._live_yield_target = tgt
        # 重检率目标随机游走
        base_r = self._live_rechk_pct()
        rt = self._live_rechk_target if self._live_rechk_target is not None else base_r
        rband = max(0.3, base_r * 0.8)
        rt = rt + random.uniform(-0.1, 0.1) + (base_r - rt) * 0.05
        rt = max(base_r * 0.4, min(base_r * 1.8, rt))
        self._live_rechk_target = rt
        n = 20
        g = 0
        for _ in range(n):
            if random.random() < tgt / 100.0:
                g += 1
        b = n - g
        self._live_total += n
        self._live_good += g
        self._live_bad += b
        self._apply_live()

    def _apply_live(self):
        total = self._live_total
        good = int(round(self._live_good))
        bad = int(round(self._live_bad))
        yld = (good / total * 100) if total else 0.0
        rechk_rate = self._live_rechk_target if self._live_rechk_target is not None else self._live_rechk_pct()
        rechk = int(round(total * rechk_rate / 100)) if total else 0
        bad_rate = (bad / total * 100) if total else 0.0
        rechk_rate_v = (rechk / total * 100) if total else 0.0
        kpi = [
            ("总数", str(total), COLORS["text_primary"]),
            ("良品数", str(good), COLORS["accent_green"]),
            ("不良品数", str(bad), COLORS["accent_red"]),
            ("重检数", str(rechk), COLORS["accent_yellow"]),
            ("良品率", f"{yld:.2f}%", COLORS["accent_green"]),
            ("不良率", f"{bad_rate:.2f}%", COLORS["accent_red"]),
            ("重检率", f"{rechk_rate_v:.2f}%", COLORS["accent_yellow"]),
        ]
        self.kpi_grid.set_values(kpi)
        ng1 = int(round(bad * 280 / 500))
        ng2 = int(round(bad * 120 / 500))
        rst = bad - ng1 - ng2
        self.stat_datasets["按剔除口统计"] = [
            ("OK", good, "#0D822B"), ("NG1", ng1, "#C81435"),
            ("NG2", ng2, "#FF8A80"), ("RST", rst, "#F9AA0B")]
        self.donut_chart.center_value = f"{yld:.2f}%"
        if self.stat_mode == "按剔除口统计":
            self.donut_chart.data = self.stat_datasets["按剔除口统计"]
            self.donut_chart.update()
            self._refresh_legend(self.stat_datasets["按剔除口统计"])
        cam_stats = self._build_live_cam_stats(total, good, bad)
        cam_def = self._build_live_defects(bad)
        self.camera_stats_view.set_data(cam_stats, cam_def)
        self.defect_stats_view.set_data(cam_def)
        self._refresh_reject_detail()

    def _build_live_cam_stats(self, total, good, bad):
        rechk_rate = self._live_rechk_pct()
        weights = [_CAM_WEIGHTS[f"相机{i}"] for i in range(1, 9)]
        # 把「全局总数 / 全局不良数」按相机权重（整数）拆分到 8 路相机，
        # 保证各相机之和严格等于全局总数 / 全局不良数（与 KPI、环形图口径一致），
        # 各相机「总数 = 良品数 + 不良品数」且逐相机良率围绕全局良品率波动。
        cam_total = _distribute(total, weights)
        cam_bad = _distribute(bad, weights)
        out = {}
        for i in range(8):
            cam = f"相机{i + 1}"
            ct = cam_total[i]
            cbad = cam_bad[i]
            cgood = ct - cbad
            rechk = int(round(ct * rechk_rate / 100)) if ct else 0
            out[cam] = {
                "总数": str(ct),
                "良品数": str(cgood),
                "不良品数": str(cbad),
                "重检数": str(rechk),
                "良率": f"{cgood / ct * 100:.2f}%" if ct else "0.00%",
                "重检率": f"{rechk / ct * 100:.2f}%" if ct else "0.00%",
            }
        return out

    def _build_live_defects(self, bad):
        weights = [_CAM_WEIGHTS[f"相机{i}"] for i in range(1, 9)]
        # 与 _build_live_cam_stats 同一口径拆分相机不良数，保证各相机之和=全局不良数
        cam_bad = _distribute(bad, weights)
        sum_base = sum(_DEFECT_BASE.values()) or 1
        out = {}
        for i, cam in enumerate([f"相机{i}" for i in range(1, 9)]):
            cbad = cam_bad[i]
            # 按缺陷基准权重把该相机的不良数拆到各缺陷项，保证各缺陷项之和=相机不良数
            dist = _distribute(
                cbad, [_DEFECT_BASE[d] for d in _DEFECT_TYPES])
            s = cbad or 1
            out[cam] = [(d, str(dist[j]),
                        f"{dist[j] / s * 100:.2f}%")
                       for j, d in enumerate(_DEFECT_TYPES)]
        return out


# 设备详细信息弹窗：展示用户中心「设备配置」内的全部设备信息
_DEVICE_EXAMPLES = {
    "设备型号": "VI-3000S",
    "出厂日期": "2025-01-20",
    "设备功率": "2.4 kW",
}


class DeviceDetailDialog(QDialog):
    """点击生产信息页「设备编码」右侧圆形「i」按钮弹出的设备详情窗口。

    内容取自用户中心的设备配置：软件名称 + 设备编码 / 名称 / 产线编号 /
    型号 / 出厂日期 / 功率。缺失字段用用户中心示例值兜底，保证展示完整。
    """

    @staticmethod
    def _f(bold=False):
        """与全局暗色主题一致的 12px 字体（CSS 像素，非 12pt）。"""
        f = QFont("Microsoft YaHei", QFont.Weight.Bold if bold else QFont.Weight.Normal)
        f.setPixelSize(12)
        return f

    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self.setWindowTitle("设备详细信息")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        dc = dict(manager.device_code) if manager is not None else {}
        merged = dict(_DEVICE_EXAMPLES)
        merged.update({k: dc.get(k, "") for k in
                       ["设备编码", "设备名称", "设备型号", "出厂日期", "设备功率"]})
        rows = [
            (k, merged.get(k, "")) for k in
            ["设备编码", "设备名称", "设备型号", "出厂日期", "设备功率"]
        ]

        card = QFrame()
        card.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; padding: 12px;")
        cl = QVBoxLayout(card)
        cl.setSpacing(10)
        # 第一列（标签）宽度按最长标签文字实测，保证完整显示不被截断
        _fm = QFontMetrics(self._f())
        _label_w = max(max((_fm.horizontalAdvance(t) for t, _ in rows), default=0) + 12, 96)
        for label_text, value_text in rows:
            r = QHBoxLayout()
            r.setSpacing(10)
            k = QLabel(label_text)
            k.setFixedWidth(_label_w)
            k.setFont(self._f())
            k.setStyleSheet(f"color: {COLORS['text_secondary']};")
            v = QLabel(str(value_text) if value_text != "" else "—")
            v.setFont(self._f())
            v.setStyleSheet(f"color: {COLORS['text_primary']};")
            # 单行完整显示，不自动换行（避免错行）
            v.setWordWrap(False)
            v.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            r.addWidget(k)
            r.addWidget(v, 1)
            cl.addLayout(r)
        root.addWidget(card)
        root.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Microsoft YaHei", 12))
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; padding: 0 16px; }}"
            f"QPushButton:hover {{ background-color: #E08A2B; }}")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)


# ---------------------------------------------------------------------------
# 生产报表（按参考图设计）：快捷时段 + 各相机检测项
# ---------------------------------------------------------------------------
_REPORT_QUICK_RANGES = ["10分钟", "15分钟", "30分钟", "45分钟",
                        "1小时", "2小时", "3小时", "4小时",
                        "6小时", "8小时", "12小时", "1天"]

_REPORT_QUICK_MINUTES = {
    "10分钟": 10, "15分钟": 15, "30分钟": 30, "45分钟": 45,
    "1小时": 60, "2小时": 120, "3小时": 180, "4小时": 240,
    "6小时": 360, "8小时": 480, "12小时": 720, "1天": 1440,
}

# 每路相机的检测项：(检测项名, 子项名, 基准耗时 ms)；名称含 {} 时填入相机号
_REPORT_CAM_ITEMS = [
    ("图像源[{}]", "触发图像源", 0),
    ("□1平面定位 v10536", "平面定位 v10536", 0),
    ("缺角", "AI推理", 19),
    ("□2平面定位 v10535", "平面定位 v10535", 0),
    ("□3定位扩展 v10536", "定位扩展 v10536", 0),
    ("□1台上直线", "直线定位", 5),
    ("□4图素定位 v10532", "图素定位 v1052", 3),
    ("台阶测量面", "定位扩展 v10536", 0),
    ("台阶图层", "平面配合", 1),
    ("FA3锐线倒度", "通用孔锐度", 23),
    ("VMPofile(v10536)", "VM选择图", 0),
    ("□2侧距测量VMRectangle v10528", "矩形测量", 5),
    ("FA7台阶面-平面度", "平面配合", 18),
    ("VMPaneFitting v10536", "平面配合", 0),
]

# 班次检索（当日时段）：白班 08:00-16:00 / 中班 16:00-24:00 / 夜班 00:00-08:00
_REPORT_SHIFTS = ["白班", "中班", "夜班"]
_REPORT_SHIFT_HOURS = {"白班": (8, 16), "中班": (16, 24), "夜班": (0, 8)}

# 筛选数据四项（示例值取自程序当前配置 / 设备信息，见 _ReportExportMixin._report_product_info）
_REPORT_FILTER_KEYS = ["产品类型", "产品型号", "产品料号", "产品批号"]


class ProductionReportDialog(QDialog):
    """生产报表窗口：由「统计信息」卡片「导出」按钮或左侧导航「生产报表」打开。

    版式按参考图设计，分三栏：
      左栏：检索数据（站点序号 / 时间范围 / 快捷时段 / 检索）、筛选数据（产品名称 / 批次）、
            报表导出（报表类型 / 导出）；
      中栏：8 路相机的检测项明细卡片（检测项 / 子项 / 判定 / 耗时）；
      右栏：产品列表（分页 + 良品/缺陷标记）与数据统计（总数 / 良品 / 缺陷 / 待定）。
    """

    LEFT_W = 448     # 加宽左栏，保证「检索数据」内 18 位时间串等文字完整显示
    RIGHT_W = 292
    CAM_CARD_H = 200

    def __init__(self, parent=None, period="当前运行", start="", end="",
                 kpi=None, donut=None, cam_stats=None, product=None):
        super().__init__(parent)
        self.setWindowTitle("生产报表")
        self.setModal(True)
        self.setMinimumSize(1300, 700)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        self._period = period
        self._kpi = list(kpi or [])
        self._donut = list(donut or [])
        self._cam_stats = dict(cam_stats or {})
        self._product = dict(product or {})
        self._quick_active = "12小时"
        self._shift_active = None
        self._rnd = random.Random(20260910)   # 固定种子：报表示例数据稳定、可复现

        now = datetime.now()
        self._sel_start = self._fmt_ts(
            now - timedelta(minutes=_REPORT_QUICK_MINUTES["12小时"]))
        self._sel_end = self._fmt_ts(now)

        self._cam_item_layouts = []
        self._prod_layout = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 「关闭」按钮位于左栏「报表导出」卡片内（导出按钮下方），故此处不再单独放底部按钮行
        cols = QHBoxLayout()
        cols.setSpacing(10)
        cols.addWidget(self._build_left(), 0)
        cols.addWidget(self._build_center(), 1)
        cols.addWidget(self._build_right(), 0)
        root.addLayout(cols, 1)

    # ------------------------------------------------------------------ 样式
    @staticmethod
    def _fmt_ts(dt):
        """参考图时间格式：20260910 09:31:21."""
        return dt.strftime("%Y%m%d %H:%M:%S.")

    @staticmethod
    def _lab_style():
        return (f"color: {COLORS['text_secondary']}; background-color: transparent; "
                f"font-size: 12px;")

    @staticmethod
    def _sub_style():
        return (f"color: {COLORS['text_secondary']}; background-color: transparent; "
                f"font-size: 11px;")

    @staticmethod
    def _primary_style():
        return (f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: #5A78FF; }}")

    @staticmethod
    def _mini_btn_style():
        return (f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
                f"color: {COLORS['accent_blue']}; border: 1px solid {COLORS['accent_blue']}; "
                f"border-radius: 3px; font-size: 11px; padding: 0 6px; }}"
                f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; color: white; }}")

    @staticmethod
    def _badge_style(status):
        color = {"良品": COLORS["accent_green"], "缺陷": COLORS["accent_red"]}.get(
            status, COLORS["accent_yellow"])
        return (f"QLabel {{ background-color: {color}; color: white; border-radius: 8px; "
                f"font-size: 11px; padding: 1px 6px; }}")

    def _card(self, title=None):
        """返回（卡片 QFrame, 其纵向布局）；卡片带标题。"""
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setStyleSheet(
                f"color: {COLORS['text_primary']}; background-color: transparent; "
                f"font-size: 13px; font-weight: bold;")
            lay.addWidget(t)
        return f, lay

    @staticmethod
    def _scroll():
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        s.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return s

    # -------------------------------------------------------------- 左栏
    def _build_left(self):
        w = QWidget()
        w.setFixedWidth(self.LEFT_W)
        w.setStyleSheet("background-color: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # —— 检索数据 ——
        card, cl = self._card("检索数据")
        r = QHBoxLayout()
        r.setSpacing(6)
        lab = QLabel("站点序号")
        lab.setStyleSheet(self._lab_style())
        self._site_cb = QComboBox()
        self._site_cb.addItems(["1", "2", "3", "4"])
        self._site_cb.setMinimumHeight(28)
        r.addWidget(lab)
        r.addWidget(self._site_cb, 1)
        cl.addLayout(r)

        tr = QHBoxLayout()
        tr.setSpacing(6)
        self._start_edit = QLineEdit(self._sel_start)
        self._end_edit = QLineEdit(self._sel_end)
        for e in (self._start_edit, self._end_edit):
            e.setMinimumHeight(28)
            e.setMinimumWidth(202)   # 容下 18 位时间串（20260910 09:31:21.）完整显示
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.setStyleSheet(self._input_style())
        tilde = QLabel("~")
        tilde.setStyleSheet(self._lab_style())
        tr.addWidget(self._start_edit, 1)
        tr.addWidget(tilde)
        tr.addWidget(self._end_edit, 1)
        cl.addLayout(tr)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._quick_btns = {}
        for i, name in enumerate(_REPORT_QUICK_RANGES):
            b = QPushButton(name)
            b.setMinimumHeight(26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._on_quick_range(n))
            self._quick_btns[name] = b
            grid.addWidget(b, i // 4, i % 4)
        cl.addLayout(grid)

        # 班次检索：白班 / 中班 / 夜班
        srow = QHBoxLayout()
        srow.setSpacing(6)
        sl = QLabel("班次")
        sl.setStyleSheet(self._lab_style())
        srow.addWidget(sl)
        self._shift_btns = {}
        for name in _REPORT_SHIFTS:
            b = QPushButton(name)
            b.setMinimumHeight(26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._on_shift(n))
            self._shift_btns[name] = b
            srow.addWidget(b, 1)
        cl.addLayout(srow)
        self._style_quick_btns()

        self._search_btn = QPushButton("检索")
        self._search_btn.setMinimumHeight(30)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.setStyleSheet(self._primary_style())
        self._search_btn.clicked.connect(self._refresh_data)
        cl.addWidget(self._search_btn)
        lay.addWidget(card)

        # —— 筛选数据 ——（产品类型 / 产品型号 / 产品料号 / 产品批号；示例值取自程序当前配置）
        card2, cl2 = self._card("筛选数据")
        self._filter_cbs = {}
        for key in _REPORT_FILTER_KEYS:
            rr = QHBoxLayout()
            rr.setSpacing(6)
            l = QLabel(key)
            l.setFixedWidth(60)
            l.setStyleSheet(self._lab_style())
            cb = QComboBox()
            cb.setMinimumHeight(28)
            val = str(self._product.get(key, "") or "").strip()
            cb.addItem(val if val else "—")
            self._filter_cbs[key] = cb
            rr.addWidget(l)
            rr.addWidget(cb, 1)
            cl2.addLayout(rr)
        lay.addWidget(card2)

        # —— 报表导出 ——
        card3, cl3 = self._card("报表导出")
        rr = QHBoxLayout()
        rr.setSpacing(6)
        l = QLabel("报表类型")
        l.setFixedWidth(60)
        l.setStyleSheet(self._lab_style())
        self._type_cb = QComboBox()
        self._type_cb.addItems(["0-不含待定,测量项区分相机号",
                                "1-含待定,测量项区分相机号",
                                "2-不含待定,测量项不区分相机号"])
        self._type_cb.setMinimumHeight(28)
        rr.addWidget(l)
        rr.addWidget(self._type_cb, 1)
        cl3.addLayout(rr)
        self._export_btn = QPushButton("导出")
        self._export_btn.setMinimumHeight(30)
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet(self._primary_style())
        self._export_btn.clicked.connect(self._save_to_file)
        cl3.addWidget(self._export_btn)
        # 「关闭」放在「导出」下方（不再置于窗口右下角）
        self._close_btn = QPushButton("关闭")
        self._close_btn.setMinimumHeight(30)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 4px; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: #E08A2B; }}")
        self._close_btn.clicked.connect(self.accept)
        cl3.addWidget(self._close_btn)
        lay.addWidget(card3)

        lay.addStretch(1)
        return w

    @staticmethod
    def _input_style():
        # 10px：兼顾可读性，同时保证 18 位时间串在栏宽内完整显示（不截断）
        return (f"QLineEdit {{ background-color: {COLORS['bg_dark']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 4px; font-size: 10px; padding: 0 4px; }}")

    def _style_quick_btns(self):
        active = (f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
                  f"border: none; border-radius: 3px; font-size: 11px; }}")
        idle = (f"QPushButton {{ background-color: {COLORS['bg_dark']}; "
                f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 3px; font-size: 11px; }}"
                f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; "
                f"color: {COLORS['accent_blue']}; }}")
        for name, b in getattr(self, "_quick_btns", {}).items():
            b.setStyleSheet(active if name == self._quick_active else idle)
        for name, b in getattr(self, "_shift_btns", {}).items():
            b.setStyleSheet(active if name == self._shift_active else idle)

    def _on_quick_range(self, name):
        """点击快捷时段：同步时间范围输入框并刷新高亮（与班次检索互斥）。"""
        self._quick_active = name
        self._shift_active = None
        now = datetime.now()
        self._sel_start = self._fmt_ts(
            now - timedelta(minutes=_REPORT_QUICK_MINUTES.get(name, 60)))
        self._sel_end = self._fmt_ts(now)
        self._start_edit.setText(self._sel_start)
        self._end_edit.setText(self._sel_end)
        self._style_quick_btns()

    def _on_shift(self, name):
        """按班次检索：白班 08:00-16:00 / 中班 16:00-24:00 / 夜班 00:00-08:00（当日）。"""
        self._shift_active = name
        self._quick_active = None
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        sh, eh = _REPORT_SHIFT_HOURS.get(name, (0, 8))
        start = today + timedelta(hours=sh)
        end = (today + timedelta(hours=23, minutes=59, seconds=59)
               if eh >= 24 else today + timedelta(hours=eh))
        self._sel_start = self._fmt_ts(start)
        self._sel_end = self._fmt_ts(end)
        self._start_edit.setText(self._sel_start)
        self._end_edit.setText(self._sel_end)
        self._style_quick_btns()

    # -------------------------------------------------------------- 中栏
    def _build_center(self):
        w = QWidget()
        w.setStyleSheet("background-color: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i in range(8):
            grid.addWidget(self._camera_card(i), i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        return w

    def _camera_card(self, idx):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        card.setFixedHeight(self.CAM_CARD_H)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(f"相机 1-{idx + 1}")
        name.setStyleSheet(
            f"color: {COLORS['text_primary']}; background-color: transparent; "
            f"font-size: 12px; font-weight: bold;")
        head.addWidget(name)
        head.addStretch(1)
        for txt in ("查看详情", "查看图像"):
            b = QPushButton(txt)
            b.setFixedHeight(20)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(self._mini_btn_style())
            b.clicked.connect(lambda _=False, c=idx, t=txt: self._on_cam_action(c, t))
            head.addWidget(b)
        lay.addLayout(head)

        scroll = self._scroll()
        inner = QWidget()
        inner.setStyleSheet("background-color: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(3)
        self._fill_cam_items(il, idx)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self._cam_item_layouts.append(il)
        return card

    def _fill_cam_items(self, il, idx):
        while il.count():
            it = il.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for i, (nm, sub, base_ms) in enumerate(_REPORT_CAM_ITEMS):
            il.addWidget(self._item_row(idx, i, nm, sub, base_ms))
        il.addStretch(1)

    def _item_row(self, cam, i, name, sub, base_ms):
        """单个检测项：第一行 检测项名；第二行 子项 + 判定 + 耗时。"""
        verdict = "缺陷" if self._rnd.random() < 0.12 else "良品"
        ms = base_ms + self._rnd.randint(0, 8)

        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_panel']}; "
            f"border: none; border-radius: 3px; }}")
        lay = QVBoxLayout(row)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(1)

        nm_text = str(name).format(f"1-{cam + 1}") if "{}" in str(name) else str(name)
        nm = QLabel(nm_text)
        nm.setStyleSheet(
            f"color: {COLORS['text_primary']}; background-color: transparent; "
            f"font-size: 11px;")
        lay.addWidget(nm)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        sb = QLabel(str(sub))
        sb.setStyleSheet(self._sub_style())
        bot.addWidget(sb, 1)
        badge = QLabel(verdict)
        badge.setStyleSheet(self._badge_style(verdict))
        bot.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        msl = QLabel(f"{ms}ms")
        msl.setStyleSheet(self._sub_style())
        bot.addWidget(msl, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(bot)
        return row

    def _on_cam_action(self, idx, action):
        """「查看详情 / 查看图像」：演示程序内仅记录，不另开窗口。"""
        self._last_cam_action = (idx, action)

    # -------------------------------------------------------------- 右栏
    def _build_right(self):
        w = QWidget()
        w.setFixedWidth(self.RIGHT_W)
        w.setStyleSheet("background-color: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # —— 产品列表 ——
        card, cl = self._card()
        head = QHBoxLayout()
        head.setSpacing(6)
        t = QLabel("产品列表")
        t.setStyleSheet(
            f"color: {COLORS['text_primary']}; background-color: transparent; "
            f"font-size: 13px; font-weight: bold;")
        head.addWidget(t)
        head.addStretch(1)
        self._lang_cb = QComboBox()
        self._lang_cb.addItems(["中文", "English"])
        self._lang_cb.setFixedHeight(24)
        head.addWidget(self._lang_cb)
        cl.addLayout(head)

        pager = QHBoxLayout()
        pager.setSpacing(6)
        self._prev_btn = QPushButton("◀")
        self._next_btn = QPushButton("▶")
        for b in (self._prev_btn, self._next_btn):
            b.setFixedSize(26, 24)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(self._mini_btn_style())
        self._page_lab = QLabel("1/451")
        self._page_lab.setStyleSheet(self._lab_style())
        jump = QLabel("跳至")
        jump.setStyleSheet(self._lab_style())
        self._page_edit = QLineEdit("1")
        self._page_edit.setFixedSize(42, 24)
        self._page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {COLORS['bg_dark']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 3px; font-size: 11px; }}")
        page = QLabel("页")
        page.setStyleSheet(self._lab_style())
        pager.addWidget(self._prev_btn)
        pager.addWidget(self._page_lab)
        pager.addWidget(self._next_btn)
        pager.addStretch(1)
        pager.addWidget(jump)
        pager.addWidget(self._page_edit)
        pager.addWidget(page)
        cl.addLayout(pager)

        scroll = self._scroll()
        inner = QWidget()
        inner.setStyleSheet("background-color: transparent;")
        self._prod_layout = QVBoxLayout(inner)
        self._prod_layout.setContentsMargins(0, 0, 0, 0)
        self._prod_layout.setSpacing(3)
        self._fill_records()
        scroll.setWidget(inner)
        cl.addWidget(scroll, 1)
        lay.addWidget(card, 1)

        # —— 数据统计 ——
        card2, cl2 = self._card("数据统计")
        for label, val, color in self._stat_rows():
            rr = QHBoxLayout()
            rr.setSpacing(6)
            l = QLabel(label)
            l.setStyleSheet(self._lab_style())
            v = QLabel(str(val))
            v.setStyleSheet(
                f"color: {color}; background-color: transparent; "
                f"font-size: 13px; font-weight: bold;")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rr.addWidget(l)
            rr.addWidget(v, 1)
            cl2.addLayout(rr)
        lay.addWidget(card2)
        return w

    def _fill_records(self, n=80):
        while self._prod_layout.count():
            it = self._prod_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for status, ts in self._product_records(n):
            self._prod_layout.addWidget(self._record_row(status, ts))
        self._prod_layout.addStretch(1)

    def _product_records(self, n=80):
        """产品列表示例记录：良品约 68%、缺陷约 25%、待定约 7%（与数据统计口径一致）。"""
        out = []
        t0 = datetime.now()
        for i in range(n):
            r = self._rnd.random()
            st = "良品" if r < 0.68 else ("缺陷" if r < 0.93 else "待定")
            ts = (t0 - timedelta(seconds=0.31 * i)).strftime("%Y%m%d %H:%M:%S.") + \
                f"{self._rnd.randint(0, 999):03d}"
            out.append((st, ts))
        return out

    def _record_row(self, status, ts):
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_panel']}; "
            f"border: none; border-radius: 3px; }}")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(8)
        badge = QLabel(status)
        badge.setStyleSheet(self._badge_style(status))
        badge.setFixedWidth(40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel(ts)
        t.setStyleSheet(
            f"color: {COLORS['text_primary']}; background-color: transparent; "
            f"font-size: 11px;")
        lay.addWidget(badge)
        lay.addWidget(t, 1)
        return f

    def _stat_rows(self):
        d = {lab: val for lab, val, _ in self._kpi}
        rows = [("总数", d.get("总数", "-"), COLORS["text_primary"])]
        for label, cnt_key, pct_key, color in (
                ("良品", "良品数", "良品率", COLORS["accent_green"]),
                ("缺陷", "不良品数", "不良率", COLORS["accent_red"]),
                ("待定", "重检数", "重检率", COLORS["accent_yellow"])):
            cnt = d.get(cnt_key, "-")
            pct = d.get(pct_key, "")
            rows.append((label, f"{cnt} ({pct})" if pct else str(cnt), color))
        return rows

    # ------------------------------------------------------------ 刷新/导出
    def _refresh_data(self):
        """「检索」：换一组示例数据重绘相机检测项与产品列表。"""
        self._rnd = random.Random()
        for idx, il in enumerate(self._cam_item_layouts):
            self._fill_cam_items(il, idx)
        if self._prod_layout is not None:
            self._fill_records()
        if hasattr(self, "_start_edit"):
            self._sel_start = self._start_edit.text()
            self._sel_end = self._end_edit.text()

    def report_text(self):
        """把报表渲染为纯文本（导出为文件用）。"""
        d = {lab: val for lab, val, _ in self._kpi}
        lines = [
            "生产报表", "=" * 44,
            f"统计时段：{self._period}",
            f"时间范围：{self._sel_start} ~ {self._sel_end}",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "", "一、生产汇总",
        ]
        for lab, val, _ in self._kpi:
            lines.append(f"  {lab}：{val}")
        lines += ["", "二、数据统计"]
        for label, val, _ in self._stat_rows():
            lines.append(f"  {label}：{val}")
        lines += ["", "三、按剔除口分布"]
        tot = sum(int(v) for _, v, _ in self._donut) or 0
        for lab, v, _ in self._donut:
            pct = (v / tot * 100) if tot else 0
            lines.append(f"  {lab}：{int(v)}（{pct:.2f}%）")
        lines += ["", "四、按相机统计",
                  "  相机\t总数\t良品数\t不良品数\t重检数\t良率\t重检率"]
        for cam, dd in self._cam_stats.items():
            lines.append("  {}\t{}\t{}\t{}\t{}\t{}\t{}".format(
                cam, dd.get("总数", "-"), dd.get("良品数", "-"),
                dd.get("不良品数", "-"), dd.get("重检数", "-"),
                dd.get("良率", "-"), dd.get("重检率", "-")))
        lines += ["", "五、相机检测项明细"]
        for i in range(8):
            lines.append(f"  相机 1-{i + 1}")
            for nm, sub, base_ms in _REPORT_CAM_ITEMS:
                nm_text = str(nm).format(f"1-{i + 1}") if "{}" in str(nm) else str(nm)
                lines.append(f"    {nm_text} / {sub}")
        return "\n".join(lines)

    def _save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出生产报表", "生产报表.txt",
            "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.report_text())
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"写入文件失败：{e}")
            return
        QMessageBox.information(self, "导出成功", f"生产报表已保存到：\n{path}")


def open_production_report(parent, period, start, end, kpi, donut, cam_stats,
                           product=None):
    """打开生产报表弹窗（「统计信息」卡片「导出」与左侧导航「生产报表」共用）。"""
    dlg = ProductionReportDialog(parent, period=period, start=start, end=end,
                                 kpi=kpi, donut=donut, cam_stats=cam_stats,
                                 product=product)
    dlg.exec()
    return dlg


class ProductionView(_ReportExportMixin, QWidget):
    """生产运行界面：绝对定位的浮动面板，支持运行时拖拽与缩放。"""

    def __init__(self, parent=None, user_manager=None):
        super().__init__(parent)
        self.user_manager = user_manager
        self.setStyleSheet("background-color: transparent;")
        self._laid = False
        self.panels = []
        # 产品筛选（检索按钮左侧多选下拉）当前勾选的产品列表
        self._stat_filter_products = []
        # 检索按钮「返回」模式：点「检索」后按钮变「返回」，再点恢复默认统计状态
        self._search_return_mode = False
        # 先初始化播放 / 实时累计状态，避免 _build_panels -> _set_period 引用尚未定义的属性
        self._playing = False
        self._vision_online = True     # 视觉控制器：示例演示默认保持在线
        self._cleared = False
        self._alarm_stop_cb = None          # 达 100% 自动停机回调（由 MainWindow 注入 _on_stop）
        self._alarm_stopped = False         # 防止自动停机重复触发
        self._estop_active = False          # 急停报警激活态（红灯闪）
        self._estop_blink_on = False        # 急停红灯闪烁相位
        self._estop_timer = None            # 急停闪烁定时器（懒创建）
        self._estop_due_ts = None           # 本次运行随机安排的「急停被按下」时刻（5~60 分钟后）
        self._ion_fan_abnormal = False      # 离子风扇异常报警态（默认开启，运行中低概率出现）
        self._pending_routed = set()        # 已按「抽盒超时剔除逻辑」改判为待定的料盒（日志去重）
        self._products_per_tick = 20      # 每个播放节拍模拟经过的产品数
        # 时间基实时累计状态（播放态）：保证一分钟内「总数」差值 ≈ 显示的平均速度。
        # 此前固定「供料速度折算件数/节拍」，受 Qt 定时器实际间隔偏长影响，
        # 实测一分钟差值低于显示的平均速度（约 11000 Pcs/Min）。
        self._acc_remain = 0.0            # 每节拍不足 1 件的小数余量（滚动累加）
        self._last_accum_ts = None        # 上次实时累计时刻（time.monotonic()，播放态专用）
        self._refresh_every = 2           # 每 N 个节拍刷新一次统计视图（降频，避免频繁重建表格）
        self._reset_live()
        # 待机（未启动）示例自动累计定时器：先于 _build_panels 创建，
        # 因为 _build_panels -> _set_period 在初始化即会调用 _start_idle_sim()。
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._on_idle_tick)
        self._build_panels()
        self._period_yield = ""
        # 相机实时帧播放（点击「启动」后由 QTimer 逐帧快速刷新样张）
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)
        # 注：未点击「设备启动」前生产信息保持静态示例、不自动刷新（见 _start_idle_sim 已弃用）
        # 每路相机独立换帧步长/初相位，画面更自然、不整齐划一
        self._cam_speed = [1, 2, 1, 2, 3, 1, 2, 3]
        self._cam_phase = [0, 3, 5, 2, 4, 6, 1, 7]

    # ------------------------------------------------------------------
    # 面板创建
    # ------------------------------------------------------------------
    def _build_panels(self):
        self.cam_grid = CameraGrid(CAMERA_NAMES)
        # 相机监控面板不显示标题栏（去掉「相机监控」四字及其占用区域），
        # 让相机画布按整体页面高度填充
        cam = FloatPanel("相机监控", self, min_w=460, min_h=640, show_header=False)
        cam.set_body_layout(self.cam_grid)

        info = FloatPanel("生产信息", self, min_w=300, min_h=180)
        info.set_body_layout(self._build_device_info())
        # 生产信息面板标题栏：定量生产开启并设定良品产量后，同「生产信息」一行显示已达成设定产量的百分比
        self._achieve_label = QLabel("")
        self._achieve_label.setStyleSheet(
            f"color: {COLORS['accent_green']}; font-size: 12px; font-weight: bold;")
        self._achieve_label.setVisible(False)
        info.header.add_after_title(self._achieve_label)
        self._update_achieve()

        status = FloatPanel("设备状态", self, min_w=320, min_h=320)
        self._build_device_status()
        # 面板 min_w =「内容实需宽」（`_status_min_w`，按两列最长名称/最宽单位实算）。
        # 原来固定 320px，用户把面板拖窄后 QGridLayout 会把差额压到名称框上，
        # 最长名称（如「RST电磁阀」）被截断；提到内容实需宽后即可完整显示。
        # ⚠️ 2026-10-09：`_status_stretch_w` 已复原为 0（卡片整体宽度不改变），
        # 这里不再叠加任何人为富余——宽度只由内容实需宽决定。
        status.setMinimumWidth(max(320, getattr(self, "_status_min_w", 320)))
        status.min_w = status.minimumWidth()
        status.set_body_layout(self._status_lay)
        # 标题栏最右侧「玻璃清洁」图标+文字按钮：点击切换 DD 马达玻璃清洁运行/停止；生产运行态下禁用
        self._btn_glass_clean = QPushButton("玻璃清洁")
        self._btn_glass_clean.setFixedHeight(20)
        self._btn_glass_clean.setMinimumWidth(74)
        self._btn_glass_clean.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_glass_clean.setToolTip("玻璃清洁")
        self._btn_glass_clean.setFont(QFont("Microsoft YaHei", 9))
        # 单一模式感知图标：常态蓝色（深色卡片背景可见）、悬停/激活态白色、禁用态灰色
        gc_blue = _make_gc_icon(13, QColor(COLORS["accent_blue"]))
        gc_white = _make_gc_icon(13, QColor(255, 255, 255))
        gc_grey = _make_gc_icon(13, QColor(COLORS["text_secondary"]))
        gc_icon = QIcon()
        gc_icon.addPixmap(gc_blue.pixmap(13, 13), QIcon.Mode.Normal)
        gc_icon.addPixmap(gc_white.pixmap(13, 13), QIcon.Mode.Active)
        gc_icon.addPixmap(gc_grey.pixmap(13, 13), QIcon.Mode.Disabled)
        self._btn_glass_clean.setIcon(gc_icon)
        self._btn_glass_clean.setIconSize(QSize(13, 13))
        self._style_glass_clean_btn(False)
        self._btn_glass_clean.clicked.connect(self._on_glass_clean_clicked)

        # ⚠️ 2026-10-09 需求：「玻璃清洁」左侧新增「模拟生产」按钮。
        # 点击弹出模拟生产设置窗口（开关 + 各相机图片来源路径）。
        # 设备处于「生产运行中」时该按钮置灰不可点击，停止状态可点击。
        self._btn_simulate = QPushButton("模拟生产")
        self._btn_simulate.setFixedHeight(20)
        self._btn_simulate.setMinimumWidth(74)
        self._btn_simulate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_simulate.setToolTip("模拟生产设置（各相机图片来源路径）")
        self._btn_simulate.setFont(QFont("Microsoft YaHei", 9))
        self._style_simulate_btn()
        self._btn_simulate.clicked.connect(self._on_simulate_clicked)
        self._simulate_dlg = None
        status.set_header_actions([self._btn_simulate, self._btn_glass_clean])

        stats = FloatPanel("统计信息", self, min_w=410, min_h=440)
        stats.set_body_layout(self._build_stats())
        # 饼图/详情 切换按钮放到卡片标题栏右侧（两种统计方式切换按钮已移到底部操作行）
        stats.set_header_actions([self._btn_pie, self._btn_detail])

        log = FloatPanel("运行日志", self, min_w=360, min_h=200)
        log.set_body_layout(self._build_log())
        # 运行日志：把 日志详情/冻结/清除/导出 按钮移到面板标题栏右侧（腾出原「可拖拽/缩放」字眼位置，
        # 并避免与面板标题重复）。从右往左依次为 冻结 → 清除 → 导出 → 日志详情（冻结在最右，
        # 「日志详情」放在「导出」左侧，与生产运行界面、调试界面统一：日志详情 紧邻且在 导出 左侧）。
        # 「日志详情」：打开与生产运行界面左侧导航「日志管理」一致的日志窗口。
        self._btn_log_detail = QPushButton("日志详情")
        self._btn_log_detail.setFixedHeight(22)
        self._btn_log_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_log_detail.setStyleSheet(LogView._log_btn_style())
        self._btn_log_detail.setToolTip("查看完整运行日志（与「日志管理」窗口一致）")
        self._btn_log_detail.clicked.connect(self._open_log_manager)
        self._dlg_log_detail = None
        log.set_header_actions([
            self._btn_log_detail,
            self._log_view._export_btn,
            self._log_view._clear_btn,
            self._log_view._freeze_btn,
        ])

        self.panels = [cam, info, status, stats, log]
        register_restyle(self._restyle)

    def _restyle(self):
        """主题切换：重绘设备运行状态各行 + 生产统计面板的操作按钮与速度指标。

        各子组件（KPI 网格、环形图、相机/缺陷统计视图、浮动面板框架）已各自注册
        _restyle，此处仅处理生产运行界面直接持有的内联样式。
        """
        self._apply_status_style()
        for name, btn in self.stat_mode_buttons.items():
            self._style_mode_button(btn, name == self.stat_mode)
        if getattr(self, "_clear_btn", None) is not None:
            self._style_clear_button(self._clear_btn, self._cleared)
        if getattr(self, "_config_btn", None) is not None:
            self._config_btn.setStyleSheet(_BLUE_BTN_STYLE)
        self.s1.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        self.s2.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")

    # ------------------------------------------------------------------
    # 默认布局（按 1920*1080 设计，show 时按实际画布尺寸计算）
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._laid:
            self._apply_default_layout()
            self._laid = True

    def _apply_default_layout(self):
        W, H = self.width(), self.height()
        gap = 16   # 模块之间的可见间隙（设备信息/运行状态、统计/日志均保留，纵向清晰分隔）
        # 相机面板整高，宽度由 2 列 4:3 相机 + 间隙决定
        rows, cols = CameraGrid.ROWS, CameraGrid.COLS
        cam_gap = CameraGrid.GAP
        body_h = H - 2 * FloatPanel.MARGIN        # 相机面板已无标题栏：body 占满 MARGIN..H-MARGIN
        camH = (body_h - (rows - 1) * cam_gap) / rows
        camW = camH * 4 / 3
        cam_w = int(2 * camW + cam_gap) + 24       # 2 列 + 间隙 + 两侧留白
        self.panels[0].setGeometry(0, 0, cam_w, H)  # 相机监控（整高）

        rx = cam_w + gap
        rw = W - rx - gap
        col_w = (rw - gap) // 2
        # 设备状态面板有内容实需宽下限（_status_min_w，按两列最长名称/最宽单位实算）：
        # 状态行是「名称 + 百分比 + 数值 + 单位」四段并排，宽度不足时 Qt 会
        # 把差额压到名称框上，最长名称（如「RST 电磁阀」）被截断。
        # 窗口较窄时优先保证设备状态不截断（多出的宽度从右列扣），
        # 统计信息/运行日志是自适应内容，少一点宽度只是留白变窄，不会截字。
        #
        # ⚠️ 2026-10-08：下限必须取面板**实际 minimumWidth**（含名称框拉长余量
        # `_status_stretch_w`），不能只用 `_status_min_w`（纯内容实需宽）。
        # 否则按 `_status_min_w` 定位右列面板，而设备状态面板因 setMinimumWidth
        # 被 Qt 强制撑到更宽 → 右列面板被压到设备状态面板**之下**，两面板重叠
        # （实测 1300/1600/1920 三档窗口均重叠）。
        _st_min_w = max(getattr(self, "_status_min_w", 0),
                        self.panels[2].minimumWidth()
                        if len(self.panels) > 2 else 0)
        if col_w < _st_min_w:
            col_w = _st_min_w
            right_w = max(200, rw - gap - col_w)
        else:
            right_w = col_w

        # 右侧两列，均占满整高；列内上下两块保留可见间隙
        # 左列：设备信息（上） + 设备运行状态（下，保留间隙）
        # 设备信息面板高度按「body 实际内容」计算（标题栏 30 + 底边距 6），
        # 避免预留过大留白；与下方设备运行状态之间保留 gap 纵向间隙
        _info_body_lay = self.panels[1].body.layout()
        _info_content = _info_body_lay.sizeHint().height() if _info_body_lay else 0
        info_h = max(200, _info_content + 36)
        self.panels[1].setGeometry(rx, 0, col_w, info_h)
        self.panels[2].setGeometry(rx, info_h + gap, col_w, H - info_h - gap)
        # 右列：生产统计与检测结果（上） + 运行日志（下，保留间隙）
        # 比例从 0.60 提到 0.68：按缺陷项统计饼图页含 13 行汇总表，需要更大纵向空间
        # 才能避免表格被压到看不到
        stats_h = int(H * 0.68)
        self.panels[3].setGeometry(rx + col_w + gap, 0, right_w, stats_h)
        self.panels[4].setGeometry(rx + col_w + gap, stats_h + gap, right_w,
                                   H - stats_h - gap)
        self.cam_grid.relayout()
        # 显式重排每个浮动面板的内部 body，确保内容区域随面板尺寸同步更新
        # （避免 setGeometry 后 body 仍停留在初始/min 尺寸的旧几何，导致内容被裁切或留白）
        for p in self.panels:
            if hasattr(p, "_layout_internal"):
                p._layout_internal()

    def resizeEvent(self, event):
        """窗口尺寸变化（如最大化/全屏）时，五大模块重新铺满可用区域，避免底部面板被裁切或留白。"""
        super().resizeEvent(event)
        if getattr(self, "_laid", False) and self.width() > 0 and self.height() > 0:
            self._apply_default_layout()
            # 面板尺寸变了 → 刷新名称框下限/自检记录（保持「同列严格等宽对齐」）
            self._stretch_status_name_boxes()

    def _stretch_status_name_boxes(self):
        """设备状态名称框「按内容最多的矩形框长度对齐」的**收尾 + 自检记录**（只读）。

        需求（2026-10-08）：名称框**按内容最多的矩形框长度**对齐，
        同一列内所有行的名称框宽度完全一致（边框齐平）。
        ⚠️ 2026-10-09 补充：用户要求**卡片整体宽度不改变**，故不再叠加人为富余
        （`_status_stretch_w` 复原为 0）—— 只保留「同列严格等宽」的对齐效果。

        实现要点（三者缺一不可，全部在 `_build_device_status` 里一次性落地）：
          ① 名称框 `SizePolicy.Expanding` + `setMinimumWidth(本列最长文案宽)`
             —— Expanding 且是行内**唯一**弹性项 → 吃掉全部剩余宽度；
          ② 行内**不加** `addStretch()` —— 否则富余被平分，名称框右边出现空隙；
          ③ **尾部组同列严格等宽**（百分比占位恒 46px + 单位框取该列最长单位宽度，
             无单位的行也建等宽透明占位框）—— 这是「同列各行宽度一致」的**根本前提**。
             若各行尾部宽度不同（早期版本：无百分比设 0 宽、单位按行自适应），
             各行剩余空间不等，Expanding 名称框宽度必然参差（实测左列 92/166、
             右列 142/166/190/202）。
          由于 `_status_min_w` 的列最小宽本就按**各列最长名称**实算，且容器宽
          恰好等于两列最小宽之和，所以每列名称框宽度**正好 = 该列最长内容宽度**，
          同列各行严格等宽、且整体宽度不受任何人为影响。

        ⚠️ 本方法**只读不写布局**（除名称框下限外不做任何 setColumnMinimumWidth）：
        它会在 `resizeEvent` 里被调用，若在这里抬高列最小宽，会形成
        「改列最小宽 → 触发重排/resize → 再改列最小宽」的无限递归，
        离屏下直接段错误（实测 pv.show() + processEvents() 崩溃、退出码 127）。
        列最小宽在 `_build_device_status` 里已按同一公式一次算清，无需在此重复写。
        """
        recs = getattr(self, "_status_grid_recs", None)
        need = getattr(self, "_col_need_w", None)
        if not recs or not need:
            return
        grid = recs[0]["frame"].parentWidget()
        if grid is None or grid.width() <= 0:
            return
        # 各列内容实需宽 = 名称框 + 百分比 + 数值 + 单位 + 边距/间距
        col_need = {}
        for c in (0, 1):
            rs = [r for r in recs if r["grid_col"] == c]
            if not rs:
                return
            uw = max([r["unit"].width() for r in rs
                      if r["unit"] is not None] or [0])
            # 12=行内边距 12=dot 24=四个间距 46/46=百分比/数值
            col_need[c] = 12 + 12 + need[c] + 46 + 46 + uw + 24
        # 名称框下限恒为本列最长文案宽（保证文案完整、不截断）；
        # 实际宽度由 Expanding 吸收富余决定 —— 同列尾部组等宽故各行必然相同。
        for c in (0, 1):
            for r in [x for x in recs if x["grid_col"] == c]:
                r["nm"].setMinimumWidth(need[c])
        # 记录富余（仅用于冒烟断言 / 调试观察，不再回写宽度）
        spare = grid.width() - (sum(col_need.values()) + 10)   # +10 列间距
        self._name_box_extra = (
            {c: max(0, int(spare * need[c] / (sum(need.values()) or 1)))
             for c in (0, 1)} if spare > 0 else {0: 0, 1: 0})

    # ------------------------------------------------------------------
    # 相机监控（2 列 × 4 行，填满面板高度）
    # ------------------------------------------------------------------
    def _build_cameras(self):
        return self.cam_grid

    # ------------------------------------------------------------------
    # 设备信息：每行独立，料号/批号带扫码录入按钮
    # ------------------------------------------------------------------
    def _build_device_info(self):
        lay = QVBoxLayout()
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 设备编码（独立一行，可被用户中心的「设备编码设置」回写更新）
        row = QHBoxLayout()
        row.setSpacing(8)
        lab = QLabel("设备编码")
        lab.setFixedWidth(64)
        lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.device_code_edit = QLineEdit("ZG-CRL-001")
        self.device_code_edit.setMinimumHeight(30)
        self.device_code_edit.setReadOnly(True)
        row.addWidget(lab)
        row.addWidget(self.device_code_edit, 1)
        # 设备详细信息：右侧圆形图标按钮（信息图标 i，白色笔画绘制，无字体依赖），悬停提示、点击弹窗
        info_btn = QPushButton()
        info_btn.setFixedSize(24, 24)
        info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        info_btn.setToolTip("设备详细信息")
        info_btn.setIcon(_make_info_icon(18))
        info_btn.setIconSize(QSize(18, 18))
        info_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 12px; }}"
            f"QPushButton:hover {{ background-color: #5A78FF; }}")
        info_btn.clicked.connect(self._open_device_detail)
        self.device_detail_btn = info_btn
        row.addWidget(info_btn)
        lay.addLayout(row)

        # 负责人（独立一行）
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        lab2 = QLabel("负责人")
        lab2.setFixedWidth(64)
        lab2.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.owner_edit = QLineEdit("")
        self.owner_edit.setMinimumHeight(30)
        self.owner_edit.setPlaceholderText("请输入...")
        row2.addWidget(lab2)
        row2.addWidget(self.owner_edit, 1)
        lay.addLayout(row2)

        # 料号 + 批号（左侧两行，右侧一个贯穿两行高度的扫码录入按钮）
        codes = QHBoxLayout()
        codes.setSpacing(8)
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        pn = QHBoxLayout()
        pn.setSpacing(8)
        pn_lab = QLabel("料号")
        pn_lab.setFixedWidth(64)
        pn_lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.pn_edit = QLineEdit("")
        self.pn_edit.setMinimumHeight(28)
        self.pn_edit.setPlaceholderText("请输入...")
        pn.addWidget(pn_lab)
        pn.addWidget(self.pn_edit, 1)
        lot = QHBoxLayout()
        lot.setSpacing(8)
        lot_lab = QLabel("批号")
        lot_lab.setFixedWidth(64)
        lot_lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.lot_edit = QLineEdit("")
        self.lot_edit.setMinimumHeight(28)
        self.lot_edit.setPlaceholderText("请输入...")
        lot.addWidget(lot_lab)
        lot.addWidget(self.lot_edit, 1)
        left_col.addLayout(pn)
        left_col.addLayout(lot)
        codes.addLayout(left_col)
        scan = QPushButton("扫码\n录入")
        scan.setFixedHeight(64)
        scan.setStyleSheet(
            f"background-color: {COLORS['accent_orange']}; color: white; "
            f"border-radius: 4px; font-size: 12px;")
        scan.clicked.connect(self.open_scan_both)
        self.scan_btn = scan
        codes.addWidget(scan)
        lay.addLayout(codes)

        # 定量生产：开关按钮 + 文字说明
        opt = QHBoxLayout()
        opt.setSpacing(8)
        self.quant_toggle = StateToggle("定量生产")
        opt.addWidget(self.quant_toggle)
        opt.addStretch()
        opt.addWidget(QLabel("良品产量设定"))
        opt.itemAt(opt.count() - 1).widget().setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.qty_edit = QLineEdit()
        self.qty_edit.setMinimumHeight(30)
        self.qty_edit.setPlaceholderText("请输入...")
        opt.addWidget(self.qty_edit, 1)
        # 操作记录：切换定量生产开关 / 设定生产数量均写入运行日志
        self.quant_toggle.sw.toggled.connect(
            lambda on: (self.log_operation(
                getattr(self, "_op_user", "操作员"),
                "开启了定量生产" if on else "关闭了定量生产"),
                self._update_achieve()))
        self.qty_edit.editingFinished.connect(self._on_qty_edited)
        lay.addLayout(opt)
        lay.addStretch()
        return lay

    def _on_qty_edited(self):
        """生产数量输入完成：记录一次参数变更（仅在有有效值时写日志）。"""
        q = self.quant_target_value()
        if q is not None:
            self.log_operation(getattr(self, "_op_user", "操作员"),
                               f"设置了定量生产目标为 {q} 件")
        self._update_achieve()

    def quantitative_enabled(self):
        """是否开启了定量生产（开关处于「开启」状态）。"""
        return bool(getattr(self, "quant_toggle", None) and self.quant_toggle.is_on())

    def quant_target_value(self):
        """返回定量生产的目标数量（正整数）；未填或非正整数返回 None。"""
        if not getattr(self, "qty_edit", None):
            return None
        txt = self.qty_edit.text().strip()
        if not txt:
            return None
        try:
            v = int(txt)
        except ValueError:
            return None
        return v if v > 0 else None

    def _update_achieve(self):
        """生产信息面板标题栏：定量生产开启并设定良品产量后，显示「已达成设定产量的 X%」。

        比例按实际良品数（self._live_good 实时累计）计算；未开启定量生产或未设定产量则不显示。
        """
        lbl = getattr(self, "_achieve_label", None)
        if lbl is None:
            return
        if not self.quantitative_enabled():
            lbl.setVisible(False)
            return
        target = self.quant_target_value()
        if not target or target <= 0:
            lbl.setVisible(False)
            return
        good = int(round(getattr(self, "_live_good", 0.0)))
        pct = min(good / target * 100.0, 100.0)
        lbl.setText(f"已达成设定产量的 {pct:.2f}%")
        lbl.setVisible(True)

    def set_device_code(self, values):
        """回写设备编码（来自用户中心「设备编码设置」）。"""
        if getattr(self, "device_code_edit", None) is not None and values:
            self.device_code_edit.setText(str(values.get("设备编码", "")))

    def _open_device_detail(self):
        """点击「设备编码」右侧圆形「i」按钮：弹出设备详细信息窗口。"""
        dlg = DeviceDetailDialog(self, self.user_manager)
        dlg.exec()

    def open_scan_both(self):
        """扫码录入：料号与批号共用一个按钮，弹出对话框一次性填入两项。

        入口先走空闲确认（高级设置「密码输入确认时间周期」）：登录用户超时未操作软件时，
        会先弹窗要求重新输入密码，通过后才继续录入。
        """
        confirm = getattr(self, "idle_confirm_cb", None)
        if callable(confirm) and not confirm("扫码录入"):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("料号 / 批号 扫码录入")
        dlg.setFixedSize(400, 220)
        dlg.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_panel']}; }}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        v.addWidget(QLabel("请将条码对准扫码枪，或手动输入："))

        pn_row = QHBoxLayout()
        pn_row.addWidget(QLabel("料号"))
        pn_le = QLineEdit("PN" + "".join(random.choices("0123456789ABCDEF", k=8)))
        pn_row.addWidget(pn_le, 1)
        v.addLayout(pn_row)

        lot_row = QHBoxLayout()
        lot_row.addWidget(QLabel("批号"))
        lot_le = QLineEdit("LOT" + "".join(random.choices("0123456789ABCDEF", k=8)))
        lot_row.addWidget(lot_le, 1)
        v.addLayout(lot_row)

        btns = QHBoxLayout()
        ok = QPushButton("确认录入")
        ok.setStyleSheet(
            f"background-color: {COLORS['accent_green']}; color: white; "
            f"border-radius: 4px; padding: 6px 16px;")
        cancel = QPushButton("取消")
        cancel.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; color: white; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 6px 16px;")
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(ok)
        v.addLayout(btns)
        ok.clicked.connect(lambda: (self.pn_edit.setText(pn_le.text()),
                                   self.lot_edit.setText(lot_le.text()),
                                   self.log_operation(getattr(self, "_op_user", "操作员"),
                                                     "扫码录入了料号/批号"),
                                   dlg.accept()))
        cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def set_scan_locked(self, locked: bool):
        """设备运行中锁定料号/批号录入：输入框转为只读、扫码录入按钮禁用，防止运行中误改产品/批号。

        - locked=True  （设备启动后）：输入框只读不可输入、扫码录入按钮置灰禁用
        - locked=False （设备停止后）：恢复可输入、扫码录入按钮可用
        """
        btn = getattr(self, "scan_btn", None)
        if btn is not None:
            btn.setEnabled(not locked)
        for le in (getattr(self, "pn_edit", None), getattr(self, "lot_edit", None)):
            if le is not None:
                le.setReadOnly(locked)
                if locked:
                    le.setStyleSheet(
                        f"background-color: {COLORS['bg_card']}; "
                        f"color: {COLORS['text_secondary']};")
                else:
                    le.setStyleSheet("")

    # ------------------------------------------------------------------
    # 设备运行状态：每行 = 状态灯 + 名称 + 百分比 + 数值
    # ------------------------------------------------------------------
    def _build_device_status(self):
        lay = QVBoxLayout()
        # 底部边距压到 1px：让分页行（前一页/页码/后一页）尽量贴近卡片底部
        lay.setContentsMargins(10, 8, 10, 1)
        lay.setSpacing(8)
        # 设备运行状态整体采用 2 列网格对齐：
        # ① 顶部：4 个料盒卡片横向排列（卡片自带边界，无需小标题）；
        # ② 下方：电磁阀 / 实时测量 / 误踢漏踢 / 设备门 / 急停 / 视觉控制器 统一汇入 2 列网格，
        #    名称列与数值组（百分比框 + 数值框 + 单位）同宽对齐，字体完整显示、纵向更紧凑。

        # ① 料盒：4 张卡片横向排列
        bin_row = QHBoxLayout()
        bin_row.setSpacing(8)

        # ② 2 列网格
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self._status_rows = []
        self._status_recs = {}          # 名称 -> 整行记录，供按名称实时更新
        self._bin_state_labels = {}     # 料盒名称 -> 取出状态 QLabel
        self._bin_value_labels = {}     # 料盒名称 -> 数值 QLabel
        self._bin_pct_labels = {}       # 料盒名称 -> 百分比 QLabel
        self._bin_time_labels = {}      # 料盒名称 -> 取出计时(ms) QLabel
        self._valve_value_labels = {}   # 电磁阀名称 -> 数值 QLabel
        self._valve_pct_labels = {}     # 电磁阀名称 -> 百分比 QLabel
        self._valve_used = {}           # 阀键 -> 已用动作次数（次），运行期间递增
        self._valve_used_init = {}      # 阀键 -> 初始已用（重置时恢复）
        self._bin_count = {}            # 阀键 -> 料盒累计件数，运行期间按 BIN_RATE 递增
        self._bin_count_init = {}       # 阀键 -> 初始累计件数（重置时恢复）
        # 料盒取出状态：False=未取出（绿底），True=取出（红底）；示例默认均为「未取出」
        self._bin_taken = {k: False for k in BIN_KEYS}
        # 料盒满料状态：True=已满料（100%）应显示红底「满料，请取料」；取走/清零后解除
        self._bin_full = {k: False for k in BIN_KEYS}

        # 实时测量行（总气源/旋转盘/静电/负压）+ 设备门 / 误踢漏踢 / 急停 / 视觉控制器：
        # 均不写百分比，运行期间示例值波动、越界则状态灯变红并报警。
        no_pct_rows = {"总气源", "旋转盘", "静电", "负压", "设备门",
                       "OK料仓误踢频率", "OK料仓漏踢频率", "急停按钮", "视觉控制器",
                       "飞料频率", "玻璃盘上下跳动", "相机状态"}
        # 实时测量 + 设备门：门打开报警时状态灯随 live_color 变红
        live_rows = no_pct_rows | {"设备门"}

        _fm = QFontMetrics(QFont("Microsoft YaHei", 9))

        # ---- ① 料盒 4 卡（横向排列，去掉原标题） ----
        bin_items = [
            ("OK 料盒", "10000 件"),
            ("NG1 料盒", "280 件"),
            ("NG2 料盒", "120 件"),
            ("RST 料盒", "100 件"),
        ]
        _bin_name_w = max(_fm.horizontalAdvance(n) for n, _ in bin_items) + 8
        for name, val in bin_items:
            num, unit = val.split(" ", 1)
            key = name.split()[0]
            cnt = int(num)
            self._bin_count[key] = cnt
            self._bin_count_init[key] = cnt
            thr = bin_full_threshold(key)
            pct = min(100.0, cnt / thr * 100) if thr else 0.0
            col = self._status_color(int(round(pct)))
            pct_str = f"{pct:.2f}%"
            pct_val = int(round(pct))
            dot = QLabel("●")
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nm = QLabel(name)
            nm.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
            nm.setFixedWidth(_bin_name_w)
            card = QFrame()
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(5, 4, 5, 4)
            cv.setSpacing(3)
            hn = QHBoxLayout()
            hn.setSpacing(4)
            hn.addWidget(dot)
            hn.addWidget(nm)
            hn.addStretch()
            cv.addLayout(hn)
            val_box = QLabel(num)
            val_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cv.addWidget(val_box)
            pct_box = QLabel(pct_str)
            pct_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cv.addWidget(pct_box)
            # 取出计时标签（s，保留 2 位小数）：料盒变为取出态后实时刷新已取出时长；未取出时为空。
            # 与「取出/未取出」状态窗体同一行（状态窗体右侧），右对齐保证时间与单位 s 完整显示
            time_lbl = QLabel("")
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 8px; "
                # 显式去边框/去底色：卡片 QFrame 边框规则会下传给 QLabel（QLabel 为 QFrame 子类）
                f"border: none; background-color: transparent;")
            time_lbl.setVisible(False)   # 空计时隐藏，避免右侧出现空窗体
            state_lbl = QLabel(BIN_STATE_TEXT[False])
            # 状态窗体宽度收窄：按「未取出」三字自适应 +8px 边距，给右侧计时留出空间
            state_lbl.setFixedWidth(_fm.horizontalAdvance("未取出") + 8)
            state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            foot = QHBoxLayout()
            foot.setContentsMargins(0, 0, 0, 0)
            foot.setSpacing(2)
            foot.addWidget(state_lbl)
            foot.addStretch(1)
            foot.addWidget(time_lbl)
            cv.addLayout(foot)
            rec = {
                "name": name, "frame": card, "dot": dot, "nm": nm,
                "pct_box": pct_box, "val_box": val_box, "unit": None,
                "pct": pct_str, "color": col, "num": num,
                "no_pct": False, "pct_val": pct_val, "state_lbl": state_lbl,
                "time_lbl": time_lbl, "taken_timeout": False,
            }
            self._status_rows.append(rec)
            self._status_recs[name] = rec
            if name in live_rows:
                rec["live"] = True
            self._bin_value_labels[name] = val_box
            self._bin_pct_labels[name] = pct_box
            self._bin_state_labels[name] = state_lbl
            self._bin_time_labels[name] = time_lbl
            bin_row.addWidget(card)
            bin_row.setStretch(bin_row.count() - 1, 1)   # 4 卡等宽
            self._apply_status_style()

        # ---- ② 2 列网格状态行（行优先：左列、右列交替填入） ----
        grid_items = [
            ("OK 电磁阀", "3200 次"),
            ("总气源", "0.62 MPa"),
            ("NG1 电磁阀", "120 次"),
            ("旋转盘", "15.0 RPM"),
            ("NG2 电磁阀", "45 次"),
            ("静电", "2.8 KV"),
            ("RST 电磁阀", "8 次"),
            ("负压", "0.10 MPa"),
            ("急停按钮", "未开启"),
            ("OK料仓漏踢频率", "8 Pcs/H"),
            ("设备门", "已关闭"),
            ("OK料仓误踢频率", "12 Pcs/H"),
            ("视觉控制器", "在线"),
            ("飞料频率", f"{random.randint(1, 10)} Pcs/min"),
            # 左列「视觉控制器」正下方：相机状态（在线/掉线，示例保持在线）；
            # 右列「飞料频率」正下方：玻璃盘上下跳动
            ("相机状态", "在线"),
            ("玻璃盘上下跳动", f"{self._draw_glass_jump_val():.2f} mm"),
        ]
        # 名称列宽度：按各列内最长名称自适应 +6px 安全边距。
        # 左列最长名称为阀门名（NG1/NG2 电磁阀），右列为料仓频率名；
        # 同列名称同宽→ 该列百分比框/数值框严格同竖列对齐，且百分比框不压住名称。
        _col0_names = [n for i, (n, _) in enumerate(grid_items) if i % 2 == 0]
        _col1_names = [n for i, (n, _) in enumerate(grid_items) if i % 2 == 1]
        # ── 单位框宽度：按**各列最长单位的实需宽度**（+4 内边距）计算 ──
        # ⚠️ 2026-10-09 用户需求「篮框（数值框）整体右移、紧挨右侧的『次』，
        # 其左侧百分比列也相应右移」：
        # 旧口径 `max(24, advance+8)` 给 col0 的「次」（advance 仅 12px）留了
        # 24px 宽的框 → 数值框与「次」之间出现 ~12px 死间隙（视觉上没挨着）。
        # 现在单位框按内容实需收窄（+4），数值框与单位自然贴合。
        #
        # ⚠️ 收窄出来的宽度**必须补给名称框下限**，否则两列合计会变窄、
        # 卡片整体宽度被改小（用户明确要求「设备状态卡片的整体宽度不要改变」）。
        # 补给后每列总宽不变 → 面板 min_w 仍是 610px，而名称框吃掉这份富余，
        # 于是 pct/val/unit 三个控件**整体右移**到「次」左侧，二者紧挨。
        _UNIT_PAD = 4
        _UNIT_W_OLD_MIN = 24
        _UNIT_W_OLD_PAD = 8
        _col_unit_w = {}
        _col_unit_old_w = {}
        for _c in (0, 1):
            _advs = [_fm.horizontalAdvance(_v.split(" ", 1)[1]) + _UNIT_PAD
                     for _i, (_n, _v) in enumerate(grid_items)
                     if _i % 2 == _c and " " in _v]
            _col_unit_w[_c] = max(_advs) if _advs else 0
            _old = [_UNIT_W_OLD_MIN] + [
                _fm.horizontalAdvance(_v.split(" ", 1)[1]) + _UNIT_W_OLD_PAD
                for _i, (_n, _v) in enumerate(grid_items)
                if _i % 2 == _c and " " in _v]
            _col_unit_old_w[_c] = max(_old)
        # 名称框下限 = 最长文案宽 + 6 + 「单位框让出的宽度」
        _name_w_col0 = (max(_fm.horizontalAdvance(n) for n in _col0_names) + 6
                        + (_col_unit_old_w[0] - _col_unit_w[0]))
        _name_w_col1 = (max(_fm.horizontalAdvance(n) for n in _col1_names) + 6
                        + (_col_unit_old_w[1] - _col_unit_w[1]))
        grid_recs = []
        for i, (name, val) in enumerate(grid_items):
            if " " in val:
                num, unit = val.split(" ", 1)
            else:
                num, unit = val, ""
            key = name.split()[0]
            no_pct = name in no_pct_rows

            if no_pct:
                pct = None
            elif name.endswith("电磁阀"):
                # 电磁阀百分比 = 已用动作次数 / 寿命阈值（运行期间递增）
                used = float(num)
                self._valve_used[key] = used
                self._valve_used_init[key] = used
                thr = valve_life_threshold(key)
                pct = min(100.0, used / thr * 100) if thr else 0.0
            else:
                pct = 0.0

            if no_pct:
                pct_str = "—"                    # 占位，不写百分比
                col = COLORS["text_secondary"]
            else:
                col = self._status_color(int(round(pct)))
                pct_str = f"{pct:.2f}%"
            pct_val = None if no_pct else int(round(pct))
            is_door = (name == "设备门")
            dot = QLabel("●")
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nm = QLabel(name)
            # 名称框吃掉本行全部剩余横向空间（Expanding）：尾部组（百分比框 + 数值框 + 单位）
            # 因此被推到行的最右侧，与行右边缘对齐。
            # 这样同时满足两个需求：
            #   ① 「百分比框/数值框」右移到与蓝色竖线（单位起始竖线）对齐；
            #   ② 「名称框」边框加长，从状态灯一直延伸到数值组左侧（橙色箭头所指位置）。
            nm.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            # ⚠️ min 宽必须是**本列最长文案宽**（不能再打 55% 折中）：
            # 打折后网格列最小宽会小于实际所需，QGridLayout 在列宽不足时
            # 把差额全部压到名称框上，导致「RST 电磁阀」这类最长名称被截断
            # （实测压到 74px < 文案 84px）。
            # 现在把「宽度不足」的问题交给上层解决：内容容器声明最小宽 +
            # 面板 min_w 按内容实算，面板不会被拖到装不下内容。
            #
            # ⚠️ 2026-10-08 需求「按内容最多的矩形框长度整体拉长对齐」：
            # 名称框 Expanding 会吃掉行内全部剩余空间，而**同列各行尾部组宽度
            # 不同**（有/无百分比占位 0 vs 46、有/无单位框、单位宽度按行自适应），
            # 导致各行剩余空间不等 → 名称框宽度参差（实测 92/166、142/166/190/202）。
            # 修复关键：**同列各行尾部组严格等宽**（见 _col_unit_w 与下方百分比占位），
            # 剩余空间相同 → Expanding 名称框宽度自然严格一致（同列齐平）；
            # 又因为它吃掉全部剩余，面板富余全被名称框吸收 → 边框真正「拉长」。
            # ⚠️ 这里必须用 setMinimumWidth 而非 setFixedWidth：
            # QGridLayout 在列宽有余量时会**重置 FixedWidth**（实测设 156 被拉回 92），
            # 而 MinimumWidth 只抬下限、允许多余空间进来，Expanding 才能吸收富余。
            _nw_col = _name_w_col0 if i % 2 == 0 else _name_w_col1
            nm.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
            nm.setMinimumWidth(_nw_col)
            row = QFrame()
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 3, 6, 3)
            h.setSpacing(6)
            pct_box = QLabel(pct_str)
            # 百分比框 / 数值框宽度**固定不可压缩**（Fixed 策略）：
            # 它们是数据主体，被压成0 宽整列数值就消失了。
            # 面板变窄时由名称框（Expanding）吸收全部压缩量。
            pct_box.setFixedWidth(46)
            pct_box.setMinimumWidth(46)
            pct_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            pct_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if no_pct:
                # 无百分比项：文案留空、底色透明（看不出占位），但**仍占满 46px**。
                # ⚠️ 不能设成 0 宽 —— 那会让本行比同列其他行多出 46px 剩余空间，
                # 被 Expanding 名称框吃掉 → 同列名称框宽度参差（实测 92 vs 166）。
                # 保持 46px 后，同列各行尾部组等宽，名称框右缘才能严格齐平。
                pct_box.setText("")
                pct_box.setStyleSheet(
                    "background: transparent; border: none;")
            val_box = QLabel(num)
            val_box.setFixedWidth(46)
            val_box.setMinimumWidth(46)
            val_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            val_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unit_lbl = None
            h.addWidget(dot)
            # ⚠️ 这里**不加** addStretch()：名称框是 Expanding 且行内只有它一个弹性项，
            # 由它吃掉全部富余宽度（这正是「整体拉长」的来源）。
            # 若行内再加 stretch，富余会被 stretch 与名称框平分，
            # 名称框右边又会出现空隙，且名称框实际拿不到预期宽度。
            h.addWidget(nm)
            h.addWidget(pct_box)
            h.addWidget(val_box)
            # ⚠️ 单位框**每行都建**（无单位时留空+透明），且宽度取**本列最长单位**
            # （`_col_unit_w`）而非本行自适应 —— 这是同列名称框严格等宽的前提：
            # 若无单位的行不建框 / 各行宽度不同，各行剩余空间不等，名称框就参差。
            unit_lbl = QLabel(unit)
            _uw = _col_unit_w[i % 2]
            unit_lbl.setFixedWidth(_uw)
            if not unit:
                # 无单位：留空占位、透明无边框（视觉上不存在，但保留等宽占位）
                unit_lbl.setStyleSheet(
                    "background: transparent; border: none;")
                unit_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignVCenter)
            elif name.endswith("电磁阀"):
                # ⚠️ 2026-10-09：改为**左对齐**（真正紧贴数值框右缘）。
                # 旧代码这里用 AlignRight，本意是「贴近数值框」，但单位框在数值框
                # **右侧**，右对齐反而把「次」推到框的最右端、中间空出 ~12px
                # 死间隙（用户截图里数值框与「次」没挨着）。左对齐才是真紧挨。
                unit_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignVCenter)
            else:
                unit_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(unit_lbl)
            rec = {
                "name": name, "frame": row, "dot": dot, "nm": nm,
                "pct_box": pct_box, "val_box": val_box, "unit": unit_lbl,
                "pct": pct_str, "color": col, "num": num,
                "no_pct": no_pct, "pct_val": pct_val, "state_lbl": None,
            }
            self._status_rows.append(rec)
            self._status_recs[name] = rec
            grid_recs.append(rec)
            if name in live_rows:
                rec["live"] = True
            if name.endswith("电磁阀"):
                self._valve_value_labels[name] = val_box
                self._valve_pct_labels[name] = pct_box
            if name == "视觉控制器":
                # 视觉控制器：在线/离线状态行（绿/红），默认在线；右键可模拟离线/恢复
                rec["is_vision"] = True
                rec["online"] = True
                rec["val_box"].setText("在线")
                rec["frame"].setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu)
                rec["frame"].customContextMenuRequested.connect(
                    self._vision_context_menu)
            self._apply_status_style()

            r, c = divmod(i, 2)
            rec["grid_row"] = r
            rec["grid_col"] = c
            grid.addWidget(row, r, c)

        # 列最小宽 =「统一名称框宽 + 百分比(46) + 数值(46) + 单位 + 边距/间距」，
        # 保证面板被拖窄时 Qt 压缩**名称框**而不是压扁数值框
        # （百分比/数值框是 Fixed，被压成 0 宽整列数据就消失了）。
        # ⚠️ 2026-10-08：尾部组已统一为「百分比46 + 数值46 + 单位(列统一宽)」，
        # 行内控件数由 3 项变 4 项 → 间距由 3 个变 4 个（18 → 24）。
        # 12=行内边距(6+6)  12=dot  6*4=四个间距  46/46=百分比框/数值框
        _status_min_w = 0
        for _c, _nw in ((0, _name_w_col0), (1, _name_w_col1)):
            _uw_max = _col_unit_w[_c]
            _col_min = 12 + 12 + _nw + 46 + 46 + int(_uw_max) + 24
            grid.setColumnMinimumWidth(_c, _col_min)
            _status_min_w += _col_min
        # 两列合计 + 列间距 10 + 面板 body 左右内缩 2*MARGIN
        _status_min_w = int(_status_min_w + 10 + 2 * FloatPanel.MARGIN)
        # 面板 min_w 不得小于内容实需宽：否则面板被拖窄时名称文字被截断
        self._status_min_w = _status_min_w
        # 名称框「拉长余量」：**保持 0 —— 设备状态卡片的整体宽度不改变**。
        # ⚠️ 2026-10-09 用户需求「设备状态卡片的整体宽度不要改变，给我复原」：
        # 上一轮为实现「拉长」加了 132px 人为富余，导致面板 min_w 被撑到
        # 742px（实测 1920 窗口下 col_w 自然值更小，Qt 强制把面板撑宽、
        # 挤占右列空间）—— 这属于未经用户要求的宽度变更，现已复原。
        #
        # 复原后仍然成立的是「按内容最多的矩形框长度对齐」：
        # `_status_min_w` 的列最小宽本身就是按**该列最长名称**实算的，
        # 且内容容器宽 = _status_min_w - 2*MARGIN 恰好等于两列最小宽之和，
        # 因此每列名称框宽度**正好等于该列最长内容宽度**，同列各行严格等宽、
        # 右缘齐平（对齐效果不变，只是不再向外拉长）。
        self._status_stretch_w = 0
        # 记录两列的内容实需宽（不含富余），供调试/冒烟断言核对
        self._col_need_w = {0: _name_w_col0, 1: _name_w_col1}
        self._name_box_extra = {}

        # 布局稳定后触发一次重排（此时 grid 已有实际宽度，名称框已完成拉长）
        QTimer.singleShot(0, self._stretch_status_name_boxes)

        # ---- ③ 底部分页：前一页 / 当前页序号 / 后一页 ----
        # 第 1 页 = 设备状态（料盒 4 卡 + 16 项状态行）；
        # 第 2 页 = 光源状态（光源1~光源18 共18 路，每路在「频闪中 / 未频闪」间来回切换）。
        # 两页内容各自独立：第 1 页内容容器固定挂在 _status_page1，第 2 页挂 _light_content。
        self._status_page = 0
        self._status_pages = 2
        self._status_grid_recs = list(grid_recs)

        # 状态内容容器（承载料盒行 + 2 列网格）—— 固定属于第 1 页
        self._status_content = QWidget()
        # Expanding：容器宽度必须跟随面板 body 一起拉伸。
        # 默认 Preferred 会让容器停在 minimumSizeHint（实测 518），
        # 面板加宽到 562 时容器仍不跟随，右侧留白且名称框拿不到多余弹性。
        self._status_content.setSizePolicy(QSizePolicy.Policy.Expanding,
                                           QSizePolicy.Policy.Expanding)
        # ⚠️ 2026-10-08「名称框整体拉长」的关键一环：容器必须**声明宽度下限**。
        # 否则容器的 sizeHint 只由 `bin_row`（料盒 4 卡，约 598px）决定，
        # 即使面板 body 更宽，容器仍停在 598 → 状态网格拿不到富余 →
        # Expanding 名称框吃不到剩余空间（实测 nm 恒为 90/102）。
        # 下限 = 两列内容实需宽 + 列间距 + 名称框拉长余量（`_status_stretch_w`，
        # 2026-09 起已复原为 0，卡片整体宽度不改变），
        # 即与面板 min_w 保持同宽，否则容器比面板窄，网格吃不到面板富余。
        _status_min_w = getattr(self, "_status_min_w", 0)
        # ⚠️ 宽度下限在函数末尾 `self._status_lay = lay` 之后**统一设置**
        # （两页容器一起设，必须扣掉 `_status_lay` 的左右边距 10+10）。
        _cl = QVBoxLayout(self._status_content)
        _cl.setContentsMargins(0, 0, 0, 0)
        _cl.setSpacing(8)
        _cl.addLayout(bin_row)
        _cl.addSpacing(4)
        _cl.addLayout(grid)

        # 第 2 页：光源状态（18 路，2 列网格）
        self._light_recs = []
        self._light_phase = 0
        self._light_content = self._build_light_status_page()

        # 第 1 页容器
        self._status_page1 = QWidget()
        _p1 = QVBoxLayout(self._status_page1)
        _p1.setContentsMargins(0, 0, 0, 0)
        _p1.setSpacing(0)
        _p1.addWidget(self._status_content)

        # 第 2 页容器
        self._status_page2 = QWidget()
        _p2 = QVBoxLayout(self._status_page2)
        _p2.setContentsMargins(0, 0, 0, 0)
        _p2.setSpacing(0)
        _p2.addWidget(self._light_content)

        # 光源状态切换定时器（示例效果：频闪中 / 未频闪 来回切换）
        _lt = getattr(self, "_light_timer", None)
        if _lt is not None:
            try:
                _lt.stop()
            except RuntimeError:
                pass
        self._light_timer = QTimer(self)
        self._light_timer.timeout.connect(self._tick_light_status)
        self._light_timer.start(1200)
        for _pg in (self._status_page1, self._status_page2):
            _pg.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Expanding)
        # ⚠️ 两页容器必须放进 **QStackedLayout**（分页容器），不能直接 addWidget。
        # 原因：直接 addWidget 时 QVBoxLayout 按两页 sizeHint **比例**分配宽度
        # （第 1 页 598 由料盒卡主导、第 2 页 286，合计 884 > body 可用 730），
        # 两页都拿不到富余、都不拉伸 → 面板加宽后内容右侧留白，
        # 状态网格吃不到宽度 → 名称框无法被「拉长」（实测 nm 恒为 90/102）。
        # 隐藏页即使 setVisible(False) 也仍参与 QVBoxLayout 的宽度分配计算，
        # 所以「隐藏」不等于「不占位」。QStackedLayout 只布局当前页，
        # 可见页必然独占整块 body 宽度。
        self._status_stack = QStackedLayout()
        self._status_stack.setContentsMargins(0, 0, 0, 0)
        self._status_stack.setSpacing(0)
        self._status_stack.addWidget(self._status_page1)
        self._status_stack.addWidget(self._status_page2)
        lay.addLayout(self._status_stack, 1)

        _pbtn_style = (
            # 分页行：按需求去掉「上一页 / 页码 / 后一页」的外围矩形框——
            # 常态与悬停都保持透明无边框（悬停仅用主题蓝文字 + 淡底提示可点），
            # 避免鼠标划过时又冒出矩形框。
            f"QPushButton {{ background-color: transparent; "
            f"color: {COLORS['text_secondary']}; border: none; "
            f"border-radius: 4px; padding: 1px 8px; font-size: 9px; "
            f"font-family: 'Microsoft YaHei'; }} "
            f"QPushButton:hover {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['accent_blue']}; }} "
            f"QPushButton:disabled {{ color: {COLORS['border']}; }}")
        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.setSpacing(6)
        self._btn_status_prev = QPushButton("前一页")
        self._btn_status_next = QPushButton("后一页")
        for _b in (self._btn_status_prev, self._btn_status_next):
            _b.setFixedHeight(18)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(_pbtn_style)
        self._btn_status_prev.clicked.connect(self._on_status_prev_page)
        self._btn_status_next.clicked.connect(self._on_status_next_page)
        self._status_page_lbl = QLabel(f"1/{self._status_pages}")
        self._status_page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 「1/N」比单字符页码宽，按实测文案宽度固定，避免被布局压缩后文字被裁
        _pglbl_w = QFontMetrics(QFont("Microsoft YaHei", 9)).horizontalAdvance(
            f"{self._status_pages}/{self._status_pages}") + 18
        self._status_page_lbl.setFixedWidth(max(34, _pglbl_w))
        # 页码同样去掉外围矩形框（透明底、无边框）
        self._status_page_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 9px; font-weight: bold; "
            f"font-family: 'Microsoft YaHei'; "
            f"background-color: transparent; border: none; padding: 1px 8px;")
        page_row.addWidget(self._btn_status_prev)
        page_row.addStretch(1)
        page_row.addWidget(self._status_page_lbl)
        page_row.addStretch(1)
        page_row.addWidget(self._btn_status_next)
        lay.addLayout(page_row)
        self._apply_status_page()
        # 布局交由调用方挂到面板 body（调用方需在构建后按 _status_min_w
        # 抬高面板 min_w，故此处只缓存不返回）
        self._status_lay = lay

        # ── 两页内容容器的宽度下限（统一在此设置，此时 lay 边距已知）──────────
        # ⚠️ 2026-10-09 修「第2 页显示不完整」：容器下限必须扣除
        # `_status_lay` 自身的左右边距（10+10=20px）。
        # 之前只扣 `2*MARGIN` → 声明 598，但 stack 真实可用宽仅
        # body(598) - 10 - 10 = 578 → 容器溢出 20px，第 2 页右列被裁掉。
        _smw = getattr(self, "_status_min_w", 0)
        if _smw > 0:
            _lay_lr = lay.contentsMargins().left() + lay.contentsMargins().right()
            _cw = int(_smw - 2 * FloatPanel.MARGIN - _lay_lr
                      + getattr(self, "_status_stretch_w", 0))
            self._status_content.setMinimumWidth(_cw)
            self._light_content.setMinimumWidth(_cw)
            self._page_content_w = _cw

    def _build_light_status_page(self):
        """构建设备状态卡片第 2 页：光源状态（光源1~光源18，共 18 路，2 列网格）。

        每路 = 状态灯+ 名称 + 状态文字（频闪中 / 未频闪），示例效果由
        `_tick_light_status` 定时来回切换（各路错相，翻转节奏更自然）。
        """
        LIGHT_COUNT = 18
        _fm = QFontMetrics(QFont("Microsoft YaHei", 9))
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)
        # ⚠️ 宽度下限**不在这里**设置：本方法由 `_build_device_status` 在
        # `self._status_lay` 赋值**之前**调用，此刻拿不到 `_status_lay` 的左右边距
        # （10+10=20px）。若按 `_status_min_w - 2*MARGIN` = 598 声明，会超出真实
        # 可用宽 578 → 第 2 页右列（光源10/12/14/16/18）被裁掉，显示不完整。
        # 统一在 `_build_device_status` 里 `self._status_lay = lay` 之后设置。

        title = QLabel("光源状态")
        title.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 9px; "
            f"font-family: 'Microsoft YaHei'; background-color: transparent; border: none;")
        vl.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        _name_w = _fm.horizontalAdvance("光源18") + 6
        _val_w = _fm.horizontalAdvance("未频闪") + 12
        for i in range(LIGHT_COUNT):
            name = f"光源{i + 1}"
            # 初始状态：按 3 路一组错相（每组 2 路频闪 + 1 路未频闪），
            # 首屏两类状态交错分布，避免整列整齐划一
            on = (i % 3 != 2)
            row = QFrame()
            row.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Preferred)
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 3, 6, 3)
            h.setSpacing(6)
            dot = QLabel("●")
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nm = QLabel(name)
            # 与第 1 页同口径：名称框 Expanding + MinimumWidth（不用 FixedWidth，
            # 否则 QGridLayout 会把固定宽重置、长度改不回去），
            # 吸收面板富余宽度实现「整体拉长」，同列各行仍完全一致、边框齐平。
            nm.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
            nm.setMinimumWidth(_name_w)
            val = QLabel("频闪中" if on else "未频闪")
            val.setFixedWidth(_val_w)
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.addWidget(dot)
            h.addWidget(nm)
            h.addWidget(val)
            rec = {"name": name, "frame": row, "dot": dot, "nm": nm,
                   "val_box": val, "on": on}
            self._light_recs.append(rec)
            r, c = divmod(i, 2)
            grid.addWidget(row, r, c)

        vl.addLayout(grid)
        vl.addStretch(1)
        # 光源页名称框也要「拉长」：行内尾部（dot12 + 状态文字 val_w）各行一致，
        # 名称框 Expanding 会自动吃满剩余宽度 → 同列各行天然齐平。
        # 列最小宽给内容下限保护，避免面板被拖窄时压缩状态文字。
        _light_col_min = 12 + 12 + _name_w + _val_w + 18   # 12边距 12dot 18间距
        grid.setColumnMinimumWidth(0, _light_col_min)
        grid.setColumnMinimumWidth(1, _light_col_min)
        self._apply_light_style()
        return page

    def _apply_light_style(self):
        """按当前主题重绘光源状态各行（行底色 / 状态灯 / 名称 / 状态文字）。

        频闪中 = 绿色（正在出光），未频闪 = 次级灰（未出光）。
        """
        for rec in getattr(self, "_light_recs", []):
            col = COLORS["accent_green"] if rec["on"] else COLORS["text_secondary"]
            # 与第 1 页一致：行容器不画最外围大框（仅底色）；
            # 名称标签保留小框、状态灯不加框、状态文字保留小框
            rec["frame"].setStyleSheet(
                f"QFrame {{ background-color: {COLORS['bg_card']}; border: none; }}")
            rec["dot"].setStyleSheet(
                f"color: {col}; font-size: 9px; "
                f"background-color: transparent; border: none;")
            rec["nm"].setStyleSheet(
                f"color: {COLORS['text_primary']}; font-size: 9px; "
                f"font-family: 'Microsoft YaHei'; "
                f"background-color: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px;")
            rec["val_box"].setText("频闪中" if rec["on"] else "未频闪")
            rec["val_box"].setStyleSheet(
                f"color: {col}; font-size: 9px; font-family: 'Microsoft YaHei'; "
                f"background-color: {COLORS['bg_panel']}; "
                f"border: 1px solid {COLORS['border']}; "
                f"border-radius: 3px; padding: 2px 6px;")

    def _tick_light_status(self):
        """光源状态示例切换：每路在「频闪中 / 未频闪」之间来回翻转。

        各路以 3 为步长错相（相位 = 序号 % 3），避免 18 路整齐划一地同时翻转；
        并在末尾做一次「混合态兜底」—— 若某一拍恰好让 18 路全部同态，
        则强制翻转其中一路，保证示例画面始终能同时看到「频闪中」与「未频闪」
        两类状态（否则长时间运行后可能整屏只剩一种状态，失去演示意义）。
        """
        recs = getattr(self, "_light_recs", None)
        if not recs:
            return
        phase = getattr(self, "_light_phase", 0) + 1
        self._light_phase = phase
        for i, rec in enumerate(recs):
            if (phase + i) % 3 == 0:
                rec["on"] = not rec["on"]
        # 混合态兜底：全同态时翻转第一路，避免整屏只有一种状态
        _ons = [r["on"] for r in recs]
        if all(_ons) or not any(_ons):
            recs[0]["on"] = not recs[0]["on"]
        self._apply_light_style()

    def _on_status_prev_page(self):
        """设备状态分页：上一页。"""
        if self._status_page > 0:
            self._status_page -= 1
            self._apply_status_page()

    def _on_status_next_page(self):
        """设备状态分页：下一页。"""
        if self._status_page < self._status_pages - 1:
            self._status_page += 1
            self._apply_status_page()

    def _apply_status_page(self):
        """按当前页码切换页面容器（第 1 页设备状态 / 第 2 页光源状态）。

        两页内容各自独立、互不搬移；页码与前后页按钮可用态同步刷新。
        ⚠️ 两页放在 `QStackedLayout` 里，必须用 `setCurrentIndex` 切页
        （不能只 setVisible —— 见 `_build_device_status` 中关于「隐藏≠不占位」的说明）。
        """
        on_page2 = self._status_page > 0
        _st = getattr(self, "_status_stack", None)
        if _st is not None:
            _st.setCurrentIndex(self._status_page)
        else:
            self._status_page1.setVisible(not on_page2)
            self._status_page2.setVisible(on_page2)
        # 切页后强制重排一次：QStackedLayout 换页后子页的 Expanding 名称框
        # 可能仍停留在上一页/构造期的旧宽度，需 activate 后才会按新页宽重算，
        # 否则光源页名称框宽度会是过期值（实测 nm 恒 640、间隙算成 -639）。
        for _pg in ((self._status_page2,) if on_page2
                    else (self._status_page1,)):
            _lay = _pg.layout()
            if _lay is not None:
                _lay.activate()
        self._status_page_lbl.setText(f"{self._status_page + 1}/{self._status_pages}")
        self._btn_status_prev.setEnabled(self._status_page > 0)
        self._btn_status_next.setEnabled(self._status_page < self._status_pages - 1)

    def _set_bin_taken(self, name, taken):
        """设置料盒取出状态：记录取出起始时刻（用于超时计时）、刷新状态窗体与计时标签。"""
        key = name.split()[0]
        self._bin_taken[key] = taken
        self._paint_bin_state(name)
        rec = self._status_recs.get(name)
        if taken:
            # 进入取出态：记录起始时刻、清除上一次超时报警标记
            self._bin_taken_since[key] = time.monotonic() * 1000.0
            self._bin_taken_timeout_alarmed.discard(key)
            if rec is not None:
                rec["taken_timeout"] = False
        else:
            # 放回：清除计时、超时标记与计时标签
            self._bin_taken_since.pop(key, None)
            self._bin_taken_timeout_alarmed.discard(key)
            if rec is not None:
                rec["taken_timeout"] = False
                tl = rec.get("time_lbl")
                if tl is not None:
                    tl.setText("")
                    tl.setVisible(False)   # 放回后隐藏计时

    def _paint_bin_state(self, name):
        """料盒「满料 / 取出 / 未取出」状态窗体：
        - 满料（达 100%）→ 红底白字「满料，请取料」突出显示；
        - 取出 → 红底白字「取出」；
        - 未取出 → 绿底白字「未取出」。
        """
        rec = self._status_recs.get(name)
        if rec is None or rec.get("state_lbl") is None:
            return
        key = name.split()[0]
        bg = COLORS["accent_green"]
        text = BIN_STATE_TEXT[False]
        if self._bin_full.get(key, False):
            bg = COLORS["accent_red"]
            text = "满料，请取料"
        elif self._bin_taken.get(key, False):
            bg = COLORS["accent_red"]
            text = BIN_STATE_TEXT[True]
        rec["state_lbl"].setText(text)
        rec["state_lbl"].setStyleSheet(
            f"color: #FFFFFF; font-size: 9px; font-weight: bold; "
            f"background-color: {bg}; border: 1px solid {bg}; "
            f"border-radius: 3px; padding: 2px 4px;")

    def _status_color(self, p):
        """设备运行状态配色：100% 红（满料/寿命到期），80%~<100% 黄，80% 以下绿。"""
        if p >= 100:
            return COLORS["accent_red"]
        if p >= 80:
            return COLORS["accent_yellow"]
        return COLORS["accent_green"]

    def _paint_status_dot(self, rec):
        """按运行态/实时测量决定状态灯颜色：
        - 视觉控制器 → 依在线/离线显示绿/红（示例演示默认保持在线）；
        - 料盒 → 始终按真实状态着色（满料红 / 百分比三色），停止后依旧显示真实状态；
        - 急停按钮 → 急停激活时红灯闪（由 estop 逻辑驱动），正常态（含停止后）显示绿色；
        - 停止 → 统一显示正常状态（绿），不再置灰（仅料盒/视觉控制器保持真实状态）；
        - 运行中 → 实时测量行随测量值绿/红；纯状态行正常（绿）；其余百分比行三色。
        """
        if rec.get("is_vision"):
            col = (COLORS["accent_green"] if rec.get("online", True)
                   else COLORS["accent_red"])
        elif rec["name"] == "玻璃盘上下跳动":
            # 跳动值 > 0.05 mm（落在 10% 的 0.05~0.06 高段）→ 状态灯红，否则绿
            try:
                _gj = float(rec["val_box"].text())
            except (ValueError, TypeError):
                _gj = 0.0
            col = (COLORS["accent_red"] if _gj > 0.05
                   else COLORS["accent_green"])
        elif rec["name"].endswith("料盒"):
            # 料盒：始终按真实状态着色，停止后依旧显示真实状态（满料保持红）
            if self._bin_full.get(rec["name"].split()[0], False):
                col = COLORS["accent_red"]
            else:
                col = self._status_color(int(round(rec.get("pct_val") or 0)))
        elif rec["name"] == "急停按钮" and getattr(self, "_estop_active", False):
            # 急停激活（红灯闪）优先，避免被下方逻辑覆盖为绿
            col = COLORS["accent_red"]
        elif not getattr(self, "_playing", False):
            # 停止态：统一显示正常状态（绿），仅料盒/视觉控制器保持真实状态
            col = COLORS["accent_green"]
        elif rec.get("taken_timeout"):
            # 料盒取出未放回超时：强制红灯（即使运行中）
            col = COLORS["accent_red"]
        elif rec.get("live"):
            col = rec.get("live_color", COLORS["accent_green"])
        elif rec.get("no_pct"):
            col = COLORS["accent_green"]
        else:
            p = int(round(rec.get("pct_val") or 0))
            col = self._status_color(p)
        rec["color"] = col
        rec["dot"].setStyleSheet(f"color: {col}; font-size: 9px;")

    def _apply_status_style(self):
        """按当前主题重绘设备运行状态各行（行底色 / 状态灯 / 名称 / 百分比 / 数值框）。

        边框约定（2026-10-08 需求，共两轮）：
        - **要去掉**：每个完整示例**最外围的大矩形框**（行容器）、每行**右侧单位**的
          外围矩形框、底部「上一页 / 页码 / 下一页」的外围矩形框。
          行容器的 `QFrame {...}` 规则会下传给作为子控件的 QLabel（QLabel 是 QFrame
          子类），因此单位 / 百分比占位等处都**显式**写死自己的边框。
        - **要保留（本轮加回）**：料盒 4 卡的外围框、各行**名称标签**与**状态灯**的小框、
          百分比框 / 数值框的小框。
        """
        for rec in getattr(self, "_status_rows", []):
            self._paint_status_dot(rec)   # 先依运行态/百分比确定状态灯与配色
            col = rec["color"]
            is_door = rec["name"] == "设备门"
            is_bin = rec["name"].endswith("料盒")
            if is_bin:
                # 料盒卡：保留（加回）外围圆角框 —— 它是四个并列料盒的分隔框
                rec["frame"].setStyleSheet(
                    f"QFrame {{ background-color: {COLORS['bg_card']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
            else:
                # 状态行容器：去边框，仅保留底色（作为分组底衬）
                rec["frame"].setStyleSheet(
                    f"QFrame {{ background-color: {COLORS['bg_card']}; border: none; }}")
            # 名称 / 状态灯：显式声明自己的边框 —— QLabel 是 QFrame 子类，
            # 行容器的 QFrame 规则会下传，这里必须自己写死，避免框丢失或外溢。
            # 状态灯只有一个小圆点，不加框；料盒卡内已有整卡外框，名称不再套第二层框。
            if is_bin:
                rec["nm"].setStyleSheet(
                    f"color: {COLORS['text_primary']}; font-size: 9px; "
                    f"font-family: 'Microsoft YaHei'; "
                    f"background-color: transparent; border: none;")
            else:
                rec["nm"].setStyleSheet(
                    f"color: {COLORS['text_primary']}; font-size: 9px; "
                    f"font-family: 'Microsoft YaHei'; "
                    f"background-color: {COLORS['bg_card']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px;")
            rec["dot"].setStyleSheet(
                f"color: {col}; font-size: 9px; "
                f"background-color: transparent; border: none;")
            if rec["pct_box"] is not None:
                if is_door or rec.get("no_pct"):
                    # 设备门 / 无百分比项：占位透明，仅保留数值列对齐位置
                    rec["pct_box"].setStyleSheet("background: transparent; border: none;")
                else:
                    rec["pct_box"].setStyleSheet(
                        f"color: {col}; font-size: 9px; font-weight: bold; "
                        f"font-family: 'Microsoft YaHei'; "
                        f"background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
                        f"border-radius: 3px; padding: 2px;")
            # 视觉控制器：数值窗体按在线/离线着色（在线=绿 / 离线=红）
            if rec.get("is_vision"):
                val_color = (COLORS["accent_green"] if rec.get("online", True)
                             else COLORS["accent_red"])
            # 相机状态：示例保持「在线」，数值窗体绿字（与视觉控制器行一致）
            elif rec["name"] == "相机状态":
                val_color = COLORS["accent_green"]
            # 设备门的数值窗体按实时状态着色（关闭=绿 / 打开=红）
            elif is_door:
                val_color = col
            # 急停按钮：未开启=绿字（正常态）；开启(急停激活)=红字
            elif rec["name"] == "急停按钮":
                val_color = (COLORS["accent_red"] if getattr(self, "_estop_active", False)
                             else COLORS["accent_green"])
            else:
                val_color = COLORS["text_secondary"]
            rec["val_box"].setStyleSheet(
                f"color: {val_color}; font-size: 9px; "
                f"font-family: 'Microsoft YaHei'; "
                f"background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 3px; padding: 2px 6px;")
            if rec["unit"] is not None:
                # 单位：显式去边框 + 去底色（QLabel 为 QFrame 子类，会继承行容器的
                # QFrame 边框规则；这里明确关闭，避免右侧单位外多出一圈矩形框）
                if rec["unit"].text():
                    rec["unit"].setStyleSheet(
                        f"color: {COLORS['text_secondary']}; font-size: 9px; "
                        f"font-family: 'Microsoft YaHei'; "
                        f"background-color: transparent; border: none;")
                else:
                    # 无单位的等宽占位框：完全透明（视觉上不存在，仅用于对齐尾部组）
                    rec["unit"].setStyleSheet(
                        "background-color: transparent; border: none;")
            # 料盒行：同步刷新最右侧「取出 / 未取出」状态窗体（主题切换也能正确重绘）
            if rec["name"].endswith("料盒"):
                self._paint_bin_state(rec["name"])
        # 第 2 页光源状态行同步按新主题重绘
        self._apply_light_style()

    def _update_bin_life(self, reset=False):
        """料盒满料百分比随运行实时更新（累计件数 / 满料停机阈值）。

        每个料盒按 BIN_RATE 独立递增累计件数，从示例种子值起步向满料阈值增长，
        四个料盒按各自速率依次冲到 100%（红），演示三色配色与满料停机报警。
        """
        if reset:
            self._bin_count = dict(getattr(self, "_bin_count_init", {}))
        for key in BIN_KEYS:
            # 取出状态的料盒计数冻结（已取出期间不累计、不推进满料百分比）
            if not reset and self._bin_taken.get(key, False):
                continue
            # 「剔除设定」中关闭的剔除口（NG1/NG2/RST）停止累计，模拟该剔除通道停用
            if (not reset and key in ("NG1", "NG2", "RST")
                    and not self.dev_cfg["reject"]["ports"].get(key.lower(), {}).get("enable", True)):
                continue
            name = key + " 料盒"
            cnt = self._bin_count.get(key, 0)
            if not reset:
                cnt += BIN_RATE.get(key, 1)
                self._bin_count[key] = cnt
            thr = bin_full_threshold(key)
            pct = min(100.0, cnt / thr * 100) if thr else 0.0
            # 满料状态：达 100% 标记满料（红底「满料，请取料」），取走/清零后解除
            was_full = self._bin_full.get(key, False)
            now_full = pct >= 100.0
            if now_full != was_full:
                self._bin_full[key] = now_full
                self._paint_bin_state(name)
            rec = self._status_recs.get(name)
            if rec is not None:
                self._set_status_pct(rec, pct)
                rec["val_box"].setText(str(cnt))
            if pct >= 100.0 and name not in getattr(self, "_bin_alarmed", set()):
                if feature_auto_clear():
                    # 料仓自动清零：达满料阈值即自动清料并继续运行，不触发停机。
                    # 注意：自动清零分支【不】加入 _bin_alarmed，否则第二次到 100% 会被该集合
                    # 守卫跳过、无法再次清零而卡死在 100%。_bin_alarmed 仅用于停机报警去重。
                    self._bin_count[key] = 0
                    self._set_status_pct(rec, 0.0)
                    rec["val_box"].setText("0")
                    lv = getattr(self, "_log_view", None)
                    if lv is not None and hasattr(lv, "add"):
                        ts = datetime.now().strftime("%H:%M:%S")
                        lv.add(ts, f"料仓自动清零：{name}已达满料阈值，已自动清料并继续运行",
                               COLORS["accent_blue"])
                else:
                    self._bin_alarmed.add(name)
                    self._push_bin_alarm(name)

            # 收料百分比满料报警：仅在「百分比从低于阈值上升穿越到阈值及以上」的瞬间触发，
            # 与 100% 满料停机报警相互独立。采用上升穿越判定可避免两类误报：
            #  1) 预置种子已高于阈值（如开局即 50%）时立即误报；
            #  2) 用户把阈值调到当前百分比以下时立即误报。
            pct_thr = bin_full_pct()
            if feature_bin_full_alarm() and 0 < pct_thr < 100:
                prev = self._bin_pct_prev.get(key)
                if prev is None:
                    prev = pct  # 首帧以当前值为基准，防止开局直接误报
                if prev < pct_thr <= pct and name not in self._bin_pct_alarmed:
                    self._bin_pct_alarmed.add(name)
                    lv = getattr(self, "_log_view", None)
                    if lv is not None and hasattr(lv, "add"):
                        ts = datetime.now().strftime("%H:%M:%S")
                        plan = bin_full_plan()
                        suffix = f"（满料报警方案：{plan}）" if plan else ""
                        lv.add(ts, f"{name}收料百分比已达 {pct_thr:.0f}%，触发满料报警{suffix}",
                               COLORS["accent_red"])
                        self._beep()
                if pct < pct_thr:
                    self._bin_pct_alarmed.discard(name)
            self._bin_pct_prev[key] = pct  # 记录本帧百分比，供下帧穿越判定

    def _update_valve_life(self, reset=False):
        """电磁阀寿命百分比随运行实时更新（已用动作次数 / 寿命阈值）。"""
        if reset:
            self._valve_used = dict(getattr(self, "_valve_used_init", {}))
        for key in VALVE_KEYS:
            name = key + " 电磁阀"
            used = self._valve_used.get(key, 0.0)
            if not reset:
                used += VALVE_RATE.get(key, 0.5)
                self._valve_used[key] = used
            thr = valve_life_threshold(key)
            pct = min(100.0, used / thr * 100) if thr else 0.0
            rec = self._status_recs.get(name)
            if rec is not None:
                self._set_status_pct(rec, pct)
                rec["val_box"].setText(f"{used:.0f}")
            # 电磁阀使用寿命报警：已用动作次数达到「报警阈值(%)」即按所选方案报警（每周期一次）
            alarm_pct = valve_alarm_pct()
            if 0 < alarm_pct < 100:
                if pct >= alarm_pct and key not in self._valve_alarmed:
                    self._valve_alarmed.add(key)
                    lv = getattr(self, "_log_view", None)
                    if lv is not None and hasattr(lv, "add"):
                        ts = datetime.now().strftime("%H:%M:%S")
                        plan = valve_alarm_plan()
                        suffix = f"（寿命报警方案：{plan}）" if plan else ""
                        lv.add(ts,
                               f"{name}使用寿命已达 {pct:.0f}%（报警阈值 {alarm_pct:.0f}%），"
                               f"触发寿命报警{suffix}",
                               COLORS["accent_red"])
                        self._beep()
                elif pct < alarm_pct:
                    self._valve_alarmed.discard(key)

    def _set_status_pct(self, rec, pct):
        """刷新某行百分比文本与配色（并同步 restyle 所需的缓存字段）。"""
        if rec.get("name") == "设备门" or rec.get("no_pct"):
            return   # 设备门 / 无百分比项无百分比框，跳过
        p = int(round(pct))
        rec["pct_val"] = p
        rec["pct_f"] = pct  # 精确百分比（未取整），供停机判定按真实 100% 触发，避免四舍五入提前
        rec["pct"] = f"{pct:.2f}%"
        if rec["pct_box"] is not None:
            rec["pct_box"].setText(f"{pct:.2f}%")
            self._paint_status_dot(rec)        # 依运行态/百分比更新状态灯与配色缓存
            rec["pct_box"].setStyleSheet(
                f"color: {rec['color']}; font-size: 9px; font-weight: bold; "
                f"font-family: 'Microsoft YaHei'; "
                f"background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; "
                f"border-radius: 3px; padding: 2px;")

    def _beep(self):
        """报警蜂鸣器：任意报警触发时蜂鸣（由「报警蜂鸣器」开关控制，默认开启）。"""
        if not feature_buzzer():
            return
        try:
            QApplication.beep()
        except Exception:
            pass

    def _push_bin_alarm(self, name):
        """料盒达满料停机阈值时向运行日志推送一条报警（同一料盒仅推送一次）。"""
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            ts = datetime.now().strftime("%H:%M:%S")
            suffix = ""
            if feature_bin_full_alarm():
                plan = bin_full_plan()
                suffix = f"（满料报警方案：{plan}）" if plan else ""
            lv.add(ts, f"{name}已达满料停机阈值，触发停机报警{suffix}", COLORS["accent_red"])
            self._beep()

    def _check_alarm_stop(self):
        """报警联动：任意一个料盒/电磁阀百分比达 100% 时向运行日志报警并触发自动停机。

        仅触发一次（由 self._alarm_stopped 守护），避免重复停机；停机回调由 MainWindow 注入。
        """
        if not getattr(self, "_playing", False) or getattr(self, "_alarm_stopped", False):
            return
        culprits = []
        for name, rec in getattr(self, "_status_recs", {}).items():
            if rec.get("no_pct"):
                continue
            if name.endswith("料盒"):
                # 料盒满料停机：按「满料停机阈值(%)」停机，默认 100%
                if feature_bin_full_stop() and (rec.get("pct_f") or 0.0) >= bin_full_stop_pct():
                    culprits.append(name)
            elif name.endswith("电磁阀"):
                # 电磁阀寿命停机：按「使用寿命停机阈值(%)」停机，默认 100%
                if (rec.get("pct_f") or 0.0) >= valve_stop_pct():
                    culprits.append(name)
        if not culprits:
            return
        self._alarm_stopped = True
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            ts = datetime.now().strftime("%H:%M:%S")
            lv.add(ts, f"【自动停机】{', '.join(culprits)} 已达100%阈值，系统自动停止运行",
                   COLORS["accent_red"])
            self._beep()
        cb = getattr(self, "_alarm_stop_cb", None)
        if cb is not None:
            cb()

    def _check_quant_target(self):
        """定量生产：良品数（良品数量）或 OK 料盒累计数达到设定目标时，自动停机并记日志。

        与满料/寿命停机共用 _alarm_stopped 守卫（仅触发一次），通过 MainWindow 注入的
        回调执行自动停机；停机后状态灯整体转灰。
        """
        if not getattr(self, "_playing", False) or getattr(self, "_alarm_stopped", False):
            return
        if not self.quantitative_enabled():
            return
        target = self.quant_target_value()
        if not target or target <= 0:
            return
        good = int(round(getattr(self, "_live_good", 0.0)))
        ok_bin = int(getattr(self, "_bin_count", {}).get("OK", 0))
        if good >= target:
            reached = f"良品数 {good}"
        elif ok_bin >= target:
            reached = f"OK 料盒数 {ok_bin}"
        else:
            return
        self._alarm_stopped = True
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            ts = datetime.now().strftime("%H:%M:%S")
            lv.add(ts, f"【定量生产达成】{reached} 已达目标 {target} 件，系统自动停止运行",
                   COLORS["accent_red"])
            self._beep()
        cb = getattr(self, "_alarm_stop_cb", None)
        if cb is not None:
            cb()

    @staticmethod
    def _draw_glass_jump_val():
        """玻璃盘上下跳动示例值（mm）：90% 概率在 0.01~0.05 内随机，10% 概率在 0.05~0.06 内随机。"""
        if random.random() < 0.9:
            return random.uniform(0.01, 0.05)
        return random.uniform(0.05, 0.06)

    def _update_device_status_live(self):
        """运行期间模拟总气源 / 旋转盘 / 负压 / 静电四类实时测量值，并驱动状态灯与报警。

        - 示例值在正常范围内小幅随机游走，偶尔越界以演示报警；
        - 范围内指示灯绿色，越界红色；
        - 越界后持续「报警延时」才真正记日志（去抖），记日志后保持「报警时长」再自动解除，
          解除后若仍越界则重新开始延时计数（报警呈周期性闪烁）。
        旋转盘的下/上限取「报警设备」窗口里设置的转盘速度过低/过高阈值。
        """
        if not getattr(self, "_playing", False):
            return
        rd = getattr(self, "_dev_readings", {})
        # 检测速度（Pcs/Min）：与统计数据里的「平均速度」同源（示例约 11000 ±150），
        # 叠加小幅抖动，供「检测速度过低/过高」报警判定（阈值见「报警设备」窗口，默认 8000/12000）。
        _base = float(getattr(self, "_avg_speed", 0.0))
        if _base <= 0:
            _base = 11000.0
        self._detect_pcs = max(10500.0, min(11500.0,
                              _base + random.uniform(-80, 80)))
        # 推进模拟值：向「设备设置」配置的目标值均值回归 + 随机抖动，使改设即时可见
        rd["总气源"]["val"] = max(0.20, min(0.90, rd["总气源"]["val"] + random.uniform(-0.05, 0.05)))
        _c_dd = self.dev_cfg["dd_motor"]["speed_rpm"]
        rd["旋转盘"]["val"] = max(0.0, min(60.0,
            rd["旋转盘"]["val"] + (_c_dd - rd["旋转盘"]["val"]) * 0.10 + random.uniform(-1.0, 1.0)))
        _c_np = self.dev_cfg["neg_press"]["pressure_mpa"]
        rd["负压"]["val"] = max(0.0, min(0.30,
            rd["负压"]["val"] + (_c_np - rd["负压"]["val"]) * 0.10 + random.uniform(-0.01, 0.01)))
        _c_esd = self.dev_cfg["hv_esd"]["voltage_kv"]
        rd["静电"]["val"] = max(0.0, min(5.0,
            rd["静电"]["val"] + (_c_esd - rd["静电"]["val"]) * 0.10 + random.uniform(-0.1, 0.1)))
        # 玻璃盘上下跳动（mm）：每拍按示例分布重新随机（90% 落在 0.01~0.50，10% 落在 0.50~0.60），
        # 仅作示例显示，不参与越界报警
        _gj_rec = self._status_recs.get("玻璃盘上下跳动")
        if _gj_rec is not None:
            _gj_rec["val_box"].setText(f"{self._draw_glass_jump_val():.2f}")
            self._paint_status_dot(_gj_rec)   # 值 > 0.05 mm 时状态灯变红

        delay_ms = alarm_delay_ms()
        duration_ms = alarm_duration_ms()
        now = time.monotonic() * 1000.0

        for name, info in rd.items():
            rec = self._status_recs.get(name)
            if rec is None:
                continue
            # 数值刷新到数值框（单位框在建立时固定）
            rec["val_box"].setText(info["fmt"].format(info["val"]))
            # 判定是否在正常范围内（旋转盘的下/上限取转盘速度报警阈值）
            if name == "旋转盘":
                lo = sq_threshold("turntable_low")
                hi = sq_threshold("turntable_high")
                unit = "RPM"
            else:
                lo, hi = info["lo"], info["hi"]
                unit = info["unit"]
            in_range = (lo <= info["val"] <= hi)
            if in_range:
                info["out_since"] = None
                info["fired_at"] = None
                info["active"] = False
                info["live_color"] = COLORS["accent_green"]
                # 刚从报警态恢复至正常：补一条恢复日志，保证日志齐全
                if info.get("_alarmed"):
                    info["_alarmed"] = False
                    self._log_device_recover(name, unit)
            else:
                if info["out_since"] is None:
                    info["out_since"] = now
                info["live_color"] = COLORS["accent_red"]
                if (now - info["out_since"] >= delay_ms) and not info["active"]:
                    info["active"] = True
                    info["fired_at"] = now
                    info["_alarmed"] = True
                    self._log_device_alarm(name, info["val"], lo, hi, unit)
                elif info["active"] and duration_ms > 0 and (now - info["fired_at"] >= duration_ms):
                    # 报警时长到，自动解除并重新开始延时计数（仍未恢复，不记恢复日志）
                    info["active"] = False
                    info["out_since"] = now
            rec["live_color"] = info["live_color"]
            self._paint_status_dot(rec)

    def _log_device_alarm(self, name, val, lo, hi, unit):
        """向运行日志推送一条设备状态越界报警（红色）。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        disp = _LIVE_DISP.get(name, name)
        ts = datetime.now().strftime("%H:%M:%S")
        if val > hi:
            detail = f"{val:.2f} {unit} > 上限 {hi:.2f} {unit}"
        else:
            detail = f"{val:.2f} {unit} < 下限 {lo:.2f} {unit}"
        lv.add(ts, f"报警：{disp}异常（{detail}）", COLORS["accent_red"])
        self._beep()

    def _log_device_recover(self, name, unit):
        """向运行日志推送一条设备状态恢复至正常的记录（绿色）。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        disp = _LIVE_DISP.get(name, name)
        ts = datetime.now().strftime("%H:%M:%S")
        lv.add(ts, f"报警恢复：{disp}恢复至正常", COLORS["accent_green"])

    def _check_speed_quality_alarms(self):
        """速度/良率报警：任意指标超出设定阈值即在运行日志记录报警（不触发停机）。

        采用「进入报警态只记一次」策略——用 _active_sq_alarms 集合记录当前处于报警态的项，
        恢复后从集合中移除，下次再越界会重新记录，避免运行期间重复刷屏。
        """
        if not getattr(self, "_playing", False):
            return
        # 注：转盘速度（旋转盘）的过低/过高报警改由设备运行状态「旋转盘」实时行负责，
        # 避免与速度/良率报警重复记录；此处仅检查检测速度 / 良品率 / 重检率。
        pcs = self._detect_pcs
        yld = self._live_yield
        rechk = self._live_rechk_rate
        # 单相机良率低：比较各相机实时最低良率（取最差的一路相机）
        worst_cam_yield = 100.0
        for i in range(8):
            g = self._live_cam_good[i]
            b = self._live_cam_bad[i]
            tot = g + b
            cy = (g / tot * 100.0) if tot else 100.0
            worst_cam_yield = min(worst_cam_yield, cy)
        self._worst_cam_yield = worst_cam_yield
        checks = [
            ("detect_low", pcs < sq_threshold("detect_low"),
             f"检测速度过低：{pcs:.0f} Pcs/Min < 阈值 {sq_threshold('detect_low')} Pcs/Min"),
            ("detect_high", pcs > sq_threshold("detect_high"),
             f"检测速度过高：{pcs:.0f} Pcs/Min > 阈值 {sq_threshold('detect_high')} Pcs/Min"),
            ("good_low", yld < sq_threshold("good_low"),
             f"综合良率低：{yld:.2f}% < 阈值 {sq_threshold('good_low')}%"),
            ("cam_yield_low", worst_cam_yield < sq_threshold("cam_yield_low"),
             f"单相机良率低：最低相机良率 {worst_cam_yield:.2f}% < 阈值 {sq_threshold('cam_yield_low')}%"),
            ("recheck_high", rechk > sq_threshold("recheck_high"),
             f"重检率过高：{rechk:.2f}% > 阈值 {sq_threshold('recheck_high')}%"),
        ]
        lv = getattr(self, "_log_view", None)
        for key, breached, msg in checks:
            if breached and key not in self._active_sq_alarms:
                self._active_sq_alarms.add(key)
                if lv is not None and hasattr(lv, "add"):
                    ts = datetime.now().strftime("%H:%M:%S")
                    plan = sq_plan(key)
                    suffix = f"（报警方案：{plan}）" if plan else ""
                    lv.add(ts, f"报警：{msg}{suffix}", COLORS["accent_red"])
                    self._beep()
            elif not breached and key in self._active_sq_alarms:
                self._active_sq_alarms.discard(key)
                # 恢复至正常：补一条恢复日志，保证日志齐全
                disp = _SQ_RECOVERY.get(key, key)
                if lv is not None and hasattr(lv, "add"):
                    ts = datetime.now().strftime("%H:%M:%S")
                    lv.add(ts, f"报警恢复：{disp}恢复至正常", COLORS["accent_green"])

    # ------------------------------------------------------------------
    # OK 良品料仓误漏剔除监控 + 门打开报警（两个可开启的附加报警功能）
    # ------------------------------------------------------------------
    def _update_mis_freq_display(self):
        """刷新设备运行状态区的 OK 料仓误踢/漏踢频率示例值（Pcs/H），运行期间小幅随机游走；
        均值回归到略低于设定阈值的中心，使其会在阈值附近波动、偶尔越界以演示报警。"""
        if not getattr(self, "_playing", False):
            return
        # 中心略低于阈值，使频率在阈值附近游动、偶尔越过阈值触发报警（演示用）
        sens = 1.0
        cw = max((mis_wrong_threshold() - 4.0) * sens, 2.0)
        cm = max((mis_miss_threshold() - 4.0) * sens, 2.0)
        self._mis_wrong_rate = max(0.0, min(90.0,
            self._mis_wrong_rate + (cw - self._mis_wrong_rate) * 0.08 + random.uniform(-3.5, 3.5)))
        self._mis_miss_rate = max(0.0, min(90.0,
            self._mis_miss_rate + (cm - self._mis_miss_rate) * 0.08 + random.uniform(-3.0, 3.0)))
        for name, rate in (("OK料仓误踢频率", self._mis_wrong_rate),
                           ("OK料仓漏踢频率", self._mis_miss_rate)):
            rec = self._status_recs.get(name)
            if rec is not None:
                # 单位「Pcs/H」已在建行时作为独立标签，这里只刷新数值，避免重复显示
                rec["val_box"].setText(f"{rate:.0f}")

    def _record_mis_reject(self, kind):
        """记录一次误踢 / 漏踢事件（滚动 1 小时窗口），仅对应监控开启时生效。"""
        if kind == "wrong":
            if not feature_mis_wrong():
                return
        else:
            if not feature_mis_miss():
                return
        lst = self._mis_wrong_events if kind == "wrong" else self._mis_miss_events
        lst.append(time.monotonic() * 1000.0)

    @staticmethod
    def _count_recent(lst, now, window):
        """统计窗口内事件数并清理过期时间戳（窗口单位 ms）。"""
        cutoff = now - window
        while lst and lst[0] < cutoff:
            lst.pop(0)
        return len(lst)

    def _set_mis_dot(self, name, breach):
        """误踢/漏踢频率行状态灯：越界变红、恢复正常变绿（不强制停机）。"""
        rec = self._status_recs.get(name)
        if rec is None:
            return
        rec["live_color"] = COLORS["accent_red"] if breach else COLORS["accent_green"]
        self._paint_status_dot(rec)

    def _check_mis_reject(self):
        """OK 良品料仓误漏剔除监控：误踢/漏踢的实时频率（Pcs/H）超过设定阈值即按触发方式报警或停机。

        - 越界时对应频率行状态灯变红；恢复（低于阈值）后变绿。
        - 触发方式 = 停机：与满料/定量停机共用 _alarm_stopped 守卫（仅触发一次），自动停机；
        - 触发方式 = 报警：仅向运行日志推送一条报警（红色）并蜂鸣，每次越界记一次（恢复后解除）。
        """
        if not getattr(self, "_playing", False):
            self._set_mis_dot("OK料仓误踢频率", False)
            self._set_mis_dot("OK料仓漏踢频率", False)
            self._mis_alarm_logged = False
            return
        # 误踢 / 漏踢各自独立开关、报警方案与阈值
        wrong_on = feature_mis_wrong()
        miss_on = feature_mis_miss()
        thr_w = mis_wrong_threshold() if wrong_on else 0
        thr_m = mis_miss_threshold() if miss_on else 0
        wrong_breach = wrong_on and self._mis_wrong_rate >= thr_w
        miss_breach = miss_on and self._mis_miss_rate >= thr_m
        self._set_mis_dot("OK料仓误踢频率", wrong_breach)
        self._set_mis_dot("OK料仓漏踢频率", miss_breach)
        if not (wrong_breach or miss_breach):
            self._mis_alarm_logged = False
            return
        detail = []
        if wrong_breach:
            detail.append(f"误踢 {self._mis_wrong_rate:.0f} Pcs/H ≥ 阈值 {thr_w}")
        if miss_breach:
            detail.append(f"漏踢 {self._mis_miss_rate:.0f} Pcs/H ≥ 阈值 {thr_m}")
        msg = f"误漏剔除超阈值：{'; '.join(detail)}"
        # 报警方案：误踢优先取误踢方案，否则取漏踢方案（按别名显示）
        if wrong_breach:
            plan = state_plan_by_alias(mis_wrong_plan())
            plan_name = plan.get("alias", mis_wrong_plan()) if plan else mis_wrong_plan()
        else:
            plan = state_plan_by_alias(mis_miss_plan())
            plan_name = plan.get("alias", mis_miss_plan()) if plan else mis_miss_plan()
        if getattr(self, "_mis_alarm_logged", False):
            return
        self._mis_alarm_logged = True
        self._push_alarm(f"{msg}（报警方案：{plan_name}）", stop=False)

    def _push_alarm(self, msg, stop=False):
        """向运行日志推送一条报警（红色）并蜂鸣；stop=True 时额外触发自动停机回调。"""
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            ts = datetime.now().strftime("%H:%M:%S")
            prefix = "【误漏剔除报警停机】" if stop else "报警："
            lv.add(ts, prefix + msg, COLORS["accent_red"])
            self._beep()
        if stop:
            cb = getattr(self, "_alarm_stop_cb", None)
            if cb is not None:
                cb()

    # ------------------------------------------------------------------
    # 急停报警：示例演示中常态保持「未开启」，仅以极低概率随机触发一次
    # ------------------------------------------------------------------
    def _schedule_estop_random(self):
        """为本次运行随机安排一次「急停被按下」的时刻。

        示例程序要求急停按钮常态保持「未开启」：绝大多数演示时长内都不会触发。
        触发时刻取 5~60 分钟的三角分布（众数约 10 分钟）——
        即最快也要运行 5 分钟才可能触发，多数在 10 分钟左右，偶尔要 1 小时。
        """
        minutes = random.triangular(_ESTOP_MIN_MINUTES, _ESTOP_MAX_MINUTES,
                                    _ESTOP_PEAK_MINUTES)
        self._estop_due_ts = time.time() + minutes * 60.0

    def _check_estop_random(self):
        """到点则触发一次急停（按下急停 → 设备紧急停止 + 红灯闪 + 运行日志）。"""
        if not getattr(self, "_playing", False):
            return
        if getattr(self, "_estop_active", False) or not feature_estop_alarm():
            return
        due = getattr(self, "_estop_due_ts", None)
        if due is None or time.time() < due:
            return
        self._estop_due_ts = None
        self._trigger_estop("急停按钮被按下，设备紧急停止")
        # 急停即停机：与报警自动停机共用同一条停机链路
        self._alarm_stopped = True
        cb = getattr(self, "_alarm_stop_cb", None)
        if cb is not None:
            cb()

    def _trigger_estop(self, reason):
        """急停报警：急停按钮被按下（示例为极低概率随机触发）→ 状态灯红灯闪（+可选蜂鸣），
        运行日志记录红色报警。"""
        if not feature_estop_alarm():
            return
        self._estop_active = True
        self._estop_blink_on = True
        lv = getattr(self, "_log_view", None)
        if lv is not None and hasattr(lv, "add"):
            ts = datetime.now().strftime("%H:%M:%S")
            lv.add(ts, f"【急停按钮】{reason}", COLORS["accent_red"])
        # 提示方式含蜂鸣时蜂鸣一次
        if estop_mode() == "blink_buzzer":
            self._beep()
        # 设备运行状态面板：值窗体显示「开启」，状态灯立即变红
        rec = self._status_recs.get("急停按钮")
        if rec is not None:
            rec["val_box"].setText("开启")
            self._apply_status_style()
        # 启动红灯闪烁定时器（~400ms 切换一次亮/灭）
        if getattr(self, "_estop_timer", None) is None:
            self._estop_timer = QTimer(self)
            self._estop_timer.timeout.connect(self._estop_blink)
        self._estop_timer.start(400)

    def _estop_blink(self):
        """急停红灯闪烁：在红色与熄灭之间切换状态灯（仅急停激活时有效）。"""
        if not getattr(self, "_estop_active", False):
            return
        self._estop_blink_on = not self._estop_blink_on
        rec = self._status_recs.get("急停按钮")
        if rec is not None:
            col = COLORS["accent_red"] if self._estop_blink_on else COLORS["bg_panel"]
            rec["dot"].setStyleSheet(f"color: {col}; font-size: 9px;")

    def _clear_estop(self):
        """解除急停报警：停止闪烁、状态灯复位、值窗体恢复「正常」。"""
        self._estop_active = False
        self._estop_blink_on = False
        timer = getattr(self, "_estop_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        rec = self._status_recs.get("急停按钮")
        if rec is not None:
            rec["val_box"].setText("未开启")
            # 解除急停后恢复「未开启」绿色（正常态，不再置灰）
            self._apply_status_style()

    def _update_door_status(self):
        """门打开报警：功能开启时，设备门打开即按触发方式报警或停机，关闭后恢复。

        演示用：开启后设备门以低概率随机打开/关闭，以直观展示报警与恢复日志。
        """
        if not getattr(self, "_playing", False):
            return
        rec = self._status_recs.get("设备门")
        if not feature_door_alarm():
            if rec is not None:
                rec["val_box"].setText("已关闭")
                rec["live_color"] = COLORS["accent_green"]
                self._paint_status_dot(rec)
            return
        # 演示：关闭态以小概率打开，打开态以较高概率关闭，形成偶发开关
        if not getattr(self, "_door_open", False):
            if random.random() < 0.03:
                self._door_open = True
        else:
            if random.random() < 0.20:
                self._door_open = False
        if rec is None:
            return
        if self._door_open:
            rec["val_box"].setText("已打开")
            rec["live_color"] = COLORS["accent_red"]
            if not getattr(self, "_door_alarmed", False):
                self._door_alarmed = True
                if feature_door_mode() == "stop":
                    if not getattr(self, "_alarm_stopped", False):
                        self._alarm_stopped = True
                        self._push_alarm("设备门已打开（门打开报警）", stop=True)
                else:
                    self._log_door_alarm()
        else:
            rec["val_box"].setText("已关闭")
            rec["live_color"] = COLORS["accent_green"]
            if getattr(self, "_door_alarmed", False):
                self._door_alarmed = False
                self._log_door_recover()
        self._paint_status_dot(rec)

    def _log_door_alarm(self):
        """设备门打开时向运行日志推送一条报警（红色），并标注所选报警方案。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        plan = feature_door_alarm_plan()
        suffix = f"（报警方案：{plan}）" if plan else ""
        lv.add(ts, f"报警：设备门已打开（门打开报警）{suffix}", COLORS["accent_red"])
        self._beep()

    def _log_door_recover(self):
        """设备门关闭后向运行日志推送一条恢复记录（绿色）。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        lv.add(ts, "报警恢复：设备门已关闭，恢复至正常", COLORS["accent_green"])

    # ------------------------------------------------------------------
    # 视觉控制器：在线/离线状态显示 + 同步日志记录与提醒
    # ------------------------------------------------------------------
    def set_vision_online(self, online, *, force=False, log=True, remind=True):
        """设置视觉控制器在线/离线状态。
        - 在线：绿底「在线」；离线：红底「离线」。
        - 状态变化（或 force）时刷新设备运行状态面板的状态灯与文本。
        - log=True 时在运行日志记录（离线=红色报警，恢复=绿色）。
        - remind=True 且离线时弹出提醒框；恢复在线亦给出提醒。
        - force=True 用于启动初始化，不记日志、不弹提醒。
        示例演示默认保持在线（见 start_playback），日常不会随机离线。
        """
        if self._vision_online == online and not force:
            return
        changed = self._vision_online != online
        self._vision_online = online
        rec = self._status_recs.get("视觉控制器")
        if rec is None:
            return
        rec["online"] = online
        rec["val_box"].setText("在线" if online else "离线")
        self._paint_status_dot(rec)
        self._apply_status_style()   # 重绘数值窗体颜色（绿/红）
        if changed and log and not force:
            if online:
                self._log_vision_recover()
            else:
                self._log_vision_alarm()
        if changed and remind and not force:
            if not online:
                QMessageBox.warning(
                    self, "视觉控制器离线",
                    "视觉控制器已离线，请检查设备连接与通讯状态！")
            else:
                QMessageBox.information(
                    self, "视觉控制器恢复在线",
                    "视觉控制器已恢复在线。")

    def _log_vision_alarm(self):
        """视觉控制器离线时向运行日志推送一条报警（红色）+ 蜂鸣。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        lv.add(ts, "报警：视觉控制器离线（请检查连接与通讯）", COLORS["accent_red"])
        self._beep()

    def _log_vision_recover(self):
        """视觉控制器恢复在线时向运行日志推送一条恢复记录（绿色）。"""
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        lv.add(ts, "报警恢复：视觉控制器恢复在线", COLORS["accent_green"])

    def _vision_context_menu(self, pos):
        """右键视觉控制器状态行：手动模拟离线/恢复，用于演示日志记录与提醒。"""
        m = QMenu(self)
        off = m.addAction("模拟视觉控制器离线")
        on = m.addAction("恢复视觉控制器在线")
        act = m.exec(self.sender().mapToGlobal(pos))
        if act is None:
            return
        if act is off:
            self.set_vision_online(False)
        elif act is on:
            self.set_vision_online(True)

    # ------------------------------------------------------------------
    # 料盒取出未放回超时报警（演示：随机切换料盒取出态 + 实时计时 + 超阈值报警）
    # ------------------------------------------------------------------
    def _update_bin_taken_status(self):
        """料盒取出未放回超时监控。

        - 演示：运行中以低概率随机把某个料盒切到取出/未取出，直观展示计时与超时报警；
        - 处于取出态的料盒实时刷新「已取出时长 (s)」标签；
        - 时长超过设定阈值：功能开启 → 状态灯变红 + 记红色报警日志 + 蜂鸣；
          功能关闭 → 不变红，但仍在运行日志记录一条提示（不报警）。
        """
        if not getattr(self, "_playing", False):
            return
        # 演示：以较低概率把 NG1 料盒切到取出/未取出（按需求以 NG1 料盒作为示例）
        if random.random() < 0.10:
            k = "NG1"
            self._set_bin_taken(k + " 料盒", not self._bin_taken.get(k, False))

        now = time.monotonic() * 1000.0
        thr = bin_taken_timeout_ms()
        feat = feature_bin_taken_timeout()
        lv = getattr(self, "_log_view", None)
        for k in BIN_KEYS:
            name = k + " 料盒"
            rec = self._status_recs.get(name)
            if rec is None:
                continue
            tl = rec.get("time_lbl")
            if not self._bin_taken.get(k, False):
                if tl is not None and tl.text():
                    tl.setText("")
                    tl.setVisible(False)
                continue
            since = self._bin_taken_since.get(k)
            elapsed = (now - since) if since is not None else 0.0
            if tl is not None:
                # 以秒（s）为单位显示，保留 2 位小数（如 856 ms → 0.86 s）
                tl.setText(f"{elapsed / 1000.0:.2f} s")
                tl.setVisible(True)
            if elapsed < thr:
                continue
            # 超过阈值：按功能开关决定变红报警 / 仅提示；处理方式=停机时触发自动停机
            if feat:
                rec["taken_timeout"] = True
                self._paint_status_dot(rec)
                if k not in self._bin_taken_timeout_alarmed:
                    self._bin_taken_timeout_alarmed.add(k)
                    if lv is not None and hasattr(lv, "add"):
                        ts = datetime.now().strftime("%H:%M:%S")
                        if feature_bin_taken_timeout_mode() == "stop":
                            # 处理方式 = 停机：触发自动停机（红灯/蜂鸣由停机逻辑统一处理）
                            if not getattr(self, "_alarm_stopped", False):
                                self._alarm_stopped = True
                                self._push_alarm(
                                    f"{name}取出未放回超时（{elapsed:.0f} ms ≥ 阈值 {thr} ms）",
                                    stop=True)
                        else:
                            # 处理方式 = 报警：按所选报警方案（别名）显示报警，记报警日志并蜂鸣
                            plan = state_plan_by_alias(bin_taken_timeout_plan())
                            plan_name = plan.get("alias", bin_taken_timeout_plan()) if plan else bin_taken_timeout_plan()
                            lv.add(ts,
                                   f"报警：{name}取出未放回超时（{elapsed:.0f} ms ≥ 阈值 {thr} ms）【报警方案：{plan_name}】",
                                   COLORS["accent_red"])
                            self._beep()
            else:
                # 功能关闭：不变红，但仅在本次取出周期内记一条提示
                rec["taken_timeout"] = False
                self._paint_status_dot(rec)
                if k not in self._bin_taken_timeout_alarmed:
                    self._bin_taken_timeout_alarmed.add(k)
                    if lv is not None and hasattr(lv, "add"):
                        ts = datetime.now().strftime("%H:%M:%S")
                        lv.add(ts, f"提示：{name}取出未放回已超时（{elapsed:.0f} ms），"
                                   f"报警功能未开启", COLORS["accent_blue"])

    # ------------------------------------------------------------------
    # 连续混料 / 连续产品歪斜 / 连续连料 报警（各自独立连续计数，超阈值报警）
    # ------------------------------------------------------------------
    def _tick_consecutive(self, f_attr, alarmed_attr, disp, feature_on, threshold):
        """推进一项连续不良报警：连续计数在阈值附近随机游走，越界记红色报警、恢复记绿色。

        f_attr/alarmed_attr 为 self 上的浮点计数与布尔报警标记属性名；disp 为日志显示名。
        """
        if not getattr(self, "_playing", False):
            return
        val = getattr(self, f_attr)
        center = max(threshold - 3.0, 1.0)
        val = max(0.0, min(threshold + 6.0,
                           val + (center - val) * 0.15 + random.uniform(-2.5, 2.5)))
        setattr(self, f_attr, val)
        count = int(round(val))
        breached = val >= threshold
        alarmed = getattr(self, alarmed_attr)
        lv = getattr(self, "_log_view", None)
        if feature_on and breached and not alarmed:
            setattr(self, alarmed_attr, True)
            if lv is not None and hasattr(lv, "add"):
                ts = datetime.now().strftime("%H:%M:%S")
                lv.add(ts, f"报警：{disp}连续 {count} 件（≥ 阈值 {threshold} 件）",
                       COLORS["accent_red"])
                self._beep()
        elif not breached and alarmed:
            setattr(self, alarmed_attr, False)
            if lv is not None and hasattr(lv, "add"):
                ts = datetime.now().strftime("%H:%M:%S")
                lv.add(ts, f"报警恢复：{disp}恢复至正常", COLORS["accent_green"])

    def _check_consecutive_alarms(self):
        """连续混料 / 连续产品歪斜 / 连续连料 三项报警的统一入口。"""
        self._tick_consecutive("_consec_mix_f", "_consec_mix_alarmed",
                               "连续混料", feature_cont_mix(), cont_mix_threshold())
        self._tick_consecutive("_consec_tilt_f", "_consec_tilt_alarmed",
                               "连续产品歪斜", feature_cont_tilt(), cont_tilt_threshold())
        self._tick_consecutive("_consec_stick_f", "_consec_stick_alarmed",
                               "连续连料", feature_cont_stick(), cont_stick_threshold())

    # ------------------------------------------------------------------
    # 生产统计与检测结果：KPI 2 行排布（可编辑）+ 环形图 + 速度 + 按钮
    # ------------------------------------------------------------------
    def _build_stats(self):
        lay = QVBoxLayout()
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 统计时段筛选：切换后所有示例数据联动刷新；白班/中班/晚班可设默认起止时间
        frow = QHBoxLayout()
        frow.setSpacing(8)
        cb = QComboBox()
        cb.addItems(["当前运行", "指定时间段", "白班", "中班", "晚班"])
        cb.setMinimumHeight(28)
        cb.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        cb.currentTextChanged.connect(
            lambda t: self.log_operation(getattr(self, "_op_user", "操作员"),
                                         f"切换了统计时段为 {t}"))
        d1 = QLineEdit("开始日期")
        d1.setMinimumHeight(28)
        d1.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        d2 = QLineEdit("结束日期")
        d2.setMinimumHeight(28)
        d2.setStyleSheet("font-family: 'Microsoft YaHei'; font-size: 9px;")
        frow.addWidget(cb)
        frow.addWidget(d1, 1)
        frow.addWidget(d2, 1)
        # 「检索」按钮左侧的产品多选筛选下拉：列出新建过的产品，可复选；选中项随检索生效
        self._product_filter = ProductFilterCombo(provider=lambda: self._resolve_products())
        self._product_filter.selectionChanged.connect(self._on_stat_filter_changed)
        frow.addWidget(self._product_filter)
        # 该行按钮（自左向右）：「检索」按检索方式+时间范围刷新统计并固定显示；「导出」弹出生产报表页面
        self._btn_search_stat = QPushButton("检索")
        self._btn_search_stat.setFixedHeight(28)
        self._btn_search_stat.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_search_stat.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 6px; "
            f"font-size: 9px; }}"
            f"QPushButton:hover:!disabled {{ background-color: {COLORS['accent_blue']}; color: white; }}"
            f"QPushButton:disabled {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']}; }}")
        self._btn_search_stat.clicked.connect(self._on_search_stats)
        # 该行最右侧「导出」按钮：点击弹出生产报表页面
        self._btn_export_report = QPushButton("导出")
        self._btn_export_report.setFixedHeight(28)
        self._btn_export_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export_report.setToolTip("导出生产报表")
        self._btn_export_report.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; padding: 0 6px; "
            f"font-size: 9px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; color: white; }}")
        self._btn_export_report.clicked.connect(self._open_production_report)
        frow.addWidget(self._btn_search_stat)
        frow.addWidget(self._btn_export_report)
        lay.addLayout(frow)

        # 当前统计时段（默认当前运行），作为所有示例数据的数据源
        self.period = "当前运行"
        self._cleared = False
        # 检索固定显示：点「检索」后统计 UI 冻结（周期刷新不再改写），切回「当前运行」自动解冻
        self._stat_frozen = False
        # 持久化的时段默认时间（白班/中班/晚班等修改后下次启动沿用）
        self.period_times = load_period_times()
        # 保留时间输入框引用，供时段切换时回填起止时间
        self.d_start = d1
        self.d_end = d2
        d1.textChanged.connect(self._on_time_edited)
        d2.textChanged.connect(self._on_time_edited)

        # KPI：单行 7 项，数值双击可编辑（数据取自当前时段）
        kpi_items = PERIOD_DATA[self.period]["kpi"]
        self.kpi_grid = EditableKpiGrid(kpi_items, cols=7)
        self._kpi_example = kpi_items
        lay.addWidget(self.kpi_grid)

        # 环形图 + 图例（图例置于右侧，按 4 行放置）
        # 三种统计方式的数据集：切换后饼图与图例联动更新
        self.stat_mode = "按剔除口统计"
        self._chart_view_mode = "pie"
        self.stat_datasets = {m: [tuple(x) for x in PERIOD_DATA[self.period]["donut"][m]]
                              for m in PERIOD_DATA[self.period]["donut"]}
        # 保存示例数据快照，供「统计清零」后恢复
        self._donut_example = {m: [tuple(x) for x in PERIOD_DATA[self.period]["donut"][m]]
                               for m in PERIOD_DATA[self.period]["donut"]}
        data = self.stat_datasets[self.stat_mode]
        self.chart_stack = QStackedWidget()

        # 第 0 页：饼图/详情 可切换容器（默认显示饼图）
        chart_container = QWidget()
        chart_container.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        container_layout = QVBoxLayout(chart_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        # 饼图 / 详情 切换按钮（放到卡片标题栏右侧，见 _build_panels 中 set_header_actions）
        self._btn_pie = QPushButton("饼图")
        self._btn_detail = QPushButton("详情")
        for b in (self._btn_pie, self._btn_detail):
            b.setFixedHeight(22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont("Microsoft YaHei", 9))
        self._btn_pie.clicked.connect(lambda: self._set_chart_view("pie"))
        self._btn_detail.clicked.connect(lambda: self._set_chart_view("detail"))

        self._inner_stack = QStackedWidget()

        # 饼图页：环形图 + 图例
        donut_page = QWidget()
        donut_page.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        chart_box = QHBoxLayout(donut_page)
        chart_box.setContentsMargins(0, 0, 0, 0)
        chart_box.setSpacing(20)
        chart_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.donut_chart = DonutChart(data)
        self.donut_chart.setFixedSize(160, 160)
        chart_box.addWidget(self.donut_chart)
        # 右侧图例：剔除口 / 数量 / 比例 三列左对齐（网格布局保证列对齐，列间隙适中）
        self.legend_layout = QGridLayout()
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setHorizontalSpacing(12)
        self.legend_layout.setVerticalSpacing(6)
        self._refresh_legend(data)
        chart_box.addLayout(self.legend_layout)
        self._inner_stack.addWidget(donut_page)

        # 详情页：各相机不同剔除口的数量及比例
        self._reject_detail_view = RejectDetailView()
        self._inner_stack.addWidget(self._reject_detail_view)

        container_layout.addWidget(self._inner_stack, 1)
        self.chart_stack.addWidget(chart_container)

        # 第 1 页：按相机统计（标签页 + 双表）
        self.camera_stats_view = CameraStatsView(
            camera_stats_data=PERIOD_DATA[self.period]["camera_stats"],
            camera_defects_data=PERIOD_DATA[self.period]["camera_defects"])
        self.chart_stack.addWidget(self.camera_stats_view)

        # 第 2 页：按缺陷项统计（饼图 / 详情 切换容器）
        self.defect_stats_view = DefectStatsContainer(
            camera_defects_data=PERIOD_DATA[self.period]["camera_defects"])
        self.chart_stack.addWidget(self.defect_stats_view)

        # 默认显示饼图，并初始化详情表
        self._set_chart_view("pie")

        # 速度指标（同一行显示，颜色区分）：置于环状饼图上方（与调试界面 StatsPanel 一致）
        srow = QHBoxLayout()
        srow.setSpacing(12)
        s1 = QLabel("平均速度：0 Pcs/Min")
        s1.setStyleSheet(
            f"color: {COLORS['accent_blue']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        s2 = QLabel("瞬时速度：0 Pcs/Min")
        s2.setStyleSheet(
            f"color: {COLORS['accent_orange']}; font-size: 12px; font-weight: bold; "
            f"background-color: {COLORS['bg_panel']}; border-radius: 4px; padding: 3px 6px;")
        self.s1 = s1
        self.s2 = s2
        srow.addWidget(s1)
        srow.addStretch()
        srow.addWidget(s2)
        lay.addLayout(srow)

        # 速度示例值：平均 / 瞬时速度随机波动（演示用，每秒刷新一次）
        self._avg_speed = 0
        self._inst_speed = 0.0
        self._stop_elapsed = 0
        self._speed_running = False
        self._speed_stopped = False
        self._speed_timer = QTimer(self)
        self._speed_timer.timeout.connect(self._tick_speed)
        self._speed_timer.start(1000)
        self._tick_speed()

        # 统计图表区随面板高度撑满，充分利用纵向空间（消除表格上下留白）
        lay.addWidget(self.chart_stack, 1)

        # 统计时段切换联动
        self.period_cb = cb
        cb.currentTextChanged.connect(self._set_period)
        cb.currentTextChanged.connect(self._refresh_search_btn)
        # 初始化：回填当前时段的默认起止时间，并保证数据一致
        self._set_period(self.period)

        # 统计操作按钮（同一行显示）：仅保留「统计配置」「统计清零」两个操作按钮
        self.stat_mode_buttons = {}
        op_names = ["统计配置", "统计清零"]
        brow = QHBoxLayout()
        self._stats_btn_row = brow
        brow.setSpacing(6)
        for name in op_names:
            b = QPushButton(name)
            b.setMinimumHeight(28)
            if name == "统计清零":
                b.clicked.connect(self._toggle_clear)
                self._clear_btn = b
                self._style_clear_button(b, False)
            elif name == "统计配置":
                # 统计配置：蓝色底、白字，点击后底色不变（暂未绑定具体配置对话框）
                self._config_btn = b
                b.setStyleSheet(_BLUE_BTN_STYLE)
            else:
                b.setStyleSheet(
                    f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                    f"font-size: 10px; padding: 4px 10px;")
            brow.addWidget(b)
        brow.addStretch(1)
        # 统计方式切换按钮：移到最右侧（与生产运行界面、调试界面保持一致）
        for name in ("按剔除口统计", "按缺陷项统计"):
            b = QPushButton(name)
            b.setMinimumHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont("Microsoft YaHei", 9))
            b.clicked.connect(lambda checked, m=name: self._set_stat_mode(m))
            self.stat_mode_buttons[name] = b
            self._style_mode_button(b, name == self.stat_mode)
            brow.addWidget(b)

        lay.addLayout(brow)

        return lay

    # 统计方式切换：高亮当前按钮，并联动刷新环形图与图例
    def _style_mode_button(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"background-color: {COLORS['accent_orange']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 10px; "
                f"padding: 4px 10px; font-weight: bold;")
        else:
            btn.setStyleSheet(
                f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 10px; padding: 4px 10px;")

    def _style_chart_view_button(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"background-color: {COLORS['accent_orange']}; color: white; "
                f"border: none; border-radius: 4px; font-size: 12px; "
                f"padding: 2px 12px; font-weight: bold;")
        else:
            btn.setStyleSheet(
                f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 12px; padding: 2px 12px;")

    def _set_chart_view(self, mode):
        """饼图 / 详情 视图切换（按剔除口统计 与 按缺陷项统计 下可见）。"""
        self._chart_view_mode = mode
        self._style_chart_view_button(self._btn_pie, mode == "pie")
        self._style_chart_view_button(self._btn_detail, mode == "detail")
        if self.stat_mode == "按缺陷项统计":
            # 缺陷项统计容器：饼图（聚合缺陷分布）+ 详情（逐相机检测项）
            self.defect_stats_view.set_view(mode)
        else:
            self._inner_stack.setCurrentIndex(0 if mode == "pie" else 1)
            if mode == "detail":
                self._refresh_reject_detail()

    def _set_stat_mode(self, mode):
        self.stat_mode = mode
        # 按缺陷项统计 -> 第 2 页（缺陷项 × 相机 矩阵，含饼图/详情切换）
        # 按剔除口统计（默认）-> 第 0 页（环形图 / 详情 可切换容器）
        if mode == "按缺陷项统计":
            self.chart_stack.setCurrentIndex(2)
            show_toggle = True
        else:
            # 默认「按剔除口统计」：刷新环形图与图例，并回到饼图视图
            self.chart_stack.setCurrentIndex(0)
            show_toggle = True
            if mode == "按剔除口统计":
                self._set_chart_view("pie")
            data = self.stat_datasets[mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = self._period_yield
            self.donut_chart.update()
            self._refresh_legend(data)
        # 饼图/详情 切换按钮在两种统计方式下均可见
        self._btn_pie.setVisible(show_toggle)
        self._btn_detail.setVisible(show_toggle)
        # 进入「按缺陷项统计」时，默认回到饼图视图
        if show_toggle and mode != "按剔除口统计":
            self._set_chart_view("pie")
        for name, btn in self.stat_mode_buttons.items():
            self._style_mode_button(btn, name == mode)

    def set_speed_running(self, running):
        """由设备启动/停止同步速度刷新状态：
        - running=True：进入生产运行态，平均/瞬时速度复位到 11000 并开始波动刷新；
        - running=False：进入停止态，平均速度缓慢衰减（每秒 ×0.96）；瞬时速度独立快速
          衰减，5 秒内明显下降、10 秒后归零（衰减快于平均速度）。"""
        running = bool(running)
        self._speed_running = running
        if running:
            self._speed_stopped = False
            self._avg_speed = 11000
            self._inst_speed = 11000.0
            self._stop_elapsed = 0
        else:
            self._speed_stopped = True
            self._stop_elapsed = 0
        self._tick_speed()

    def _tick_speed(self):
        """刷新速度示例值。

        - 生产运行态（_speed_running=True）：平均速度围绕 11000 ±150 随机游走并钳制在
          [10850, 11150]；瞬时速度随机比平均速度大或小（演示用，每秒刷新一次）。
        - 停止后（_speed_stopped=True）：平均速度缓慢衰减（每秒 ×0.96）；瞬时速度独立
          快速衰减（每秒 ×0.70），5 秒内明显下降、第 10 秒归零，衰减快于平均速度。
        - 未启动（idle）：保持 0，不刷新。"""
        if self._speed_running:
            self._avg_speed = max(
                10850, min(11150, self._avg_speed + random.uniform(-150, 150)))
            avg = int(round(self._avg_speed))
            sign = random.choice([-1, 1])
            self._inst_speed = max(0.0, avg + sign * random.uniform(80, 400))
            inst = int(round(self._inst_speed))
        elif self._speed_stopped:
            # 平均速度：缓慢衰减（与原有行为一致）
            if self._avg_speed > 0:
                self._avg_speed = self._avg_speed * 0.96
                if self._avg_speed < 60:
                    self._avg_speed = 0
            avg = int(round(self._avg_speed))
            # 瞬时速度：独立快速衰减，第 10 秒归零（明显快于平均速度）
            self._stop_elapsed = getattr(self, "_stop_elapsed", 0) + 1
            if self._stop_elapsed >= 10:
                self._inst_speed = 0.0
            else:
                self._inst_speed = max(0.0, getattr(self, "_inst_speed", 0.0) * 0.70)
                if self._inst_speed < 30:
                    self._inst_speed = 0.0
            inst = int(round(self._inst_speed))
        else:
            avg = 0
            inst = 0
        self.s1.setText(f"平均速度：{avg} Pcs/Min")
        self.s2.setText(f"瞬时速度：{inst} Pcs/Min")

    def _refresh_legend(self, data):
        """按剔除口统计饼图右侧图例：剔除口 / 数量 / 比例 三列左对齐（带颜色点）。"""
        grid = self.legend_layout
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        total = sum(v for _, v, _ in data)
        # 表头（三列左对齐）
        hdr = "font-size: 10px; font-weight: bold; color: %s;" % COLORS["text_primary"]
        for c, txt in enumerate(["剔除口", "数量", "比例"]):
            h = QLabel(txt)
            h.setStyleSheet(hdr)
            h.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(h, 0, c + 1)
        # 数据行：颜色点 + 剔除口 + 数量 + 比例，各列左对齐
        for i, (label, value, color) in enumerate(data):
            pct = (value / total * 100) if total else 0
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(dot, i + 1, 0)
            l = QLabel(label)
            l.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            l.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(l, i + 1, 1)
            v = QLabel(str(value))
            v.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            v.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(v, i + 1, 2)
            p = QLabel(f"{pct:.1f}%")
            p.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 11px;")
            p.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(p, i + 1, 3)

    def _build_reject_detail_rows(self, data, stats):
        """由当前「按剔除口统计」环形图与各相机统计，生成详情明细行。

        每行：(相机, 良品率, 总数, 良品数, 不良1数, 不良2数, 重检数)。
        总数 = 良品数 + 不良1数 + 不良2数 + 重检数。
        重检数按「各相机(良品+不良)占全局之比」从环形图 RST（== KPI 重检数）分摊，
        保证「表格重检数之和 == 概览 KPI 重检数」严格一致；不良1/2 数对应 NG1/NG2
        按其在环形图占比分摊到各相机。各相机总数因权重近均匀而基本一致（仅微小偏差）。
        """
        ng1 = ng2 = rst = 0
        for l, v, _ in data:
            if l == "NG1":
                ng1 = v
            elif l == "NG2":
                ng2 = v
            elif l == "RST":
                rst = v
        s = ng1 + ng2
        ng_w = [ng1 / s, ng2 / s] if s > 0 else [0.0, 0.0]
        # 收集各相机的 良品数 / 不良品数，作为重检分摊基数
        cam_infos = []
        for cam in getattr(self.camera_stats_view, "cameras", []):
            cam_data = stats.get(cam)
            if cam_data is None:
                continue
            good = int(cam_data.get("良品数", 0))
            bad = int(cam_data.get("不良品数", 0))
            cam_infos.append((cam, good, bad))
        base = sum(g + b for _, g, b in cam_infos) or 1
        rows = []
        for cam, good, bad in cam_infos:
            rechk = int(round(rst * (good + bad) / base))
            counts = _distribute(bad, ng_w) if bad > 0 else [0, 0]
            ng1_c, ng2_c = counts[0], counts[1]
            total = good + ng1_c + ng2_c + rechk
            rate = f"{good / total * 100:.2f}%" if total else "0.00%"
            row = (
                cam,
                rate,
                str(total),
                str(good),
                str(ng1_c),
                str(ng2_c),
                str(rechk),
            )
            rows.append(row)
        return rows

    def _refresh_reject_detail(self):
        """刷新「详情」页：按相机显示良品率 / 总数 / 良品数 / 不良1数 / 不良2数 / 重检数。"""
        if not hasattr(self, "_reject_detail_view"):
            return
        if self._cleared:
            self._reject_detail_view.set_data([])
            return
        data = self.stat_datasets.get("按剔除口统计", [])
        stats = getattr(self.camera_stats_view, "camera_stats_data", {}) or {}
        rows = self._build_reject_detail_rows(data, stats)
        self._reject_detail_view.set_data(rows)

    def _show_static_example(self):
        """未运行态（未点击「设备启动」）下展示当前时段的静态示例数据，不再自动刷新。

        供「统计清零→恢复示例」「切换时段」「停止播放」等场景复用，保证任一时刻若未处于
        运行态，生产信息都呈现当前时段示例数据且保持静止，绝不在未点击设备启动前自行滚动变化。
        """
        if self._cleared:
            return
        self.kpi_grid.set_values(self._kpi_example)
        if self.stat_mode not in ("按相机统计", "按缺陷项统计"):
            data = self.stat_datasets[self.stat_mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = self._period_yield
            self.donut_chart.update()
            self._refresh_legend(data)
        self.camera_stats_view.set_cleared(False)
        self.defect_stats_view.load_example()
        self._refresh_reject_detail()

    # 统计时段切换：整体替换 KPI、环形图、相机统计与缺陷汇总数据
    def _set_period(self, period):
        if period not in PERIOD_DATA:
            return
        self.period = period
        # 「当前运行」= 实时刷新，切回后自动解冻（恢复按正常示例数据刷新）；
        # 其余检索方式保持既有冻结态，由「检索」按钮点击后再固定显示。
        # 同时退出「返回」模式，按钮复位为「检索」。
        if period == "当前运行":
            self._stat_frozen = False
            self._search_return_mode = False
        self._refresh_search_btn()
        pd = PERIOD_DATA[period]
        self._kpi_example = pd["kpi"]
        self._period_yield = pd["yield"]
        # 重建环形图数据集与示例快照
        self.stat_datasets = {m: [tuple(x) for x in pd["donut"][m]] for m in pd["donut"]}
        self._donut_example = {m: [tuple(x) for x in pd["donut"][m]] for m in pd["donut"]}
        # 回填该时段的默认起止时间（白班/中班/晚班等），阻断信号避免误触发持久化
        start, end = self.period_times.get(period, ("", ""))
        self.d_start.blockSignals(True)
        self.d_end.blockSignals(True)
        self.d_start.setText(start)
        self.d_end.setText(end)
        self.d_start.blockSignals(False)
        self.d_end.blockSignals(False)
        if self._playing:
            # 播放中切换时段 / 检索：累计器始终持续累加（设备仍在生产），绝不在这一刻清零重计。
            # 检索冻结态下 _refresh_live_stats_ui 内部会跳过，保持检索画面不动；
            # 非冻结（当前运行）则继续刷新实时累计，因此切换检索方式不影响下方数据的正常刷新显示。
            # 与 DebugView 镜像口径一致：切换 / 检索都不会触发清零。
            self._refresh_live_stats()
            return
        # 整体替换两个统计视图的数据（静态示例）
        self.camera_stats_view.set_data(pd["camera_stats"], pd["camera_defects"])
        self.defect_stats_view.set_data(pd["camera_defects"])
        if self._cleared:
            # 若处于清零状态，切换时段后继续保持清零
            self.kpi_grid.set_values(
                [(lab, "0.00%" if "%" in val else "0", col)
                 for lab, val, col in self._kpi_example])
            for mode in self.stat_datasets:
                self.stat_datasets[mode] = [
                    (lab, 0, col) for lab, _, col in self.stat_datasets[mode]]
            if self.stat_mode not in ("按相机统计", "按缺陷项统计"):
                data = self.stat_datasets[self.stat_mode]
                self.donut_chart.data = data
                self.donut_chart.center_value = "0.00%"
                self.donut_chart.update()
                self._refresh_legend(data)
            self.camera_stats_view.set_cleared(True)
            self.defect_stats_view.clear_data()
        else:
            self.kpi_grid.set_values(self._kpi_example)
            if self.stat_mode not in ("按相机统计", "按缺陷项统计"):
                data = self.stat_datasets[self.stat_mode]
                self.donut_chart.data = data
                self.donut_chart.center_value = self._period_yield
                self.donut_chart.update()
                self._refresh_legend(data)
            self.camera_stats_view.set_cleared(False)
            self.defect_stats_view.load_example()
        self._refresh_reject_detail()

    # 时间输入框变更：将当前时段的起止时间持久化，下次启动沿用
    def _on_time_edited(self, *_):
        self.period_times[self.period] = (self.d_start.text(), self.d_end.text())
        save_period_times(self.period_times)

    # 统计清零：固定蓝色底、白字，点击后底色不变
    def _style_clear_button(self, btn, active):
        btn.setStyleSheet(_BLUE_BTN_STYLE)

    def _toggle_clear(self):
        if self._playing:
            # 播放运行中：统计清零 = 实时累计归零并继续累计（点击即重置，不切换「恢复示例」语义）
            self._reset_live()
            self._refresh_live_stats()
            self.log_operation(getattr(self, "_op_user", "操作员"), "清零了生产统计")
            return
        self._cleared = not self._cleared
        self._style_clear_button(self._clear_btn, self._cleared)
        self.log_operation(getattr(self, "_op_user", "操作员"),
                           "清零了生产统计" if self._cleared else "恢复了示例数据")
        if self._cleared:
            # 清零：KPI、环形图、相机统计表、缺陷矩阵表 全部置空
            self.kpi_grid.set_values(
                [(lab, "0.00%" if "%" in val else "0", col)
                 for lab, val, col in self._kpi_example])
            for mode in self.stat_datasets:
                self.stat_datasets[mode] = [
                    (lab, 0, col) for lab, _, col in self.stat_datasets[mode]]
            data = self.stat_datasets[self.stat_mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = "0.00%"
            self.donut_chart.update()
            self._refresh_legend(data)
            self.camera_stats_view.set_cleared(True)
            self.defect_stats_view.clear_data()
        else:
            # 恢复示例数据（静态兜底；未运行时随即由待机示例累计覆盖刷新）
            self.kpi_grid.set_values(self._kpi_example)
            for mode in self.stat_datasets:
                self.stat_datasets[mode] = [tuple(x) for x in self._donut_example[mode]]
            data = self.stat_datasets[self.stat_mode]
            self.donut_chart.data = data
            self.donut_chart.center_value = self._period_yield
            self.donut_chart.update()
            self._refresh_legend(data)
            self.camera_stats_view.set_cleared(False)
            self.defect_stats_view.load_example()
        self._refresh_reject_detail()

    # ------------------------------------------------------------------
    # 相机实时帧播放：点击「启动」后 8 路相机画布一帧一帧快速刷新样张，
    # 同时生产统计按当前时段良品率实时累计增长，像真实产线在跑。
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 设备状态卡片「玻璃清洁」按钮
    # ------------------------------------------------------------------
    def _on_glass_clean_clicked(self):
        """点击「玻璃清洁」：先判断高压静电模块是否已断电，未断电则弹窗提示且禁止清洁。"""
        esd = self.dev_cfg.get("hv_esd", {})
        esd_on = bool(esd.get("powered", True))   # 默认视为通电工作中
        if esd_on:
            QMessageBox.information(
                self, "提示", "当前高压静电模块正在通电工作中，请手动关闭")
            return   # 安全：高压静电未断电前不允许清洁玻璃
        # 已断电：可放心清洁
        cfg = self.dev_cfg["dd_motor"]
        cleaning = bool(cfg.get("running", False)) and cfg.get("mode") == "玻璃清洁"
        if cleaning:
            cfg["running"] = False
            self.log_operation(getattr(self, "_op_user", "操作员"), "DD马达：玻璃清洁停止")
        else:
            cfg["mode"] = "玻璃清洁"
            cfg["speed_rpm"] = cfg.get("clean_rpm", 1.0)
            cfg["running"] = True
            self.log_operation(getattr(self, "_op_user", "操作员"), "DD马达：玻璃清洁运行")
            QMessageBox.information(
                self, "提示", "当前高压静电模块已断电停止工作，请放心清洁玻璃")
        self._refresh_glass_clean_btn()
        self.apply_device_settings()   # 同步「旋转盘」目标转速显示

    def _refresh_glass_clean_btn(self):
        """根据当前 DD 马达是否已处于玻璃清洁运行状态，刷新按钮高亮。"""
        cfg = self.dev_cfg["dd_motor"]
        active = bool(cfg.get("running", False)) and cfg.get("mode") == "玻璃清洁"
        self._style_glass_clean_btn(active)
        self._refresh_simulate_btn()

    def _refresh_simulate_btn(self):
        """按生产运行状态刷新「模拟生产」按钮可用性：
        运行中置灰不可点击，停止状态可点击。"""
        btn = getattr(self, "_btn_simulate", None)
        if btn is None:
            return
        btn.setEnabled(not bool(getattr(self, "_playing", False)))
        self._style_simulate_btn()

    def _style_simulate_btn(self):
        """「模拟生产」按钮样式（与「玻璃清洁」同一视觉规格，9px 字号）。

        运行中（禁用）时用次级灰字+ 灰边框，明确表达「不可点击」。
        """
        btn = getattr(self, "_btn_simulate", None)
        if btn is None:
            return
        running = bool(getattr(self, "_playing", False))
        if running:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['text_secondary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"font-size: 9px; padding: 0 5px; }}")
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; "
                f"color: {COLORS['accent_blue']}; "
                f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; "
                f"font-size: 9px; padding: 0 5px; }}"
                f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}; "
                f"color: white; }}")

    def _on_simulate_clicked(self):
        """点击「模拟生产」：打开模拟生产设置窗口（开关 + 各相机图片来源路径）。

        生产运行中禁止进入（按钮已置灰，这里再兜底一次，避免快捷方式绕过）。
        """
        if bool(getattr(self, "_playing", False)):
            QMessageBox.information(
                self, "提示", "设备处于「生产运行中」，请先停止生产再设置模拟生产")
            return
        from nav_dialogs import SimulateProductionDialog
        prev = getattr(self, "_simulate_dlg", None)
        if prev is not None:
            try:
                prev.close()
            except Exception:
                pass
        dlg = SimulateProductionDialog(self)
        dlg.setModal(False)
        self._simulate_dlg = dlg
        dlg.show()

    def _style_glass_clean_btn(self, active):
        btn = self._btn_glass_clean
        # ⚠️ 2026-10-09 需求：字号与检测项操作列的「教导 / 复制 / 删除」一致。
        # 那三个按钮用 `font-size: 9px`（BTN_NEUTRAL），此处原为 10px 偏大。
        if active:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
                f"border: 1px solid {COLORS['accent_orange']}; border-radius: 4px; "
                f"font-size: 9px; padding: 0 5px; }}")
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; color: {COLORS['accent_blue']}; "
                f"border: 1px solid {COLORS['accent_blue']}; border-radius: 4px; "
                f"font-size: 9px; padding: 0 5px; }}"
                f"QPushButton:hover:!disabled {{ background-color: {COLORS['accent_blue']}; color: white; }}"
                f"QPushButton:disabled {{ color: {COLORS['text_secondary']}; border-color: {COLORS['border']}; "
                f"background-color: {COLORS['bg_card']}; }}")

    def start_playback(self):
        """启动相机画布与生产统计实时累计：逐帧快速刷新样张，统计随刷新增长。"""
        _pd("enter start_playback playing=", self._playing)
        if self._playing:
            _pd("early-return: already playing")
            return
        self._playing = True
        self.set_speed_running(True)   # 进入生产运行态：速度开始波动刷新
        self._btn_glass_clean.setEnabled(False)   # 生产运行态下禁用「玻璃清洁」按钮
        self._btn_simulate.setEnabled(False)    # 生产运行态下「模拟生产」置灰不可点击
        self._style_simulate_btn()          # 同步置灰样式
        _pd("set playing=True -> load frames")
        # 进入运行态：停止待机示例累计，改由播放定时器驱动统计
        self._stop_idle_sim()
        # 关键可见刷新优先：先把样张帧装载到各相机。这一步与统计/配置初始化完全解耦，
        # 即便随后的 _reset_live / 设备配置加载等初始化抛出异常，也保证画布立即开始逐帧刷新，
        # 彻底杜绝『点设备启动后画布/统计不动』（此前帧装载与初始化在同一 try 内，初始化
        # 一抛异常帧就装不上，定时器虽起但画布拿到的是空帧、看起来就是没刷新）。
        self._load_frames_to_cams()
        # 诊断：记录各相机装载后的可见性/尺寸/帧数（真机刷新问题定位）
        try:
            _pd("=== start_playback ===")
            for i, cc in enumerate(self.cam_grid.cams):
                sc = getattr(cc, "screen", None)
                n = len(getattr(sc, "_frames", [])) if sc else -1
                _pd("load", i,
                    "vis=", cc.isVisible(),
                    "cam_wh=", cc.width(), cc.height(),
                    "sc_wh=", (sc.width() if sc else -1), (sc.height() if sc else -1),
                    "frames=", n)
        except Exception:
            pass
        # 统计 / 配置初始化（尽力而为，失败不影响画布刷新）
        try:
            if self._cleared:
                # 用户已主动清零：从零起步重新累计
                self._reset_live()
            else:
                # 续跑：保留停机/待机时已累计的示例数据，从停止处继续累计（不清零重计）。
                # 报警/阀体书签与时间基状态仍在本段运行时独立重置。
                self._reset_live(keep_counters=True)
            self.set_vision_online(True, force=True, log=False, remind=False)  # 启动即置为在线（示例演示始终在线）
            self._clear_estop()          # 启动时解除上一次的急停报警状态
            self._schedule_estop_random()  # 本次运行随机安排一次急停（5~60 分钟后，绝大多数演示不会触发）
            # 先累计首批，避免开局环形图空白；随后每节拍推进并联动刷新统计
            self._accumulate_batch()
            self._tick_count = 1
            self._refresh_live_stats()
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            # 无论如何都要启动播放定时器：只要它起来了，相机画布与生产统计就会开始刷新，
            # 避免任何前置异常导致定时器没启动、画布/统计『点了设备启动却不动』。
            self._play_timer.start(30)  # ~33fps 快速换帧

    def _load_frames_to_cams(self):
        """把示例/用户样张帧装载到各相机画布（独立于统计初始化，保证画布必刷新）。

        尺寸优先用预览卡片的固定尺寸（CameraPreview 永远有确定尺寸），再回退到画布实时尺寸；
        这样即便生产界面尚未完成布局（画布实时尺寸暂为 0）也能成功装载样张，
        避免『点设备启动后画布拿到空帧、看起来不刷新』。"""
        for i, cam in enumerate(self.cam_grid.cams):
            try:
                sw, sh = cam.width(), cam.height()
                if sw <= 0 or sh <= 0:
                    sw, sh = cam.screen.width(), cam.screen.height()
                if sw > 0 and sh > 0:
                    if i == ZIGAA_CAM_INDEX:
                        # ZiGAA 品牌展示位：固定显示 ZiGAA 图片，始终显示、不参与逐帧刷新
                        frame = _make_zigaa_pixmap(sw, sh)
                        cam.set_frames([frame])
                        cam.set_frame_index(0)
                    else:
                        name = CAMERA_NAMES[i]
                        img_file = _CAMERA_FRAME_IMAGES.get(name)
                        if img_file:
                            img_path = os.path.join(_camera_frame_dir(), img_file)
                            if os.path.exists(img_path):
                                frames = _make_user_frames(img_path, sw, sh, count=12)
                            else:
                                frames = make_sample_frames(sw, sh, count=12, seed=100 + i)
                        else:
                            frames = make_sample_frames(sw, sh, count=12, seed=100 + i)
                        cam.set_frames(frames)
                        cam.set_frame_index(self._cam_phase[i] % 12)
                    cam.set_playing(True)
            except Exception:
                # 单相机帧生成失败不影响其它相机与整体播放（保证画布/统计仍启动刷新）
                import traceback
                traceback.print_exc()

    def stop_playback(self):
        """停止播放：相机画布冻结在最后一张样张，生产统计回到待机示例模式。"""
        if not self._playing:
            return
        self._playing = False
        self.set_speed_running(False)  # 停止：速度随后逐渐衰减到 0
        self._last_accum_ts = None     # 停止后清掉时间戳：重新启动不带入停机时长
        self._btn_glass_clean.setEnabled(True)   # 停止态恢复「玻璃清洁」按钮可用
        self._btn_simulate.setEnabled(True)     # 停止态恢复「模拟生产」可点击
        self._style_simulate_btn()
        self._play_timer.stop()
        for cam in self.cam_grid.cams:
            cam.set_playing(False)
        # 停机后状态灯显示正常/当前状态（不再整体置灰）
        self._apply_status_style()
        self._stop_idle_sim()
        # 停机后保持最后显示的数据：不清零、不回退静态示例、不再自动刷新。
        # 仅当再次点击「设备启动」后才会继续累计刷新。
        # 注意：报警触发的自动停机**不再**点亮「急停按钮」——急停常态保持「未开启」，
        # 只有极低概率的随机急停事件（_check_estop_random）才会真正触发急停。
        self._estop_due_ts = None

    # ------------------------------------------------------------------
    # 待机示例自动累计：未点击「设备启动」时也持续模拟示例数据，使环形图以
    # 100% 绿色起手、随后按 95~97% 良率 / 0~1% 重检率 实时刷新（良率+重检率+不良率=100%），
    # 供调试界面镜像同一份示例数据（界面切换不影响刷新与显示）。
    # ------------------------------------------------------------------
    def _start_idle_sim(self):
        """启动待机示例自动累计（仅当未运行、未清零时生效）。"""
        if self._playing or self._cleared:
            return
        if not self._idle_timer.isActive():
            self._idle_timer.start(700)   # 待机示例刷新节奏（慢于播放的 30ms）

    def _stop_idle_sim(self):
        if self._idle_timer.isActive():
            self._idle_timer.stop()

    def _on_idle_tick(self):
        # 仅在「未启动 且 未清零」时累计示例数据；运行中由播放定时器驱动、清零时保持零值示例
        if self._playing or self._cleared:
            return
        self._accumulate_batch()
        self._tick_count += 1
        if self._tick_count % self._refresh_every == 0:
            self._refresh_live_stats_ui()

    def set_alarm_stop_callback(self, cb):
        """由 MainWindow 注入：任意料盒/电磁阀达 100% 时回调其 _on_stop 执行自动停机。"""
        self._alarm_stop_cb = cb

    def reset_valve_counts(self, key=None):
        """清除电磁阀已用动作次数并重新计数（不影响寿命阈值）。

        - key=None：全部恢复为初始已用次数（原「清空」行为）；
        - key 为阀键（ok/ng1/ng2/rst）：仅把该阀已用次数清零并重新开始计数
          （「已使用次数清零」按钮调用）。
        """
        if key is None:
            self._valve_used = dict(getattr(self, "_valve_used_init", {}))
        else:
            # 记住清零后的初始值，运行中全量重置时保持已清零状态
            init = getattr(self, "_valve_used_init", None)
            if isinstance(init, dict):
                init[key] = 0.0
        if hasattr(self, "_status_recs"):
            # reset=True：按（已更新的）初始值重算，避免本次刷新又累加一步
            self._update_valve_life(reset=True)

    def get_valve_counts(self):
        """返回各电磁阀当前已用动作次数（次），供报警设置对话框实时显示使用次数。"""
        return dict(getattr(self, "_valve_used", {}))

    def _on_play_tick(self):
        # 诊断：前 6 帧记录 tick/idx/可见性/尺寸，确认定时器真的在驱动重绘
        self._play_diag_n = getattr(self, "_play_diag_n", 0) + 1
        if self._play_diag_n <= 6:
            try:
                cams = self.cam_grid.cams
                c = cams[1] if len(cams) > 1 else (cams[0] if cams else None)
                if c is not None:
                    sc = getattr(c, "screen", None)
                    _pd("tick", self._play_diag_n,
                        "idx=", c.current_frame_index() if hasattr(c, "current_frame_index") else -1,
                        "vis=", c.isVisible(),
                        "sc_vis=", sc.isVisible() if sc else -1,
                        "cam_wh=", c.width(), c.height(),
                        "sc_wh=", (sc.width() if sc else -1), (sc.height() if sc else -1),
                        "frames=", len(getattr(sc, "_frames", [])) if sc else -1,
                        "timer=", self._play_timer.isActive())
            except Exception:
                pass
        # 每路相机按各自步长推进样张帧，形成快速、错落的逐帧刷新
        # （ZiGAA 品牌展示位固定显示、不推进）
        for i, cam in enumerate(self.cam_grid.cams):
            if i == ZIGAA_CAM_INDEX:
                continue
            cam.advance_frame(self._cam_speed[i])
        # 统计清零（_cleared）只在「非播放 / 静态」状态下控制是否显示零值示例；
        # 播放运行中点击清零 = 把实时累计归零并继续累计，因此此处无论 _cleared 与否都持续累计，
        # 绝不会因为清零而停止更新数据。
        self._accumulate_batch()
        self._tick_count += 1
        if self._tick_count % self._refresh_every == 0:
            self._refresh_live_stats()

    # ------------------------------------------------------------------
    # 实时累计：每节拍按当前时段良品率抽取良/不良，分摊到各相机与缺陷项
    # ------------------------------------------------------------------
    def _reset_live(self, keep_counters=False):
        """重置所有实时累计计数器（启动 / 切时段 / 清零 时调用）。

        keep_counters=True 时仅重置报警/阀体书签与时间基状态，保留已累计的生产
        计数（_live_total 等），用于『停止后再次启动』从停机瞬间显示的数据续跑，
        而不是从零重计；keep_counters=False（默认）为原样整体清零。
        """
        if not keep_counters:
            self._live_total = 0
            self._live_good = 0.0
            self._live_bad = 0.0
            self._live_rechk = 0.0
            self._live_cam_good = [0.0] * 8
            self._live_cam_bad = [0.0] * 8
            self._live_cam_rechk = [0.0] * 8
            self._live_defects = {f"相机{i}": {d: 0 for d in _DEFECT_TYPES}
                                  for i in range(1, 9)}
            self._live_yield = 0.0           # 实时良品率（%），来自实时累计
            self._live_rechk_rate = 0.0      # 实时重检率（%），来自实时累计
            # 实时良品率 / 重检率目标：在时段基准附近随机游走（带均值回归），
            # 使累计良品率/重检率围绕基准上下可见地波动，而非恒为固定值。
            _pp = _PERIOD_PROFILE.get(getattr(self, "period", "当前运行"),
                                     _PERIOD_PROFILE["当前运行"])
            self._live_yield_target = _pp[1]
            self._live_rechk_target = _pp[2]
        # 以下书签/状态：每一段运行都独立重置（与是否保留生产计数无关）
        self._tick_count = 0
        # 报警联动：重置料盒累计件数与电磁阀已用动作次数；设备运行状态面板建好后再重绘
        self._alarm_stopped = False
        self._estop_active = False
        self._estop_blink_on = False
        self._bin_alarmed = set()
        # 电磁阀使用寿命报警：记录已触发报警的阀门（每运行周期一次，恢复后解除可重触发）
        self._valve_alarmed = set()
        # 满料报警的「收料百分比阈值」已触发集合（与 100% 满料停机报警独立，恢复后自动解除）
        self._bin_pct_alarmed = set()
        # 满料报警上升穿越判定：记录上一帧各料盒收料百分比，仅在从低于阈值上升穿越时触发
        self._bin_pct_prev = {}
        # 速度 / 良率报警：检测速度模拟当前测量值（与统计「平均速度」同源，示例约 11000 Pcs/Min）
        self._detect_pcs = 11000.0       # 检测速度（Pcs/Min）
        # 时间基累计状态一并归零：下次启动从单节拍起步，不带入停机期间的时间
        self._acc_remain = 0.0
        self._last_accum_ts = None
        self._active_sq_alarms = set()
        # 重置后即时刷新定量生产达成比例（归零或隐藏）
        self._update_achieve()
        # 门打开报警：门状态（开启/关闭）与已报警标记（每次运行重置）
        self._door_open = False
        self._door_alarmed = False
        # 料盒取出状态：每次运行重置为「未取出」（绿底）
        self._bin_taken = {k: False for k in BIN_KEYS}
        # 料盒满料状态：每次运行重置为「未满料」
        self._bin_full = {k: False for k in BIN_KEYS}
        # 料盒取出计时与超时报警标记：每次运行清空
        self._bin_taken_since = {}
        self._bin_taken_timeout_alarmed = set()
        if hasattr(self, "_bin_time_labels"):
            for _n in self._bin_time_labels:
                tl = self._status_recs.get(_n, {}).get("time_lbl")
                if tl is not None:
                    tl.setText("")
                    tl.setVisible(False)
        if hasattr(self, "_bin_state_labels"):
            for _n in self._bin_state_labels:
                self._paint_bin_state(_n)
        # 连续混料 / 连续产品歪斜 / 连续连料：连续计数与报警标记重置
        self._consec_mix_f = 0.0
        self._consec_mix_alarmed = False
        self._consec_tilt_f = 0.0
        self._consec_tilt_alarmed = False
        self._consec_stick_f = 0.0
        self._consec_stick_alarmed = False
        # OK 良品料仓误漏剔除监控：滚动 1 小时窗口内的误踢/漏踢事件时间戳（每次运行重置）
        self._mis_wrong_events = []
        self._mis_miss_events = []
        self._mis_alarm_logged = False   # 报警模式下是否已记过一次，避免每帧刷屏
        # 设备运行状态区展示的误踢/漏踢频率示例值（Pcs/H），运行期间小幅波动
        self._mis_wrong_rate = 12.0
        self._mis_miss_rate = 8.0
        # 设备运行状态四类实时测量行：示例值在正常范围内波动，偶尔越界以演示报警
        self._dev_readings = {
            "总气源": {"val": 0.62, "lo": 0.30, "hi": 0.80, "unit": "MPa", "fmt": "{:.2f}",
                       "out_since": None, "fired_at": None, "active": False, "_alarmed": False,
                       "live_color": COLORS["accent_green"]},
            "旋转盘": {"val": 15.0, "lo": None, "hi": None, "unit": "RPM", "fmt": "{:.1f}",
                       "out_since": None, "fired_at": None, "active": False, "_alarmed": False,
                       "live_color": COLORS["accent_green"]},
            "负压":  {"val": 0.10, "lo": 0.05, "hi": 0.15, "unit": "MPa", "fmt": "{:.2f}",
                      "out_since": None, "fired_at": None, "active": False, "_alarmed": False,
                      "live_color": COLORS["accent_green"]},
            "静电":  {"val": 2.8, "lo": 2.5, "hi": 3.2, "unit": "KV", "fmt": "{:.1f}",
                      "out_since": None, "fired_at": None, "active": False, "_alarmed": False,
                      "live_color": COLORS["accent_green"]},
        }
        # 设备参数配置（由「设备设置 / 触发设定 / 剔除设定」窗口实时驱动模拟数据）
        self.dev_cfg = {
            "dd_motor": {"speed_rpm": 21.0, "jog_rpm": 5.0,
                         "prod_rpm": 21.0, "clean_rpm": 1.0,
                         "mode": "生产运行",                          # 默认工作模式：生产运行
                         "running": False, "direction": 1,         # 驱动「旋转盘」目标转速 + 运行/方向状态
                         "init_freq_pulse": 100, "interval_ms": 50, "accum_pulse": 10},  # 高级参数
            "vibrator": {"feed_rate": 12000,                              # 单位 Pcs/Min，映射 _products_per_tick
                         "round_voltage": 80.0, "round_running": False,   # 圆振电压/运行态
                         "line_voltage": 68.0, "line_running": False},    # 直振电压/运行态
            "hv_esd":   {"voltage_kv": 2.8, "lo": 2.5, "hi": 3.2,
                         "powered": True},  # 高压静电模块是否通电工作中（玻璃清洁前需先断电）
            "neg_press": {"pressure_mpa": 0.10, "lo": 0.05, "hi": 0.15},  # 驱动「负压」目标值与报警范围
            # 触发设定：8 路相机独立配置（采图使能 / 触发位置 Pulse / 触发光源 1-18）
            "trigger":  {
                "light_names": [f"光源{i + 1}" for i in range(18)],  # 18 通道名称（可编辑、跨相机共享）
                "light_values": [255 for _ in range(18)],           # 18 通道亮度值（默认 255，跨相机共享）
                "input_filter": 5000,     # 触发高级参数（全局）：输入滤波，单位 μs
                "trigger_response": 5,    # 触发高级参数（全局）：触发应答，单位 ms
                **{f"相机{i + 1}": {"enable": True, "position": 5112 + i * 1000, "lights": [True] * 18,
                                    "multi_enable": False, "multi_count": 2, "multi_delay": 100,
                                    "exposure_gain": 16, "exposure_time": 2000,
                                    "min_match": 50, "max_match": 90}
                   for i in range(8)},
            },
            "reject":   {
                "offline_port": "rst",    # 软件脱机/超时剔除口（默认 RST）
                "default_unchecked_port": "rst",  # 默认未检状态剔除口（默认 RST）
                "default_ok_port": 1,     # 默认 OK 剔除口编号（1-4）
                "default_pending_port": 4,  # 默认待定剔除口编号（1-4）
                "default_ng_port": 2,     # 默认 NG 剔除口编号（1-4）
                "ports": {
                    "ok":  {"enable": True, "position": 4000, "priority": 4, "blow_time": 200},
                    "ng1": {"enable": True, "position": 1000, "priority": 1, "blow_time": 200},
                    "ng2": {"enable": True, "position": 2000, "priority": 2, "blow_time": 200},
                    "rst": {"enable": True, "position": 3000, "priority": 3, "blow_time": 200},
                },
            },
        }
        # 启动时加载已持久化的设备参数（device_config.json），重启后仍保留上次保存值
        self._load_device_config()
        # 供料速度（Pcs/Min）→ 每节拍产品数：构造时即按配置折算，保证与「设备设置」一致
        self._sync_products_per_tick()
        if hasattr(self, "_status_recs"):
            self._update_valve_life(reset=True)
            self._update_bin_life(reset=True)
            self._clear_estop()          # 重置时同步解除急停面板红/闪烁
            self._estop_due_ts = None    # 取消本次运行已安排的随机急停时刻
        else:
            self._valve_used = dict(getattr(self, "_valve_used_init", {}))
            self._bin_count = dict(getattr(self, "_bin_count_init", {}))

    def _accumulate_batch(self):
        """按当前时段良品率/重检率，模拟一批产品经过产线并累计到各计数器。

        每批产品按总数 N 拆分：良品数 ~ Binomial(N, 良率)、重检数 = N×重检率、
        其余为不良，使 总数=良品+不良+重检、良率+不良率+重检率=100%。
        良品率约束在 95~97%、重检率约束在 0~1% 内做带均值回归的随机游走，
        使累计良率/重检率围绕基准可见地波动（而非恒为固定值）。缺陷项按权重
        分摊到 相机×缺陷 矩阵。
        """
        # 实时良品率目标随机游走（约束在 95.5~96.5%，保证显示值在 95~97% 内波动）
        base_y = _PERIOD_PROFILE[self.period][1]
        tgt_y = getattr(self, "_live_yield_target", base_y)
        tgt_y = tgt_y + random.uniform(-0.5, 0.5) + (base_y - tgt_y) * 0.05
        tgt_y = max(95.5, min(96.5, tgt_y))
        self._live_yield_target = tgt_y

        # 实时重检率目标随机游走（约束在 0~1%）
        base_r = _PERIOD_PROFILE[self.period][2]
        tgt_r = getattr(self, "_live_rechk_target", base_r)
        tgt_r = tgt_r + random.uniform(-0.08, 0.08) + (base_r - tgt_r) * 0.05
        tgt_r = max(0.0, min(1.0, tgt_r))
        self._live_rechk_target = tgt_r

        if self._playing:
            # 播放态：按「真实流逝时间 × 当前显示的平均速度」累计本批件数。
            # 定时器实际触发间隔受系统调度影响略长于 30ms，固定每节拍件数会使
            # 一分钟内的总数差值低于统计卡片显示的平均速度；改为时间基累计后，
            # 一分钟差值 = 平均速度（约 11000 Pcs/Min），两处口径严格一致。
            now = time.monotonic()
            dt = (_PLAY_TICK_SECONDS if self._last_accum_ts is None
                  else min(now - self._last_accum_ts, 1.0))
            self._last_accum_ts = now
            n_exact = (getattr(self, "_avg_speed", 0.0) / 60.0 * dt
                       + self._acc_remain)
            n = int(n_exact)
            self._acc_remain = n_exact - n
            if n < 1:
                return
        else:
            # 待机示例：保持原「每节拍固定件数」的慢速累计（未启动时的演示节奏）
            n = self._products_per_tick
        # 本批良品概率：以目标良率 p 抽样，并按「已累计良率 - 目标」做比例反馈修正。
        # 小样本下纯随机抽样会把显示良率推出 95~97%（例如开局 20 件恰好全良即 100%），
        # 加入反馈后累计良率会稳定贴在目标附近，且仍保持逐件随机、数值可见地小幅波动。
        p = tgt_y / 100.0
        if self._live_total > 0:
            cur = self._live_good / self._live_total
            p = max(0.0, min(1.0, p + (tgt_y / 100.0 - cur) * _YIELD_FEEDBACK))
        g = 0.0
        for _ in range(n):
            if random.random() < p:
                g += 1
        r = n * tgt_r / 100.0          # 重检数（占总数 tgt_r%）
        b = float(n) - g - r           # 不良 = 总数 - 良品 - 重检
        # 料盒抽出超时未放回 → 按「高级设置 → 料盒抽出超时未放回的剔除逻辑」改判为「待定」：
        #   · 对应抽出料盒走待定（默认）：只把「抽出的那个料盒」应得的产品改判为待定；
        #   · 全部料盒走待定：本批全部产品改判为待定。
        # 「待定」计入重检数（与生产报表「数据统计 → 待定」口径一致），良品率随之下降。
        moved = self._pending_move_count(n, g, b, r)
        if moved > 0:
            g = max(0.0, g - moved * (g / n))
            b = max(0.0, b - moved * (b / n))
            r = r + moved
        self._live_total += n
        self._live_good += g
        self._live_bad += b
        self._live_rechk += r
        # 每批产品按相机权重拆分到 8 路相机：各相机 总数=良品+不良+重检，
        # 与全局口径一致，KPI / 按相机统计 / 详情表 完全一致。
        weights = [_CAM_WEIGHTS[f"相机{i}"] for i in range(1, 9)]
        # 浮点拆分并浮点累计：避免每批整数取整（n=20 时每相机增量<1 被四舍五入抹零，
        # 导致各相机总数长期固化在 2/3 的二值偏差、缺陷累计恒为 0），保证各相机总数基本一致、
        # 缺陷随运行平滑累计（仅在展示时四舍五入），从而「按缺陷项统计」饼图/详情可见地刷新。
        cam_total = _distribute_f(n, weights)      # 各相机总数和=全局总数
        cam_bad = _distribute_f(b, weights)        # 各相机不良和=全局不良（b 为浮点，用浮点拆分）
        cam_rechk = _distribute_f(r, weights)      # 各相机重检和=全局重检
        for i in range(8):
            crechk = max(0.0, cam_rechk[i])
            cbad = max(0.0, cam_bad[i])
            cgood = max(0.0, cam_total[i] - cbad - crechk)
            self._live_cam_good[i] += cgood
            self._live_cam_bad[i] += cbad
            self._live_cam_rechk[i] += crechk
        # 缺陷按「缺陷基准权重 × 相机权重」分摊到 相机×缺陷 矩阵（浮点累计，展示时四舍五入）
        sum_w = sum(weights) or 1
        sum_base = sum(_DEFECT_BASE.values()) or 1
        for ci, cam in enumerate([f"相机{i}" for i in range(1, 9)]):
            for d in _DEFECT_TYPES:
                share = _DEFECT_BASE[d] / sum_base * weights[ci] / sum_w
                self._live_defects[cam][d] += b * share

    def _taken_timeout_bins(self):
        """当前处于「取出未放回超时」状态的料盒键列表（与报警判定同一口径）。"""
        thr = bin_taken_timeout_ms()
        now = time.monotonic() * 1000.0
        out = []
        for k in BIN_KEYS:
            if not self._bin_taken.get(k, False):
                continue
            since = self._bin_taken_since.get(k)
            if since is not None and (now - since) >= thr:
                out.append(k)
        return out

    def _bin_taken_reject_mode(self):
        """读取「料盒抽出超时未放回的剔除逻辑」（来自高级设置，持久化于用户配置）。"""
        um = getattr(self, "user_manager", None)
        getter = getattr(um, "get_bin_taken_reject_mode", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
        return "对应抽出料盒走待定"

    def _pending_move_count(self, n, g, b, r):
        """本批产品中应改判为「待定」的件数（0 = 无需改判）。

        - 未运行 / 没有料盒处于取出超时状态 → 0；
        - 「全部料盒走待定」→ 本批全部 n 件；
        - 「对应抽出料盒走待定」（默认）→ 仅抽出料盒应得的那部分：
          OK=良品、NG1=不良×70%、NG2=不良×30%、RST=重检（与剔除口分摊口径一致）。
        """
        if not getattr(self, "_playing", False):
            return 0.0
        bins = self._taken_timeout_bins()
        if not bins:
            self._pending_routed = set()
            return 0.0
        mode = self._bin_taken_reject_mode()
        # 记录一次剔除逻辑日志（进入该状态时记一条即可）
        routed = getattr(self, "_pending_routed", None)
        if routed is None:
            routed = self._pending_routed = set()
        new_bins = [k for k in bins if k not in routed]
        if new_bins and n > 0:
            lv = getattr(self, "_log_view", None)
            if lv is not None and hasattr(lv, "add"):
                ts = datetime.now().strftime("%H:%M:%S")
                lv.add(ts,
                       f"【剔除逻辑】{('、'.join(k + ' 料盒' for k in new_bins))}"
                       f"取出超时未放回，按「{mode}」将相关产品改判为待定",
                       COLORS["accent_orange"])
            routed.update(new_bins)
        if mode == "全部料盒走待定":
            return float(n)
        share = 0.0
        if n > 0:
            # 各料盒应得的产品占比（合计≈100%）
            per = {"OK": g / n, "NG1": 0.7 * b / n, "NG2": 0.3 * b / n, "RST": r / n}
            for k in bins:
                share += per.get(k, 0.0)
        return max(0.0, min(float(n), n * share))

    def _check_ion_fan_alarm(self):
        """离子风扇异常报警（默认开启，可在「报警设备 → 其他报警功能」中关闭并选报警方案）。

        演示用：运行中以极低概率出现离子风扇异常（风速偏低），按所选报警方案记录红色报警
        日志并蜂鸣；恢复正常后记一条恢复日志，可再次触发。**不触发停机**。
        """
        if not getattr(self, "_playing", False) or not feature_ion_fan_alarm():
            return
        lv = getattr(self, "_log_view", None)
        if getattr(self, "_ion_fan_abnormal", False):
            if random.random() < 0.15:      # 异常态：以一定概率恢复
                self._ion_fan_abnormal = False
                if lv is not None and hasattr(lv, "add"):
                    lv.add(datetime.now().strftime("%H:%M:%S"),
                           "【离子风扇】异常已恢复，风扇工作正常",
                           COLORS["accent_green"])
            return
        if random.random() >= _ION_FAN_TRIGGER_P:   # ≈ 每 1 分钟出现一次异常（演示节奏）
            return
        self._ion_fan_abnormal = True
        plan = state_plan_by_alias(ion_fan_plan())
        plan_name = (plan.get("alias") if plan else None) or ion_fan_plan() or "方案 1"
        if lv is not None and hasattr(lv, "add"):
            lv.add(datetime.now().strftime("%H:%M:%S"),
                   f"报警：【离子风扇】离子风扇异常（风速偏低）【报警方案：{plan_name}】",
                   COLORS["accent_red"])
        self._beep()

    def _build_live_camera_stats(self):
        """由实时计数器组装「按相机统计」视图所需的数据字典。

        每相机 总数=良品数+不良品数+重检数，重检数按相机权重分摊（与全局口径一致），
        保证「按相机统计」「按剔除口统计」详情表 与 KPI 三处口径完全一致。
        """
        out = {}
        for i in range(8):
            cam = f"相机{i + 1}"
            good = int(round(self._live_cam_good[i]))
            bad = int(round(self._live_cam_bad[i]))
            rechk = int(round(self._live_cam_rechk[i]))
            total = good + bad + rechk
            out[cam] = {
                "总数": str(total),
                "良品数": str(good),
                "不良品数": str(bad),
                "重检数": str(rechk),
                "良率": f"{good / total * 100:.2f}%" if total else "0.00%",
                "重检率": f"{rechk / total * 100:.2f}%" if total else "0.00%",
            }
        return out

    def _build_live_defects(self):
        """由实时计数器组装「按缺陷项统计 / 相机缺陷」视图所需数据。

        按全局不良品总数一次性拆分给「相机×缺陷」矩阵，保证所有缺陷项整数之和
        严格等于 KPI 不良品总数；各相机内部再按缺陷项占比归一化显示比例。
        """
        total_bad = int(round(self._live_bad))
        weights = []
        keys = []
        for cam in [f"相机{i}" for i in range(1, 9)]:
            for d in _DEFECT_TYPES:
                keys.append((cam, d))
                weights.append(self._live_defects[cam][d])
        dist = _distribute(total_bad, weights)
        out = {}
        idx = 0
        for cam in [f"相机{i}" for i in range(1, 9)]:
            cam_items = []
            cam_total = 0
            for d in _DEFECT_TYPES:
                q = dist[idx]
                cam_items.append((d, q))
                cam_total += q
                idx += 1
            s = cam_total or 1
            out[cam] = [(d, str(q), f"{q / s * 100:.2f}%")
                        for d, q in cam_items]
        return out

    def _refresh_live_stats_ui(self):
        """只刷新统计类 UI（KPI / 环形图 / 相机统计 / 缺陷统计 / 详情），不触碰报警与设备状态。

        供播放中（_refresh_live_stats 内部调用）与待机示例自动累计（_on_idle_tick）共用，
        保证「未启动」与「运行中」看到的生产统计口径完全一致、且供调试界面镜像同一份数据。

        注意：点「检索」后 _stat_frozen=True（统计固定显示），此时直接跳过，
        保持检索时刻的画面不动；切回「当前运行」由 _set_period 解冻后自动恢复刷新。
        """
        if getattr(self, "_stat_frozen", False):
            return
        total = self._live_total
        good = int(round(self._live_good))
        rechk = int(round(self._live_rechk))
        # 定量生产达成比例随实时良品数刷新（标题栏同「生产信息」一行显示）
        self._update_achieve()
        # 不良 = 总数 - 良品 - 重检（由精确全局计数器推导，保证 良率+不良率+重检率=100%）
        bad = total - good - rechk
        yld = (good / total * 100) if total else 0.0
        bad_rate = (bad / total * 100) if total else 0.0
        rechk_rate = (rechk / total * 100) if total else 0.0
        self._live_yield = yld
        self._live_rechk_rate = rechk_rate
        kpi = [
            ("总数", str(total), COLORS["text_primary"]),
            ("良品数", str(good), COLORS["accent_green"]),
            ("不良品数", str(bad), COLORS["accent_red"]),
            ("重检数", str(rechk), COLORS["accent_yellow"]),
            ("良品率", f"{yld:.2f}%", COLORS["accent_green"]),
            ("不良率", f"{bad_rate:.2f}%", COLORS["accent_red"]),
            ("重检率", f"{rechk_rate:.2f}%", COLORS["accent_yellow"]),
        ]
        self.kpi_grid.set_values(kpi)
        # 环形图（按剔除口统计）：OK=良品数；不良在 NG1/NG2 间按 280/120 分摊；
        # RST=重检数（与 KPI 重检数一致），保证 良率+不良率+重检率=100%。
        ng1 = int(round(bad * 280 / 400)) if bad else 0
        ng2 = bad - ng1
        rst = rechk
        self.stat_datasets["按剔除口统计"] = [
            ("OK", good, "#0D822B"), ("NG1", ng1, "#C81435"),
            ("NG2", ng2, "#FF8A80"), ("RST", rst, "#F9AA0B")]
        # 未启动（total==0）时中心显示 100.00%（全绿）；否则显示实时良品率
        self.donut_chart.center_value = "100.00%" if total == 0 else f"{yld:.2f}%"
        if self.stat_mode == "按剔除口统计":
            self.donut_chart.data = self.stat_datasets["按剔除口统计"]
            self.donut_chart.update()
            self._refresh_legend(self.stat_datasets["按剔除口统计"])
        # 相机统计与缺陷统计视图随实时数据联动
        cam_stats = self._build_live_camera_stats()
        cam_def = self._build_live_defects()
        self.camera_stats_view.set_data(cam_stats, cam_def)
        self.defect_stats_view.set_data(cam_def)
        self._refresh_reject_detail()

    def _refresh_live_stats(self):
        """把实时累计值刷新到统计 UI，并联动设备状态、报警、定量停机等运行逻辑。"""
        # 统计类 UI 刷新（播放与待机共用同一套口径）
        self._refresh_live_stats_ui()
        # 设备运行状态中的 OK/NG1/NG2/RST 四个料盒满料百分比随运行实时递增
        self._update_bin_life()
        # 电磁阀寿命百分比随运行实时递增（已用动作次数 / 寿命阈值）
        self._update_valve_life()
        # 报警联动：任意一个料盒/电磁阀达 100% 自动停机并记日志
        self._check_alarm_stop()
        # 定量生产：良品数或 OK 料盒数达到设定目标自动停机
        self._check_quant_target()
        # 设备运行状态区：OK 料仓误踢/漏踢频率示例值实时波动
        self._update_mis_freq_display()
        # OK 良品料仓误漏剔除监控：1 小时内误踢/漏踢超阈值则按触发方式报警或停机
        # （演示用：监控开启时按 ~Pcs/H 量级随机产生误踢/漏踢事件，阈值调低可快速验证）
        if feature_mis_wrong() and random.random() < 0.0004:
            self._record_mis_reject("wrong")
        if feature_mis_miss() and random.random() < 0.00025:
            self._record_mis_reject("miss")
        self._check_mis_reject()
        # 速度 / 良率报警：检测速度实时模拟、四类设备状态实时测量（越界记日志，不触发停机）
        self._update_device_status_live()
        self._check_speed_quality_alarms()
        # 门打开报警：功能开启且门打开则按触发方式报警或停机（默认报警）
        self._update_door_status()
        # 料盒取出未放回超时报警：随机切换取出态 + 实时计时 + 超阈值变红/报警
        self._update_bin_taken_status()
        # 连续混料 / 连续产品歪斜 / 连续连料 报警
        self._check_consecutive_alarms()
        # 离子风扇异常报警（默认开启；按所选报警方案记日志，不触发停机）
        self._check_ion_fan_alarm()
        # 急停按钮：极低概率的随机「按下急停」（5~60 分钟后才可能触发）
        self._check_estop_random()

    # ------------------------------------------------------------------
    # 运行日志
    # ------------------------------------------------------------------
    def set_current_user(self, name, username=None):
        """记录当前登录用户（用于运行日志操作人标识），并将「负责人」同步为当前登录用户名。"""
        self._op_user = name or "操作员"
        owner = username or name or ""
        # 负责人始终跟随当前登录用户：初始填入，登录用户变更时自动同步更新
        if getattr(self, "owner_edit", None) is not None:
            self.owner_edit.setText(owner)

    # ------------------------------------------------------------------
    # 共享统计接口：供调试界面（及任意需要同步生产统计的界面）镜像同一份实时数据，
    # 保证「生产运行界面」与「调试界面」看到的生产统计数据完全一致、切换不影响统计。
    # ------------------------------------------------------------------
    def set_period(self, period):
        """对外暴露的统计时段切换入口（调试界面镜像模式下委托调用）。"""
        self._set_period(period)
        # 同步更新生产运行界面自身的时段下拉框，保持两界面控件状态一致
        if getattr(self, "period_cb", None) is not None:
            self.period_cb.blockSignals(True)
            self.period_cb.setCurrentText(period)
            self.period_cb.blockSignals(False)

    def toggle_clear_mirror(self):
        """调试界面镜像模式下，把统计清零委托给生产运行界面统一处理。"""
        self._toggle_clear()

    def get_live_snapshot(self):
        """返回当前实时累计的「生产统计」快照，供调试界面等共享显示。"""
        total = self._live_total
        good = int(round(self._live_good))
        rechk = int(round(self._live_rechk))
        # 不良 = 总数 - 良品 - 重检（保证 良率+不良率+重检率=100%）
        bad = total - good - rechk
        yld = (good / total * 100) if total else 0.0
        bad_rate = (bad / total * 100) if total else 0.0
        rechk_rate_v = (rechk / total * 100) if total else 0.0
        kpi = [
            ("总数", str(total), COLORS["text_primary"]),
            ("良品数", str(good), COLORS["accent_green"]),
            ("不良品数", str(bad), COLORS["accent_red"]),
            ("重检数", str(rechk), COLORS["accent_yellow"]),
            ("良品率", f"{yld:.2f}%", COLORS["accent_green"]),
            ("不良率", f"{bad_rate:.2f}%", COLORS["accent_red"]),
            ("重检率", f"{rechk_rate_v:.2f}%", COLORS["accent_yellow"]),
        ]
        ng1 = int(round(bad * 280 / 400)) if bad else 0
        ng2 = bad - ng1
        rst = rechk
        donut = [("OK", good, "#0D822B"), ("NG1", ng1, "#C81435"),
                 ("NG2", ng2, "#FF8A80"), ("RST", rst, "#F9AA0B")]
        cam_stats = self._build_live_camera_stats()
        cam_def = self._build_live_defects()
        return {"kpi": kpi, "donut": donut, "camera_stats": cam_stats,
                "defect_stats": cam_def,
                "period_yield": "100.00%" if total == 0 else f"{yld:.2f}%",
                "rechk_rate": rechk_rate_v}

    def get_display_snapshot(self):
        """返回当前生产运行界面『正在显示』的生产统计快照，供调试界面镜像复用。

        - 统计清零态：界面全部为 0；
        - 运行中 / 停止后冻结：界面显示实时累计快照（停止后冻结在最后累计值，不回退示例，
          故与生产运行界面「停止保持最后数据」行为一致）；
        - 待机（从未启动 / 已复位）：界面显示当前时段静态示例数据（与 _set_period 完全一致）。
        这样无论生产运行界面处于哪种状态，调试界面镜像看到的 KPI、环形图、按相机/按缺陷项
        统计、剔除详情都与之严格一致，切换界面不影响生产信息。
        """
        if self._cleared:
            pd = PERIOD_DATA[self.period]
            kpi = [(lab, "0.00%" if "%" in val else "0", col)
                   for lab, val, col in pd["kpi"]]
            donut = [(lab, 0, col) for lab, _, col in pd["donut"]["按剔除口统计"]]
            cam_stats = {
                cam: {k: ("0.00%" if "%" in str(v) else "0")
                      for k, v in pd["camera_stats"][cam].items()}
                for cam in pd["camera_stats"]
            }
            cam_def = {
                cam: [(d, "0", "0.00%") for d, _, _ in pd["camera_defects"][cam]]
                for cam in pd["camera_defects"]
            }
            period_yield = "0.00%"
            rechk_rate = 0.0
        elif getattr(self, "_stat_frozen", False):
            # 点「检索」后固定显示：镜像当前检索方式的静态示例数据（不随时间刷新），
            # 与生产运行界面「检索后统计数据固定显示」的表现严格一致。
            pd = PERIOD_DATA[self.period]
            kpi = pd["kpi"]
            donut = [tuple(x) for x in pd["donut"]["按剔除口统计"]]
            cam_stats = pd["camera_stats"]
            cam_def = pd["camera_defects"]
            period_yield = pd["yield"]
            try:
                rechk_rate = float(
                    str([v for l, v, _ in pd["kpi"] if l == "重检率"][0]).rstrip("%"))
            except Exception:
                rechk_rate = 0.0
        elif self._playing or self._live_total > 0:
            # 运行中或停止后冻结：返回实时累计快照（停止后计数器未复位，冻结在最后累计值）
            return self.get_live_snapshot()
        else:
            # 待机：返回当前时段静态示例数据
            pd = PERIOD_DATA[self.period]
            kpi = pd["kpi"]
            donut = [tuple(x) for x in pd["donut"]["按剔除口统计"]]
            cam_stats = pd["camera_stats"]
            cam_def = pd["camera_defects"]
            period_yield = pd["yield"]
            try:
                rechk_rate = float(
                    str([v for l, v, _ in pd["kpi"] if l == "重检率"][0]).rstrip("%"))
            except Exception:
                rechk_rate = 0.0
        return {"kpi": kpi, "donut": donut, "camera_stats": cam_stats,
                "defect_stats": cam_def, "period_yield": period_yield,
                "rechk_rate": rechk_rate}

    def log_operation(self, actor, action):
        """向运行日志追加一条操作记录：『操作人 执行了某操作』（蓝色，区别于报警/恢复）。"""
        if not hasattr(self, "_op_logs"):
            self._op_logs = []
        ts = datetime.now().strftime("%H:%M:%S")
        self._op_logs.append((ts, actor, action))
        lv = getattr(self, "_log_view", None)
        if lv is None or not hasattr(lv, "add"):
            return
        lv.add(ts, f"操作记录：{actor} {action}", "#2F80ED")

    def get_operation_logs(self):
        """返回运行操作日志列表（元素为 (时间, 操作人, 动作) 元组），供「日志管理」查看。"""
        return list(getattr(self, "_op_logs", []))

    def get_bin_status(self):
        """返回四个料盒当前状态：{key: {count, capacity, pct, full}}，供「盒子监控」实时展示。"""
        out = {}
        for key in BIN_KEYS:
            cnt = self._bin_count.get(key, 0)
            thr = bin_full_threshold(key)
            pct = min(100.0, cnt / thr * 100) if thr else 0.0
            out[key] = {
                "count": cnt,
                "capacity": thr,
                "pct": pct,
                "full": bool(self._bin_full.get(key, False)),
            }
        return out

    # ------------------------------------------------------------------
    # 设备参数配置（「设备设置 / 触发设定 / 剔除设定」窗口实时驱动模拟数据）
    # ------------------------------------------------------------------
    def _device_config_path(self):
        """设备参数落盘路径：优先跟随可执行文件所在目录，否则脚本目录。"""
        if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "device_config.json")

    def _load_device_config(self):
        """启动时加载设备参数：文件不存在或解析失败则回退到代码默认值。"""
        p = self._device_config_path()
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return

        def _merge(base, override):
            """深度合并：dict 递归合并（保留新增键），其余类型直接覆盖。
            用于兼容旧配置文件——新增的相机参数键能自动补齐默认值。"""
            if isinstance(base, dict) and isinstance(override, dict):
                for k, v in override.items():
                    base[k] = _merge(base[k], v) if k in base else v
                return base
            return override

        for top in ("dd_motor", "vibrator", "hv_esd", "neg_press", "trigger", "reject"):
            saved = data.get(top)
            if isinstance(saved, dict):
                _merge(self.dev_cfg[top], saved)

    def save_device_config(self):
        """把当前 dev_cfg（含 DD马达高级参数）写回 device_config.json，重启后保留。"""
        p = self._device_config_path()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.dev_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def apply_device_settings(self):
        """将 dev_cfg 推入实时模拟：静电/负压目标值与报警范围、旋转盘目标转速、供料速度。"""
        rd = getattr(self, "_dev_readings", {})
        if "静电" in rd:
            rd["静电"]["val"] = self.dev_cfg["hv_esd"]["voltage_kv"]
            rd["静电"]["lo"] = self.dev_cfg["hv_esd"]["lo"]
            rd["静电"]["hi"] = self.dev_cfg["hv_esd"]["hi"]
        if "负压" in rd:
            rd["负压"]["val"] = self.dev_cfg["neg_press"]["pressure_mpa"]
            rd["负压"]["lo"] = self.dev_cfg["neg_press"]["lo"]
            rd["负压"]["hi"] = self.dev_cfg["neg_press"]["hi"]
        if "旋转盘" in rd:
            rd["旋转盘"]["val"] = self.dev_cfg["dd_motor"]["speed_rpm"]
        feed = self.dev_cfg["vibrator"]["feed_rate"]
        self._sync_products_per_tick(feed)
        self._refresh_dev_display()

    def _sync_products_per_tick(self, feed=None):
        """按「供料速度（Pcs/Min）」折算每个播放节拍模拟经过的产品数。

        例：12000 Pcs/Min → 200 Pcs/s → 每 30ms 节拍约 6 件。
        该折算用于「待机示例」的慢速累计；播放运行态改为时间基累计
        （真实流逝时间 × 显示平均速度，见 _accumulate_batch），保证一分钟差值
        与统计卡片的平均速度一致。
        """
        if feed is None:
            feed = self.dev_cfg["vibrator"]["feed_rate"]
        try:
            feed = float(feed)
        except Exception:
            return
        if feed > 0:
            self._products_per_tick = int(max(1, round(feed / 60.0 * _PLAY_TICK_SECONDS)))

    def _refresh_dev_display(self):
        """将 dev_cfg 当前值刷新到设备运行状态区（停止态也同步显示配置值）。"""
        rd = getattr(self, "_dev_readings", {})
        for name, info in rd.items():
            rec = self._status_recs.get(name)
            if rec is not None:
                rec["val_box"].setText(info["fmt"].format(info["val"]))

    def get_current_pulse_position(self, offset=0):
        """「自动获取」当前位置（演示）：按旋转盘转速与运行节拍模拟编码器脉冲累计值。

        - offset：多工位/多剔除口取位时的相位偏移（Pulse），保证各口取到不同位置。
        """
        rpm = float(self.dev_cfg.get("dd_motor", {}).get("prod_rpm", 21.0) or 0.0)
        ticks = int(getattr(self, "_tick_count", 0))
        base = 5112
        pos = (base + ticks * max(1, int(round(rpm))) * 3 + int(offset) * 137) % 100000
        return int(pos)

    def get_trigger_config(self):
        cfg = {}
        for k, v in self.dev_cfg["trigger"].items():
            if isinstance(v, dict):
                cfg[k] = dict(v)
            elif isinstance(v, list):
                cfg[k] = list(v)
            else:
                cfg[k] = v
        return cfg

    def set_trigger_config(self, name, enable=None, position=None, lights=None,
                           multi_enable=None, multi_count=None, multi_delay=None,
                           exposure_gain=None, exposure_time=None,
                           min_match=None, max_match=None):
        cfg = self.dev_cfg["trigger"].get(name)
        if cfg is None:
            return
        if enable is not None:
            cfg["enable"] = bool(enable)
        if position is not None:
            cfg["position"] = int(position)
        if lights is not None:
            cfg["lights"] = [bool(x) for x in lights[:18]] + [False] * (18 - len(lights))
        if multi_enable is not None:
            cfg["multi_enable"] = bool(multi_enable)
        if multi_count is not None:
            cfg["multi_count"] = int(multi_count)
        if multi_delay is not None:
            cfg["multi_delay"] = int(multi_delay)
        # 相机参数（曝光增益 / 曝光时间 / 最小匹配 / 最大匹配，每相机独立）
        if exposure_gain is not None:
            cfg["exposure_gain"] = int(exposure_gain)
        if exposure_time is not None:
            cfg["exposure_time"] = int(exposure_time)
        if min_match is not None:
            cfg["min_match"] = int(min_match)
        if max_match is not None:
            cfg["max_match"] = int(max_match)

    def get_reject_config(self):
        return dict(self.dev_cfg["reject"])

    def set_reject_config(self, **kw):
        self.dev_cfg["reject"].update(kw)

    def _build_log(self):
        logs = [
            ("09:42:12", "通讯心跳正常", COLORS["accent_green"]),
            ("09:41:30", "检测节拍 38ms / 件", COLORS["text_secondary"]),
            ("09:40:48", "料盘更换完成", COLORS["text_secondary"]),
            ("09:40:05", "电磁阀 2 动作正常", COLORS["accent_green"]),
            ("09:39:22", "复检队列已清空", COLORS["text_secondary"]),
            ("09:38:10", "相机 3 触发完成", COLORS["text_secondary"]),
            ("09:37:45", "总气源压力正常 0.62MPa", COLORS["accent_green"]),
            ("09:36:58", "当日产量统计已刷新", COLORS["text_secondary"]),
        ]
        lv = LogView(logs, show_header=False)
        self._log_view = lv
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lv)
        return lay

    def _open_log_manager(self):
        """运行日志卡片「日志详情」：打开与左侧导航「日志管理」窗口内容完全一致的日志窗口。

        直接复用 LogManagerDialog（与生产运行界面 MainWindow._open_log_manager 中打开的是同一类），
        数据源均取自本生产运行界面的 get_operation_logs()，保证内容一致。
        """
        from nav_dialogs import LogManagerDialog
        dlg = getattr(self, "_dlg_log_detail", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = LogManagerDialog(self, self.window() or self)
        self._dlg_log_detail = dlg
        dlg.show()
