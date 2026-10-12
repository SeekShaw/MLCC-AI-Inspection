import os
import sys
import time
import uuid
import contextlib
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QSizePolicy, QLineEdit, QDialog, QMessageBox, QSpacerItem,
    QMenu
)
from PyQt6.QtCore import Qt, QSize, QPointF, QPoint, QTimer, QEvent
from PyQt6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QColor, QPen, QPixmap, QBrush, QPolygon, QActionGroup, QAction

import styles
from styles import MAIN_STYLE, COLORS, set_theme, get_theme_name, register_restyle
from production_view import ProductionView, CAMERA_NAMES
from debug_view import DebugView
from new_product_dialog import NewProductDialog
from product_manager_dialog import ProductManagerDialog, _make_template_products
from user_manager import UserManager
from device_settings_dialog import (
    DeviceSettingsDialog, TriggerSettingsDialog, RejectSettingsDialog,
)


# 任务栏图标：Windows 需要显式 AppUserModelID 才会把窗口归入本程序并显示应用图标，
# 否则部分环境下任务栏显示为空白/通用图标。
APP_USER_MODEL_ID = "Teruo.ElectronicComponentVision.V3.0"

# 软件版本 / 厂商信息：顶部信息栏展示，并在「关于」窗口中显示
APP_VERSION = "Ver5.0.10.34"
COMPANY_NAME = "ZiGAA ChuangYuan（智感科技）"
COMPANY_COPYRIGHT = "Copyright (C) 2026 By: ZIGAA ChuangYuan"

# Windows 开机自启动：注册表 HKCU\...\Run 下的项名
_AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_REG_NAME = "ElectronicComponentVisionV3"


def _autostart_command():
    """开机自启动要执行的命令行：打包后为 exe 路径；开发态为解释器 + 入口脚本。"""
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return f'"{os.path.abspath(sys.executable)}"'
    entry = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main_b.py")
    return f'"{sys.executable}" "{entry}"'


def set_windows_autostart(enabled):
    """写入 / 移除 Windows 开机启动项（当前用户 HKCU\\...\\Run）。

    返回是否成功；非 Windows 平台返回 False。注意：本函数会真实修改注册表，
    仅应在打包后的 exe 中调用（开发/自检环境请勿触发）。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_REG_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _AUTOSTART_REG_NAME, 0, winreg.REG_SZ,
                                  _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, _AUTOSTART_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def is_windows_autostart_enabled():
    """当前用户是否已登记开机自启动（非 Windows / 读取失败返回 False）。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_REG_PATH, 0,
                            winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _AUTOSTART_REG_NAME)
        return True
    except Exception:
        return False


def resolve_startup_user(user_manager):
    """解析启动登录账号，返回 (用户字典, 用户名)。

    优先使用「用户中心 → 设为默认登录」所设置的账号（列表中 ★ 标记）；
    未设置或该账号已不存在时，回退到超级管理员 admin。
    """
    default = user_manager.get_default_login()
    user = user_manager.get_user(default) if default else None
    if user is None:
        return user_manager.get_user("admin"), "admin"
    return user, default

# 图标多档尺寸：任务栏取 16/24/32、标题栏取 16、高 DPI / 大图标视图取更大尺寸
_APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _set_windows_app_id():
    """设置进程级 AppUserModelID（仅 Windows 生效，须在创建窗口前调用）。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID)
    except Exception:
        pass


def _app_icon_path() -> str:
    """app_icon.ico 位置：打包后取 exe 同级目录，开发时取工程根目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "app_icon.ico")


def _load_app_icon(draw_fn=None) -> QIcon:
    """构造应用图标。

    优先读取磁盘上的 app_icon.ico——Qt 会按其中的原生多档尺寸生成 HICON，
    任务栏/标题栏/Alt-Tab 都能取到合适尺寸，是任务栏图标最可靠的做法；
    文件缺失或读取失败时，回退到程序内按多档尺寸绘制的图标。
    """
    path = _app_icon_path()
    if os.path.exists(path):
        ic = QIcon(path)
        if not ic.isNull() and ic.availableSizes():
            return ic
    ic = QIcon()
    if draw_fn is not None:
        for s in _APP_ICON_SIZES:
            ic.addPixmap(draw_fn(s))
    return ic


@contextlib.contextmanager
def _suppress_other_topmost():
    """临时取消所有『置顶』顶层窗口（如「目标查找参数设置」窗口）的 WindowStaysOnTopHint，
    确保本应用内的模态弹窗（启动确认 / 校验提示等）不会被其遮挡而点不到、导致软件看似卡死。

    根因：参数窗口设了置顶，而启动确认框挂在主窗口下；两个置顶窗口分属不同顶层所有者时
    存在 z 序竞争，参数窗口会盖住确认框使其无法点击、exec() 阻塞事件循环 → 整机卡死。
    本上下文管理器在弹窗展示期间临时撤掉其它窗口的置顶，关闭后再原样恢复。
    """
    app = QApplication.instance()
    suppressed = []
    if app is not None:
        for w in app.topLevelWidgets():
            if w.isVisible() and (w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint):
                w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
                w.show()  # setWindowFlag 对可见窗口需 re-show 才生效
                suppressed.append(w)
    try:
        yield
    finally:
        for w in suppressed:
            w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            w.show()


def _make_header_icon(kind: str, size: int = 20) -> QIcon:
    """绘制顶部操作按钮的白色线性图标（透明底，叠加在彩色按钮背景上很醒目）。

    kind: new(加号) / manage(三横线) / play(三角) / stop(方块)
    """
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    white = QColor(255, 255, 255)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(white))
    m = int(size * 0.20)
    if kind == "new":  # 加号
        t = int(size * 0.16)
        w = max(3, int(size * 0.16))
        p.fillRect(t, size // 2 - w // 2, size - 2 * t, w, white)
        p.fillRect(size // 2 - w // 2, t, w, size - 2 * t, white)
    elif kind == "manage":  # 三横线（列表/管理）
        lh = max(2, int(size * 0.12))
        gap = int(size * 0.24)
        y0 = (size - (2 * gap + lh)) // 2
        for i in range(3):
            p.fillRect(m, y0 + i * gap, size - 2 * m, lh, white)
    elif kind == "play":  # 三角形
        tri = QPolygon([
            QPoint(int(size * 0.30), int(size * 0.22)),
            QPoint(int(size * 0.30), int(size * 0.78)),
            QPoint(int(size * 0.74), int(size * 0.50)),
        ])
        p.drawPolygon(tri)
    elif kind == "stop":  # 方块
        p.fillRect(int(size * 0.28), int(size * 0.28),
                   int(size * 0.44), int(size * 0.44), white)
    p.end()
    return QIcon(px)
from user_module import LoginDialog, make_user_center
from alarm_dialog import AlarmSettingsDialog
from nav_dialogs import (
    BoxMonitorDialog, LogManagerDialog, SystemConfigDialog,
    AdvancedSettingsDialog, PlaceholderDialog, AboutDialog,
    PasswordConfirmDialog, ImageSaveDialog,
)

# 左侧导航「功能按钮」定义：顺序即显示顺序；key 用于权限可见性控制
FUNC_NAV_ITEMS = [
    ("sys_config", "⚙️", "系统配置", "_open_system_config"),
    ("box_monitor", "📦", "盒子监控", "_open_box_monitor"),
    ("run_settings", "🔧", "运行设置", "_open_device_settings"),
    ("photo_settings", "⚡", "拍照设置", "_open_trigger_settings"),
    ("sort_settings", "🗑️", "分选设置", "_open_reject_settings"),
    ("alarm_settings", "🔔", "报警设置", "_open_alarm_settings"),
    ("advanced_settings", "🧩", "高级设置", "_open_advanced_settings"),
    ("production_report", "📊", "生产报表", "_open_production_report"),
    ("log_manage", "📝", "日志管理", "_open_log_manager"),
    ("image_save", "💾", "图片保存", "_open_image_save"),
    ("user_manage", "👤", "用户管理", "_open_user_center"),
]

# 各用户类别可见的「功能按钮」key 集合（不在集合内的按钮隐藏）
NAV_VISIBILITY = {
    "超级管理员": {k for k, *_ in FUNC_NAV_ITEMS},
    "设备管理员": {"production_report", "log_manage", "image_save", "user_manage"},
    "设备工程师": {"alarm_settings", "production_report", "log_manage", "image_save",
                   "user_manage", "photo_settings", "sort_settings",
                   "box_monitor", "run_settings"},
    "设备技术员": {"alarm_settings", "production_report", "log_manage", "image_save",
                   "user_manage", "photo_settings", "sort_settings"},
    "设备操作员": {"alarm_settings", "production_report", "log_manage", "image_save", "user_manage"},
}


# 顶部操作按钮（新建/管理/启动/停止）对应的权限项，用于「无权限点击弹窗」判断
HEADER_PERM = {
    "new": "create_product",
    "manage": "manage_product",
    "start": "start_stop",
    "stop": "start_stop",
}


# ---------------------------------------------------------------------------
# 系统资源（CPU / 内存）实时占用：底部状态栏按当前电脑实际情况显示。
# 优先用 Windows API（ctypes，标准库自带、无需第三方依赖、冻结 exe 也能用）；
# 非 Windows 或读取失败则回退静态占位，不影响其它功能。
# ---------------------------------------------------------------------------
try:
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    _HAS_WIN_RES = (sys.platform == "win32")

    def _win_get_system_times():
        """返回 (idle, kernel, user) 的 100ns 计数；用于计算 CPU 占用率差值。"""
        idle = _FILETIME(); kernel = _FILETIME(); user = _FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

        def _ft2int(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return _ft2int(idle), _ft2int(kernel), _ft2int(user)

    def _win_read_memory_load():
        """返回系统内存使用百分比（0-100 浮点）；读取失败返回 None。"""
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None
        return float(m.dwMemoryLoad)
except Exception:  # pragma: no cover - 仅在缺失 ctypes / 非 Windows 时触发
    _HAS_WIN_RES = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("电子元件视觉检测系统")
        # 自适应屏幕：启动即最大化铺满当前显示器。生产运行/相机调试等页面均按
        # 窗口实际尺寸（resizeEvent）重新布局，故不同分辨率下卡片都能铺满、不留空。
        # 最小尺寸仅作兜底，避免极小屏下控件被压垮；绝不写死 1920×1080 固定尺寸。
        self.setMinimumSize(1024, 640)
        self.setWindowState(Qt.WindowState.WindowMaximized)
        self.setStyleSheet(MAIN_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧导航栏：保持原有窄栏样式——仅图标按钮，不显示文字；
        # 功能按钮按角色权限控制可见性。窗体宽高与相邻间隙保持不变。
        # 相机组（首页+8相机）靠顶部收紧显示，10 个功能按钮靠底部收紧显示。
        nav = QFrame()
        nav.setFixedWidth(64)
        self._nav_frame = nav
        nav.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-right: 1px solid {COLORS["border"]}; }}
        """)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self.nav_buttons = []
        self._func_nav = {}  # key -> 功能按钮（用于权限可见性控制）

        # 已创建产品列表；默认存在两个不可删除的母版：电容 0402 与电阻 0603
        self.products = _make_template_products()
        self.current_product = self.products[0]

        # 用户与权限：启动登录账号优先取「用户中心 → 设为默认登录」设置的账号（★ 标记）；
        # 未设置或该账号已被删除时，回退到超级管理员 admin（便于演示全部功能）。
        self.user_manager = UserManager()
        self.current_user, self.default_login_username = \
            resolve_startup_user(self.user_manager)
        self._playing = False
        # 高级设置（会话级开关，存于主窗口）；开机自启动 / 抽盒剔除逻辑 / 密码确认周期为持久化项
        self._adv_settings = {
            # 设备停止统计清零：启用后点「设备停止」即自动清零生产统计（默认不启用）
            "stop_clear_stats": False,
            "beep": True,
            "auto_clear_confirm": True,
            "debug_overlay": False,
            "special_com": "COM16",
            "algo_threads": 3,
            "measure_decimals": 4,
            "startup_check_algo": "禁用",
            "startup_input_detail": "禁用",
            "min_refresh_interval": 10,
            "main_display_mode": "保持比例显示",
            "reject_mode": "逻辑剔除",
            "flash_gauge_mode": "禁用",
            "spot_check": "禁用",
            "grr_func": "禁用",
            "primary_lang": "跟随系统",
            "secondary_lang": "English",
            "pending_redirect": "禁用",
            "linkage_mode": "检测与设备联动模式（默认）",
            "start_out_to_glass_delay": 10,
            "start_glass_to_in_delay": 10,
            "stop_in_to_glass_delay": 10,
            "stop_glass_to_out_delay": 10,
            "start_algo_delay": 1000,
            "stop_algo_delay": 1000,
            "sequential_exec": "是",
        }
        # 空闲计时：用于「密码输入确认时间周期」（超时后再次操作需重新输入密码）
        self._last_activity = time.time()
        _qapp = QApplication.instance()
        if _qapp is not None:
            _qapp.installEventFilter(self)

        # 相机分组（首页 + 8 路相机）：置于顶部、内部间距收紧
        cam_group = QWidget()
        cam_vbox = QVBoxLayout(cam_group)
        cam_vbox.setContentsMargins(0, 0, 0, 0)
        cam_vbox.setSpacing(1)

        # 首页：生产运行（仅图标，名称见工具提示）
        self._add_nav_btn(cam_vbox, "🏠", "生产运行", 0)

        # 相机分组：一路相机一个图标按钮，点击打开对应调试界面
        cam_start = 1
        for i, name in enumerate(CAMERA_NAMES):
            self._add_nav_btn(cam_vbox, "📷", name, cam_start + i, tip=name, perm="camera_debug")

        nav_layout.addWidget(cam_group)
        # 中部弹性留白：把底部功能按钮组推到导航栏最下方
        nav_layout.addStretch(1)

        # 功能按钮组（顺序见 FUNC_NAV_ITEMS）：置于底部、内部间距收紧，
        # 仅图标，按角色权限控制可见性
        func_group = QWidget()
        func_vbox = QVBoxLayout(func_group)
        func_vbox.setContentsMargins(0, 0, 0, 0)
        func_vbox.setSpacing(1)
        for key, icon, label, action in FUNC_NAV_ITEMS:
            self._add_nav_btn(func_vbox, icon, label, getattr(self, action),
                              key=key, tip=label)
        nav_layout.addWidget(func_group)
        self.cam_start = cam_start

        # 主内容区（顶部不留白）
        content = QVBoxLayout()
        content.setContentsMargins(16, 0, 16, 12)
        content.setSpacing(10)

        # 注：原「顶部信息栏」软件名称 + 软件版本卡片（topbar）已按需求删除；
        # 「关于」按钮已移至底部状态栏（见 footer 构造），窗口标题仍显示软件名称。

        # 顶部标题栏：顶部中间操作按钮 + 当前产品 + 当前用户
        header = QFrame()
        header.setFixedHeight(52)
        self._header_frame = header
        header.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-radius: 8px; }}
        """)
        header_layout = QHBoxLayout(header)
        # 左侧保留 16px，右侧缩到 8px，让当前用户信息更贴近最右边缘
        header_layout.setContentsMargins(16, 0, 8, 0)
        header_layout.setSpacing(10)
        self._header_layout = header_layout

        # 左上角：当前产品信息（只读，随产品切换更新）
        # 形式：标签「当前产品：」+ 三个有底色窗体（类型/型号/规格），窗体宽度随字符数自适应
        prod_box = QWidget()
        prod_box_layout = QHBoxLayout(prod_box)
        prod_box_layout.setContentsMargins(0, 0, 0, 0)
        prod_box_layout.setSpacing(6)
        prod_label = QLabel("当前产品：")
        prod_label.setFont(QFont("Microsoft YaHei", 15, QFont.Weight.Bold))
        prod_label.setStyleSheet(f"color: {COLORS['text_primary']};")
        prod_box_layout.addWidget(prod_label)
        # 有底色的标签窗体：背景蓝、白字、圆角；不固定宽度，仅由文字 + 内边距决定，
        # 因此窗体宽度随字符数量自适应。
        # 显示内容优先取「产品类型（自定义）/产品型号（自定义）」，为空时回退到
        # 默认「产品类型/产品型号」；规格（如 Ver01）不再显示。
        _chip_style = (
            f"background-color: {COLORS['accent_green']}; color: #FFFFFF; "
            f"font-family: 'Microsoft YaHei'; font-size: 14px; font-weight: bold; "
            f"border-radius: 4px; padding: 0 10px;"
        )
        self._prod_chip_type = QLabel(self._prod_display_type(self.current_product))
        self._prod_chip_model = QLabel(self._prod_display_model(self.current_product))
        for _chip in (self._prod_chip_type, self._prod_chip_model):
            _chip.setStyleSheet(_chip_style)
            _chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prod_box_layout.addWidget(self._prod_chip_type)
        prod_box_layout.addWidget(self._prod_chip_model)
        self.lbl_product_header = prod_box   # 保留引用名，便于对齐计算
        header_layout.addWidget(prod_box)
        # 动态占位：把四个操作按钮的左边缘对齐到下方「生产信息」面板左边缘
        self._header_btn_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        header_layout.addItem(self._header_btn_spacer)

        # 顶部中间：操作按钮
        btn_group = QHBoxLayout()
        btn_group.setSpacing(8)
        self.btn_new = None
        self.btn_manage = None
        self.btn_start = None
        self.btn_stop = None
        for key, label, style, icon_kind in [
            ("new", "新建产品", "background-color: #4261FF; color: white;",
             "new"),
            ("manage", "管理产品", "background-color: #4261FF; color: white;",
             "manage"),
            ("start", "设备启动", "background-color: #0D822B; color: white;",
             "play"),
            ("stop", "设备停止", "background-color: #C81435; color: white;",
             "stop"),
        ]:
            btn = QPushButton(label)
            btn.setIcon(_make_header_icon(icon_kind))
            btn.setIconSize(QSize(20, 20))
            btn.setStyleSheet(f"border-radius: 4px; padding: 6px 14px; border: 1px solid transparent; {style}")
            btn_group.addWidget(btn)
            if key == "new":
                self.btn_new = btn
            elif key == "manage":
                self.btn_manage = btn
            elif key == "start":
                self.btn_start = btn
            elif key == "stop":
                self.btn_stop = btn
        # 让「当前产品」三个信息窗体与「新建产品/管理产品」按钮等高
        _bh = max(self.btn_new.sizeHint().height(), 30)
        for _c in (self._prod_chip_type, self._prod_chip_model):
            _c.setFixedHeight(_bh)
        header_layout.addLayout(btn_group)
        header_layout.addStretch()  # 把当前用户信息推到最右侧

        self.lbl_user_header = QLabel(self._user_header_text())
        self.lbl_user_header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_user_header.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; padding-left: 10px;")
        header_layout.addWidget(self.lbl_user_header)

        # 顶部标题栏「当前用户」右侧：切换用户按钮（效果等同于用户中心「切换用户 / 退出登录」）
        self.btn_switch_user = QPushButton("切换用户")
        self.btn_switch_user.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_switch_user.clicked.connect(self._switch_user)
        self._style_switch_user_btn()
        header_layout.addWidget(self.btn_switch_user)

        content.addWidget(header)

        # 页面栈：生产运行 + 每路相机一个调试界面 + 占位页
        self.stack = QStackedWidget()
        self.production = ProductionView(user_manager=self.user_manager)
        # 生产界面「扫码录入」等操作入口接入空闲确认（超时需重新输入密码）
        self.production.idle_confirm_cb = self.confirm_if_idle
        # 任意料盒/电磁阀达 100% 时由生产界面回调 _on_stop 执行自动停机
        self.production.set_alarm_stop_callback(self._on_stop)
        # 生产界面「设备编码」初始同步自用户中心的设备编码设置
        self.production.set_device_code(self.user_manager.device_code)
        # 「生产报表」筛选数据的示例值取自当前产品配置（产品类型 / 产品型号）
        self.production._report_product = self.current_product
        # 当前登录用户写入生产界面，供运行日志记录操作人
        self.production.set_current_user(self.current_user["name"],
                                        self.current_user["username"])
        # 左上角软件名称同步自用户管理器（超级管理员可改），并同步窗口标题
        self._sync_software_name()
        # 窗口标题栏 / 任务栏图标：优先读 exe 同级的 app_icon.ico（原生多档尺寸），
        # 读不到时用程序内绘制的多尺寸图标兜底（原先只给 64×64 单档，任务栏易取不到合适尺寸）。
        self._app_icon = _load_app_icon(self._make_app_icon)
        self.setWindowIcon(self._app_icon)
        # 高级设置「设备开机自启动」（默认开启）：按用户配置同步 Windows 启动项（仅 exe 生效）
        self._sync_autostart()
        # 启动诊断：把图标加载情况写入 exe 同级 startup_diag.log，便于真机排查任务栏图标
        try:
            _ip = _app_icon_path()
            self._startup_log(
                "icon: frozen={} path={} exists={} isNull={} sizes={}".format(
                    getattr(sys, "frozen", False), _ip, os.path.exists(_ip),
                    self._app_icon.isNull(),
                    sorted(s.width() for s in self._app_icon.availableSizes())))
        except Exception:
            pass
        self.stack.addWidget(self.production)
        # 启动 / 停止：驱动生产运行界面相机画布滚动播放
        # 顶部操作按钮：点击时按权限拦截（无权限弹窗提示），不再依赖禁用/隐藏
        self._bind_guarded(self.btn_start, "start", self._on_start)
        self._bind_guarded(self.btn_stop, "stop", self._on_stop)
        self._bind_guarded(self.btn_new, "new", self._open_new_product)
        self._bind_guarded(self.btn_manage, "manage", self._open_manage_product)
        # 运行中「生产运行中」按钮的脉冲高亮定时器（动态突出显示）
        self._pulse_state = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(600)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self.debug_views = []
        for name in CAMERA_NAMES:
            dv = DebugView(camera_name=name, main_window=self)
            self.debug_views.append(dv)
            self.stack.addWidget(dv)
        # 占位页面
        self._placeholders = []
        for _ in range(3):
            placeholder = QLabel("功能开发中...")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 16px;")
            self.stack.addWidget(placeholder)
            self._placeholders.append(placeholder)

        content.addWidget(self.stack)

        # 底部状态栏
        footer = QFrame()
        footer.setFixedHeight(28)
        self._footer_frame = footer
        footer.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-radius: 4px; }}
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 0, 12, 0)
        footer_layout.setSpacing(16)
        # 底部状态栏不再重复显示「当前用户 / 当前产品」（顶部标题栏已有），
        # 仅保留运行信息与状态指示，避免与顶部状态栏重复。
        # 布局：「语言」左对齐；其余项整体靠右（从右边开始往左排）。
        self.lbl_user_footer = None
        self._placeholders = []
        # 「关于」按钮：位于底部状态栏最左侧，在「语言：中文」左侧
        # （顶部信息栏的软件名称 + 软件版本卡片已删除，故「关于」下移至此处）
        self.btn_about = QPushButton("关于")
        self.btn_about.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about.setFixedHeight(22)
        self.btn_about.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['accent_blue']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 2px 10px; font-size: 12px;")
        self.btn_about.clicked.connect(self._open_about)
        footer_layout.addWidget(self.btn_about)
        # 语言：独立左对齐（「语言：」前缀 + 可下拉切换语言的按钮，默认中文）
        lang_prefix = QLabel("语言：")
        lang_prefix.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; background-color: transparent;")
        footer_layout.addWidget(lang_prefix)
        self._footer_lang_label = self._make_footer_dropdown(
            ["中文", "英语", "韩语", "日语", "德语", "俄语", "越南语"],
            "中文", self._on_lang_selected)
        footer_layout.addWidget(self._footer_lang_label)
        self._placeholders.append(self._footer_lang_label)
        # 其余项右对齐：先插入一个拉伸撑满左侧，再依次追加（整组靠右）
        footer_layout.addStretch(1)
        # 「缺陷图查看」：位于「显示所有图像」左侧，点击弹出缺陷图查看窗口
        self.lbl_defect_view = QLabel("缺陷图查看")
        # 颜色与其他底部按钮（显示所有图像/全清零等）保持一致
        self.lbl_defect_view.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        self.lbl_defect_view.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_defect_view.setToolTip("查看所有工位最新的 50 张缺陷图")
        self.lbl_defect_view.mousePressEvent = lambda e: self._open_defect_images()
        footer_layout.addWidget(self.lbl_defect_view)
        self._placeholders.append(self.lbl_defect_view)
        # 「显示所有图像」下拉：选择项（单选）——显示所有图像 / 仅显示不良品图像 / 仅显示良品图像
        # 点击向上展开选择项；默认显示「显示所有图像」，选中后按钮文本即显示为当前选择。
        self.btn_img_filter = self._make_footer_dropdown(
            ["显示所有图像", "仅显示不良品图像", "仅显示良品图像"],
            "显示所有图像", self._on_img_filter_selected)
        footer_layout.addWidget(self.btn_img_filter)
        self._placeholders.append(self.btn_img_filter)
        for txt in ["全清零", "灯光：ON", "清除硬件报警", "截屏"]:
            lbl = QLabel(txt)
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
            footer_layout.addWidget(lbl)
            self._placeholders.append(lbl)
        # 系统资源占用（CPU / 内存）：按当前电脑实际情况实时显示（非示例写死值）
        self.lbl_cpu_footer = QLabel("CPU: --%")
        self.lbl_mem_footer = QLabel("内存: --%")
        for _l in (self.lbl_cpu_footer, self.lbl_mem_footer):
            _l.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
            footer_layout.addWidget(_l)
            self._placeholders.append(_l)
        # 系统资源采样状态（CPU 占用基于两次采样差，需保存上一次时刻）
        self._sys_times_prev = None
        self._sysres_timer = QTimer(self)
        self._sysres_timer.setInterval(2000)
        self._sysres_timer.timeout.connect(self._refresh_sysres_footer)
        self._sysres_timer.start()
        self._refresh_sysres_footer()
        # 运行时间：按真实「设备启动 / 设备停止」计时——
        # 开始时间 = 点击「设备启动」的时刻；运行中每秒刷新；
        # 点「设备停止」暂停计入，重新启动后在原累计基础上继续（点击标签可切换查看开始时间）。
        self._run_accum_secs = 0.0      # 已累计运行秒数（不含当前未停止的运行段）
        self._run_session_t0 = None     # 当前运行段起始（time.monotonic()）；None=未在运行
        self._run_start_wall = None     # 最近一次「设备启动」的墙钟时间（字符串）
        self.lbl_runtime_footer = QLabel("运行时间：00H:00M:00S")
        self.lbl_runtime_footer.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; cursor: pointer;")
        self.lbl_runtime_footer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_runtime_footer.setToolTip("开始运行时间：未启动（点击「设备启动」后记录）")
        self._runtime_show_start = False
        self.lbl_runtime_footer.mousePressEvent = lambda e: self._toggle_runtime_text()
        footer_layout.addWidget(self.lbl_runtime_footer)
        self._placeholders.append(self.lbl_runtime_footer)
        # 运行计时刷新定时器：仅运行中启动；停止后标签冻结在已累计值（暂停计入）
        self._runtime_timer = QTimer(self)
        self._runtime_timer.setInterval(1000)
        self._runtime_timer.timeout.connect(self._refresh_runtime_footer)
        # Copyright：置于「运行时间」右侧（二者位置互换）
        self.lbl_copyright = QLabel("Copyright (C) 2026 By: ZIGAA ChuangYuan")
        self.lbl_copyright.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        footer_layout.addWidget(self.lbl_copyright)
        self._placeholders.append(self.lbl_copyright)
        # 暗 / 亮主题切换：从标题栏移至底部状态栏，避免标题栏操作区拥挤
        self.theme_btn = QPushButton("🌓 亮色" if get_theme_name() == "dark" else "🌓 暗色")
        self.theme_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 4px 12px; font-size: 12px;")
        self.theme_btn.setFixedHeight(24)
        self.theme_btn.clicked.connect(self._toggle_theme)
        footer_layout.addWidget(self.theme_btn)
        content.addWidget(footer)

        main_layout.addWidget(nav)
        main_layout.addLayout(content, 1)

        self.switch_page(0)
        self._update_button_states(False)  # 初始：启动绿色（可点）、停止常规灰
        self._apply_permissions()  # 按当前用户权限门控各功能入口
        self.production.set_scan_locked(False)  # 初始未运行：料号/批号可录入、扫码按钮可用
        register_restyle(self._restyle_self)

    def _update_button_states(self, playing):
        """启动 / 停止按钮状态：
        - 未运行：启动=绿色「设备启动」（可点击启动）；停止=常规灰（禁用）
        - 运行中：启动=绿色「生产运行中」，由脉冲定时器动态高亮突出；停止=红色（可点击停止）
        """
        base = "border-radius: 4px; padding: 6px 14px; "
        gray = (f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
                f"border: 1px solid {COLORS['border']};")
        if playing:
            self.btn_start.setText("生产运行中")
            self.btn_start.setStyleSheet(
                base + "background-color: #0D822B; color: white; font-weight: bold; "
                       "border: 1px solid #2EA043;")
            # 停止按钮：红色可用
            self.btn_stop.setText("设备停止")
            self.btn_stop.setStyleSheet(
                base + "background-color: #C81435; color: white; border: 1px solid #C81435;")
            # 启动脉冲高亮（动态突出「生产运行中」）
            if not self._pulse_timer.isActive():
                self._pulse_state = False
                self._pulse_timer.start()
        else:
            if self._pulse_timer.isActive():
                self._pulse_timer.stop()
            self.btn_start.setText("设备启动")
            self.btn_start.setStyleSheet(
                base + "background-color: #0D822B; color: white; border: 1px solid #0D822B;")
            # 停止按钮：常规灰禁用
            self.btn_stop.setText("设备停止")
            self.btn_stop.setStyleSheet(base + gray)

    def _pulse_tick(self):
        """运行中按钮的脉冲高亮：在常规绿与亮绿之间呼吸切换，动态突出「生产运行中」。"""
        if not self._playing:
            return
        self._pulse_state = not self._pulse_state
        base = "border-radius: 4px; padding: 6px 14px; color: white; font-weight: bold; "
        if self._pulse_state:
            self.btn_start.setStyleSheet(
                base + "background-color: #1AA13A; border: 1px solid #5BE584;")
        else:
            self.btn_start.setStyleSheet(
                base + "background-color: #0D822B; border: 1px solid #2EA043;")

    # ---------- 主题切换（暗 / 亮）----------
    def _toggle_theme(self):
        """切换暗色 / 亮色主题：set_theme 会原地替换 COLORS 并触发所有组件重绘。"""
        name = "light" if get_theme_name() == "dark" else "dark"
        set_theme(name)
        # 按钮文案表示「点击切换到」的目标模式
        self.theme_btn.setText("🌓 亮色" if name == "dark" else "🌓 暗色")

    def _restyle_self(self):
        """主题切换：重绘主窗口外壳（导航栏 / 标题栏 / 底部栏 / 按钮 / 占位符）。"""
        self.setStyleSheet(styles.MAIN_STYLE)
        self._nav_frame.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-right: 1px solid {COLORS["border"]}; }}
        """)
        self._header_frame.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-radius: 8px; }}
        """)
        if getattr(self, "btn_about", None) is not None:
            self.btn_about.setStyleSheet(
                f"background-color: {COLORS['bg_panel']}; color: {COLORS['accent_blue']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
                f"padding: 2px 10px; font-size: 12px;")
        self._footer_frame.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-radius: 4px; }}
        """)
        # 左侧导航图标按钮（仅图标，选中高亮橙色）
        for btn in self.nav_buttons:
            btn.setStyleSheet(self._nav_btn_style())
        # 顶部操作按钮（启动/停止等）
        self._update_button_states(self._playing)
        # 用户标签 / 占位符 / 主题按钮
        self.lbl_user_header.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; padding-left: 10px;")
        self._style_switch_user_btn()
        if getattr(self, "lbl_user_footer", None) is not None:
            self.lbl_user_footer.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px;")
        if getattr(self, "lbl_runtime_footer", None) is not None:
            self.lbl_runtime_footer.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 11px; cursor: pointer;")
        # 底部状态栏文本标签统一 11px（语言 + 右侧各项）
        for lbl in self._placeholders:
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        self.theme_btn.setStyleSheet(
            f"background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"padding: 6px 12px; font-size: 12px;")

    # ---------- 用户与权限 ----------
    @staticmethod
    def _display_user_name(u):
        """取用于界面展示的用户姓名；姓名为空时回退到登录账号，避免显示空白。"""
        if not u:
            return ""
        name = (u.get("name") or "").strip()
        if name:
            return name
        return u.get("username", "")

    def _user_header_text(self):
        u = self.current_user
        if u is None:
            return "当前用户：未登录"
        return f"当前用户：{self._display_user_name(u)}（{u.get('category', '')}）"

    def _refresh_user_labels(self):
        if getattr(self, "lbl_user_header", None) is not None:
            self.lbl_user_header.setText(self._user_header_text())
        if getattr(self, "lbl_user_footer", None) is not None:
            u = self.current_user
            self.lbl_user_footer.setText(
                f"当前用户：{self._display_user_name(u)}" if u else "当前用户：未登录")

    def _apply_permissions(self):
        """按当前登录用户的权限门控各功能入口。

        左侧「功能按钮」（FUNC_NAV_ITEMS）：按当前用户对该功能的操作权限显隐——
        无权限则不显示，有权限才显示（可见集合见 NAV_VISIBILITY）。
        顶部操作按钮（新建/管理/启动/停止）保持可见可点，无权限时点击弹窗提示
        「当前用户无操作权限，请联系厂商开通或切换账号登录」（见 _guarded*）。
        仅保留与「生产运行」状态强相关的禁用（运行中不可管理、未运行不可停止）。
        """
        # 新建产品：始终可点，无权限时由点击拦截弹窗
        self.btn_new.setEnabled(True)
        # 「管理产品」运行中强制禁用（底色变灰）；停止后按权限保持可点（无权限点击弹窗）
        if self._playing:
            self.btn_manage.setEnabled(False)
            self.btn_manage.setStyleSheet(self._manage_style(True))
        else:
            self.btn_manage.setEnabled(True)
            self.btn_manage.setStyleSheet(self._manage_style(False))
        # 启动/停止：始终可点，无权限时点击拦截弹窗
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(getattr(self, "_playing", False))
        # 相机调试入口：始终可点，无权限时由 _guarded_switch 拦截弹窗
        for i in range(len(CAMERA_NAMES)):
            idx = getattr(self, "cam_start", 1) + i
            if 0 <= idx < len(self.nav_buttons):
                self.nav_buttons[idx].setEnabled(True)
        # 左侧功能按钮：按当前用户对该功能的操作权限显隐（无权限隐藏、有权限显示）
        for key, btn in getattr(self, "_func_nav", {}).items():
            btn.setVisible(self._is_allowed(key))
        self._refresh_user_labels()
        # 权限切换后同步窗口标题中的软件名称（软件名称由超级管理员在「设备设置」中修改）
        self._sync_software_name()

    def _set_current_user(self, user):
        self.current_user = user
        self._refresh_user_labels()
        self._apply_permissions()
        # 切换/登录用户后，将「负责人」同步更新为当前登录用户名
        if getattr(self, "production", None) is not None:
            self.production.set_current_user(user["name"], user["username"])

    def _style_switch_user_btn(self):
        """顶部「切换用户」按钮样式（随主题刷新）。"""
        btn = getattr(self, "btn_switch_user", None)
        if btn is None:
            return
        btn.setStyleSheet(
            f"background-color: {COLORS['accent_blue']}; color: #FFFFFF; "
            f"border: none; border-radius: 4px; padding: 4px 12px; font-size: 12px;")

    def _switch_user(self):
        """切换用户：直接弹出登录框，登录成功后切换当前账号。

        效果等同于用户中心页面右下角的「切换用户 / 退出登录」（设置 switch_requested
        并重新登录），但省去先打开用户中心这一步。
        """
        login = LoginDialog(self.user_manager, self)
        if login.exec() == QDialog.DialogCode.Accepted and getattr(login, "user", None):
            self._set_current_user(login.user)

    # ---------- 权限拦截（无权限点击弹窗） ----------
    def _is_allowed(self, key):
        """判断当前用户是否可使用 key 对应的功能入口。

        key 为 HEADER_PERM 中的顶部按钮键时按权限项判断；
        否则（左侧功能导航键）按 NAV_VISIBILITY 角色可见性判断。
        """
        u = self.current_user
        if not u:
            return False
        if key in HEADER_PERM:
            return self.user_manager.can(u, HEADER_PERM[key])
        return key in NAV_VISIBILITY.get(u["category"], set())

    def _deny(self):
        """无操作权限时的统一提示。"""
        QMessageBox.information(
            self, "权限提示",
            "当前用户无操作权限，请联系厂商开通或切换账号登录")

    def _guarded(self, key, slot):
        """若空闲超时需先输入密码确认；再检查权限，通过后执行 slot。"""
        if not self.confirm_if_idle():
            return
        if not self._is_allowed(key):
            self._deny()
            return
        slot()

    def _guarded_nav(self, key, fn):
        """左侧功能按钮：先空闲确认 → 再权限校验，通过则执行 fn。"""
        if not self.confirm_if_idle():
            return
        if not self._is_allowed(key):
            self._deny()
            return
        fn()

    def _guarded_switch(self, perm, index):
        """相机调试入口：先空闲确认 → 再校验 camera_debug 权限，通过则翻页。"""
        if not self.confirm_if_idle():
            return
        if not self.user_manager.can(self.current_user, perm):
            self._deny()
            return
        self.switch_page(index)

    def _bind_guarded(self, btn, key, slot):
        """将顶部操作按钮连接到带权限拦截的槽。"""
        btn.clicked.connect(lambda *a, k=key, s=slot: self._guarded(k, s))

    # ------------------------------------------------------------------
    # 空闲确认（高级设置「密码输入确认时间周期」）：
    # 当前登录用户超过设定时长未操作软件，再次操作时需重新输入密码确认。
    # ------------------------------------------------------------------
    def _touch_activity(self):
        """记录一次用户操作（鼠标点击 / 按键 / 滚轮），用于空闲计时。"""
        self._last_activity = time.time()

    def _idle_limit_seconds(self):
        um = getattr(self, "user_manager", None)
        getter = getattr(um, "confirm_interval_seconds", None)
        if callable(getter):
            try:
                return int(getter())
            except Exception:
                pass
        return 180

    def _idle_seconds(self):
        return max(0.0, time.time() - float(getattr(self, "_last_activity", time.time())))

    def _idle_expired(self):
        return self._idle_seconds() >= self._idle_limit_seconds()

    def eventFilter(self, obj, event):
        """全局事件过滤：仅在「本窗口内的点击 / 按键 / 滚轮」时刷新空闲计时。"""
        try:
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                                QEvent.Type.Wheel):
                w = obj if isinstance(obj, QWidget) else None
                if w is not None and (w is self or self.isAncestorOf(w)):
                    self._touch_activity()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def confirm_if_idle(self, action_hint=""):
        """空闲超时后要求重新输入密码确认：通过返回 True；取消或密码未通过返回 False。

        未超时则直接通过并刷新计时，因此该调用可安全地放在各操作入口最前面。
        """
        if not self._idle_expired():
            self._touch_activity()
            return True
        um = getattr(self, "user_manager", None)
        user = self.current_user or {}
        dlg = PasswordConfirmDialog(
            self,
            username=user.get("username", ""),
            name=user.get("name", ""),
            password=str(user.get("password", "")),
            interval=(um.get_confirm_interval() if um is not None else "3分钟"),
            action_hint=action_hint)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._touch_activity()
            return True
        return False

    def _open_user_center(self):
        """打开用户中心；若请求切换用户，引导重新登录。

        关闭后重新应用权限门控，使「权限配置」里对当前用户类别的修改
        立即反映到主界面（新建/管理/启动停止/相机调试入口）。
        """
        def open_center():
            return make_user_center(
                self.user_manager, self.current_user, self,
                device_code_callback=self._update_production_device_code)

        dlg = open_center()
        while True:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                break
            if getattr(dlg, "switch_requested", False):
                login = LoginDialog(self.user_manager, self)
                if login.exec() == QDialog.DialogCode.Accepted:
                    self._set_current_user(login.user)
                    dlg = open_center()
                    continue
                break
            break
        # 权限配置 / 用户编辑可能改变了当前用户类别权限，关闭后刷新门控
        self._apply_permissions()

    def _update_production_device_code(self, values):
        """用户中心「设备编码设置」保存后同步到生产界面设备编码字段。"""
        if getattr(self, "production", None) is not None:
            self.production.set_device_code(values)
            self.production.log_operation(self.current_user["name"], "修改了设备设置（设备编码/软件名称）")

    def _open_alarm_settings(self):
        """打开「报警设备」阈值设置窗口（满料停机阈值 / 电磁阀寿命阈值）。"""
        is_super = bool(self.current_user and self.current_user.get("category") == "超级管理员")
        dlg = AlarmSettingsDialog(
            self,
            # 「已使用次数清零」回调：传入阀键则仅清零该阀；无参则全部清空
            on_clear_valve_counts=lambda key=None: self.production.reset_valve_counts(key),
            is_super_admin=is_super,
            get_valve_counts=self.production.get_valve_counts,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.production.log_operation(self.current_user["name"], "修改了报警设备参数")

    def _open_device_settings(self):
        """打开「设备设置」非模态浮窗（DD马达 / 振动盘 / 高压静电 / 负压）。"""
        self._show_modeless("_dlg_device", DeviceSettingsDialog)
        self.production.log_operation(self.current_user["name"], "打开了设备设置")

    def _open_trigger_settings(self):
        """打开「触发设定」非模态浮窗，并同步到调试界面触发模式。"""
        self._show_modeless("_dlg_trigger", TriggerSettingsDialog)
        self.production.log_operation(self.current_user["name"], "打开了触发设定")

    def _open_reject_settings(self):
        """打开「剔除设定」非模态浮窗。"""
        self._show_modeless("_dlg_reject", RejectSettingsDialog)
        self.production.log_operation(self.current_user["name"], "打开了剔除设定")

    def _open_about(self):
        """打开「关于」：显示当前软件信息（名称 / 版本 / 设备信息）与厂商信息。"""
        name = (self.user_manager.software_name or "").strip() or "电子元件视觉检测系统"
        AboutDialog(self, software_name=name, version=APP_VERSION,
                    device_code=self.user_manager.device_code,
                    company=COMPANY_NAME, copyright_text=COMPANY_COPYRIGHT).exec()

    def _open_defect_images(self):
        """打开「缺陷图查看」窗口：展示所有工位最新的 50 张缺陷图（懒创建，单例）。"""
        w = getattr(self, "_defect_image_window", None)
        if w is None:
            from defect_image_window import DefectImageWindow
            w = DefectImageWindow(self)
            self._defect_image_window = w
        w.show()
        w.raise_()
        w.activateWindow()

    # ------------------------------------------------------------------
    # 底部状态栏下拉按钮（通用构造器）
    # ------------------------------------------------------------------
    def _make_footer_dropdown(self, options, default, handler):
        """构造一个底部状态栏风格的下拉按钮：点击向上展开选项（单选），选中后按钮文本即显示当前项。"""
        btn = QPushButton(default)
        btn.setFixedHeight(22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px 10px; font-size: 11px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; }}")
        menu = QMenu(self)
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for opt in options:
            act = QAction(opt, menu)
            act.setCheckable(True)
            act.setChecked(opt == default)
            act.triggered.connect(
                lambda _checked, o=opt, h=handler: h(o))
            grp.addAction(act)
            menu.addAction(act)
        btn.setMenu(menu)
        return btn

    def _on_img_filter_selected(self, mode):
        """底部「显示所有图像」下拉：选中后更新按钮文本并同步缺陷图窗口筛选模式。"""
        self.btn_img_filter.setText(mode)
        w = getattr(self, "_defect_image_window", None)
        if w is not None:
            w.set_filter_mode(mode)
        if hasattr(self, "production") and self.production is not None:
            self.production.log_operation(
                self.current_user["name"], f"图像显示模式：{mode}")

    def _on_lang_selected(self, lang):
        """底部「语言」下拉：选中后更新按钮文本（界面语言切换预留入口）。"""
        self._footer_lang_label.setText(lang)
        if hasattr(self, "production") and self.production is not None:
            self.production.log_operation(
                self.current_user["name"], f"界面语言：{lang}")

    # ------------------------------------------------------------------
    # 开机自启动（高级设置）：同步到 Windows 当前用户启动项
    # ------------------------------------------------------------------
    def apply_autostart(self, enabled):
        """把「设备开机自启动」同步到 Windows 启动项，返回是否成功。"""
        return set_windows_autostart(bool(enabled))

    def _sync_autostart(self):
        """启动时按用户配置同步开机启动项（默认开启）。

        仅在打包后的 exe 中执行：开发/自检环境不修改注册表，避免污染开发机。
        """
        if not getattr(sys, "frozen", False):
            return
        try:
            set_windows_autostart(bool(getattr(self.user_manager, "autostart", True)))
        except Exception:
            pass

    def _open_system_config(self):
        """打开「系统配置」：软件名称（超级管理员可改）/ 设备信息 / 主题切换。"""
        dlg = SystemConfigDialog(self, self)
        dlg.exec()

    def _open_box_monitor(self):
        """打开「盒子监控」非模态窗口，实时显示四个料盒收料量与满料状态。"""
        dlg = getattr(self, "_dlg_box", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        self._dlg_box = BoxMonitorDialog(self.production, self)
        self._dlg_box.show()

    def _open_advanced_settings(self):
        """打开「高级设置」：会话级运行选项（蜂鸣 / 启动确认 / 调试叠加）。"""
        dlg = AdvancedSettingsDialog(self, self)
        dlg.exec()

    def _open_production_report(self):
        """打开「生产报表」：内容与「统计信息」卡片「导出」按钮弹出的完全一致。

        直接复用 ProductionView._open_production_report（同一个 ProductionReportDialog），
        避免左侧导航与卡片导出两处内容各自维护、日久不一致。
        """
        pv = getattr(self, "production", None)
        if pv is not None and hasattr(pv, "_open_production_report"):
            pv._open_production_report()
            return
        PlaceholderDialog(self, "生产报表", "生产报表功能开发中，敬请期待。").exec()

    def _open_log_manager(self):
        """打开「日志管理」非模态窗口，展示运行操作日志。"""
        dlg = getattr(self, "_dlg_log", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        self._dlg_log = LogManagerDialog(self.production, self)
        self._dlg_log.show()

    def _open_image_save(self):
        """打开「图片保存」非模态窗口，配置图像保存策略/格式/缩放/质量。"""
        dlg = getattr(self, "_dlg_img_save", None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        self._dlg_img_save = ImageSaveDialog(self)
        self._dlg_img_save.show()

    def _add_nav_btn(self, layout, icon, label, target, key=None, tip=None, perm=None):
        """左侧导航按钮：仅图标（emoji），保持原有窄栏样式。
        target 为 int 时按页面序号翻页（可选中）；为 callable 时作为点击动作（打开窗口）。
        key 用于左侧功能按钮的权限标识与可见性登记；
        perm 用于相机调试等翻页按钮的权限校验（无权限点击弹窗）。"""
        btn = QPushButton(icon)
        btn.setMinimumHeight(26)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setToolTip(tip or label)
        if callable(target):
            if key is not None:
                btn.clicked.connect(
                    lambda _checked=False, k=key, fn=target: self._guarded_nav(k, fn))
            else:
                btn.clicked.connect(target)
        else:
            btn.setCheckable(True)
            if perm is not None:
                btn.clicked.connect(
                    lambda _checked=False, i=target, p=perm: self._guarded_switch(p, i))
            else:
                btn.clicked.connect(lambda _checked, i=target: self.switch_page(i))
        btn.setStyleSheet(self._nav_btn_style())
        self.nav_buttons.append(btn)
        layout.addWidget(btn)
        if key is not None:
            self._func_nav[key] = btn
        return btn

    def _nav_btn_style(self):
        """左侧导航按钮统一样式：仅图标，居中；选中（翻页）高亮橙色。"""
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_secondary']};
                border: none;
                border-radius: 6px;
                padding: 2px 0px;
                font-size: 18px;
                text-align: center;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']}; }}
            QPushButton:checked {{ background-color: {COLORS['accent_orange']}; color: white; }}
        """

    def _manage_style(self, disabled):
        """「管理产品」按钮样式：可点时蓝色，禁用（运行中）时灰底。"""
        if disabled:
            return (f"border-radius: 4px; padding: 6px 14px; color: {COLORS['text_secondary']}; "
                    f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']};")
        return "border-radius: 4px; padding: 6px 14px; background-color: #4261FF; color: white; border: 1px solid transparent;"

    def _add_launch_btn(self, layout, label, action):
        """左侧导航栏底部：带文字的「启动非模态浮窗」按钮（区别于翻页图标按钮）。"""
        btn = QPushButton(label)
        btn.setMinimumHeight(30)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']}; color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']}; border-radius: 6px;
                font-size: 12px; padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_orange']}; color: white;
                border-color: {COLORS['accent_orange']};
            }}
        """)
        btn.clicked.connect(action)
        layout.addWidget(btn)
        return btn

    def _show_modeless(self, attr, dlg_cls):
        """打开（或前置）一个非模态对话框：已打开则置顶，否则新建并 show()。"""
        dlg = getattr(self, attr, None)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return
        dlg = dlg_cls(self)
        setattr(self, attr, dlg)
        dlg.show()

    def switch_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    def _startup_log(self, msg):
        """把『设备启动』链路关键步骤写入 output/startup_diag.log，便于真机复现卡点。

        注意 frozen(打包 exe) 下 __file__ 指向解包目录，必须用 dirname(sys.executable)
        定位到 exe 所在的 output/，否则日志会写到临时目录、真机看不到。"""
        try:
            import os, datetime, sys
            if getattr(sys, "frozen", False):
                d = os.path.dirname(os.path.abspath(sys.executable))
            else:
                d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "startup_diag.log")
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    # ---------------- 底部「运行时间 / 开始运行时间」真实计时 ----------------
    def _format_runtime(self, secs):
        """把运行秒数格式化为「HHH:MM:SS 风格」的 00H:00M:00S 文本。"""
        secs = int(round(secs))
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}H:{m:02d}M:{s:02d}S"

    def _runtime_current_secs(self):
        """当前累计运行秒数 = 已累计值 +（运行中）本次运行段已经过的时间。"""
        total = getattr(self, "_run_accum_secs", 0.0)
        if getattr(self, "_run_session_t0", None) is not None:
            total += max(0.0, time.monotonic() - self._run_session_t0)
        return total

    def _refresh_runtime_footer(self):
        """按当前状态刷新底部标签（运行中由定时器每秒调用，启动/停止时手动调用）。"""
        if self._runtime_show_start:
            self.lbl_runtime_footer.setText(
                f"开始运行时间：{self._run_start_wall or '未启动'}")
        else:
            self.lbl_runtime_footer.setText(
                f"运行时间：{self._format_runtime(self._runtime_current_secs())}")

    def _toggle_runtime_text(self):
        """点击标签：在「运行时间」与「开始运行时间」之间切换显示。"""
        self._runtime_show_start = not self._runtime_show_start
        self._refresh_runtime_footer()

    def _refresh_sysres_footer(self):
        """刷新底部「CPU / 内存」占用：按当前电脑实际情况显示（每 2s 由定时器调用）。"""
        if not _HAS_WIN_RES:
            self.lbl_cpu_footer.setText("CPU: --%")
            self.lbl_mem_footer.setText("内存: --%")
            return
        # 内存：系统使用百分比（GlobalMemoryStatusEx.dwMemoryLoad）
        try:
            mem_pct = _win_read_memory_load()
        except Exception:
            mem_pct = None
        # CPU：基于两次 GetSystemTimes 采样差（kernel 时间含 idle）
        try:
            idle, kernel, user = _win_get_system_times()
            prev = self._sys_times_prev
            self._sys_times_prev = (idle, kernel, user)
            if prev is None:
                cpu_pct = 0.0
            else:
                idle_d = idle - prev[0]
                total_d = (kernel + user) - (prev[1] + prev[2])
                cpu_pct = (0.0 if total_d <= 0
                           else max(0.0, min(100.0, 100.0 * (total_d - idle_d) / total_d)))
        except Exception:
            cpu_pct = None
        self.lbl_cpu_footer.setText(
            f"CPU: {cpu_pct:.0f}%" if cpu_pct is not None else "CPU: --%")
        self.lbl_mem_footer.setText(
            f"内存: {mem_pct:.0f}%" if mem_pct is not None else "内存: --%")

    def _on_start(self):
        """启动：先校验料号/批号是否填写，缺失则提示并中止；通过后才开始播放。
        运行中再次点击「生产运行中」按钮视为无效（停止请点「设备停止」）。"""
        self._startup_log("=== _on_start called ===")
        if self._playing:
            self._startup_log("already playing -> return")
            return
        pn = self.production.pn_edit.text().strip()
        lot = self.production.lot_edit.text().strip()
        if not pn or not lot:
            missing = []
            if not pn:
                missing.append("料号")
            if not lot:
                missing.append("批号")
            with _suppress_other_topmost():
                box = QMessageBox(QMessageBox.Icon.Warning, "无法启动",
                                 f"请先输入{'、'.join(missing)}后再启动生产。",
                                 QMessageBox.StandardButton.Ok, self)
                # 置顶，避免被「目标查找参数设置」等置顶窗口遮挡导致无法点击（软件看似卡死）
                box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                box.exec()
            return
        # 定量生产已开启时，必须先填写有效的生产数量
        if self.production.quantitative_enabled():
            q = self.production.quant_target_value()
            if q is None:
                with _suppress_other_topmost():
                    box = QMessageBox(QMessageBox.Icon.Warning, "无法启动",
                                     "已开启「定量生产」，请先输入生产数量后再启动。",
                                     QMessageBox.StandardButton.Ok, self)
                    box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                    box.exec()
                return
        # 启动前确认：必须点击「确认」方可启动成功
        self._startup_log("show confirm dialog")
        with _suppress_other_topmost():
            box = QMessageBox(QMessageBox.Icon.Question, "启动确认", "请确认料盒是否已清空！",
                             QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self)
            # 默认聚焦「确认」：避免用户按回车/空格时误触「取消」导致启动被静默中止
            # （此前默认是「取消」，回车即取消 → 表面像『点了启动却没反应/画布不刷新』）。
            box.setDefaultButton(QMessageBox.StandardButton.Ok)
            box.setWindowModality(Qt.WindowModality.ApplicationModal)
            box.setWindowFlags(box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            box.raise_()
            box.activateWindow()
            self._startup_log("confirm exec() ...")
            rc = box.exec()
            # 注意：鼠标点击「确认/Ok」按钮时 exec() 返回 StandardButton.Ok(1024)，
            # 而键盘(Enter 触发默认按钮)走 accept() 返回 DialogCode.Accepted(1)。
            # 二者都代表「确认」，必须都判为通过；否则鼠标点击会被误判为取消 → 提前 return →
            # 播放不启动、画布/示例数据全不刷新（此前 rc!=Accepted(1) 导致点确认也无效）。
            self._startup_log(f"confirm rc={rc} (Accepted={int(QMessageBox.DialogCode.Accepted)}, Ok={int(QMessageBox.StandardButton.Ok)})")
            if rc not in (QMessageBox.DialogCode.Accepted, QMessageBox.StandardButton.Ok):
                return
        self._startup_log("confirm accepted -> start playback")
        self._playing = True
        # 底部运行时间：开始时间 = 本次点击「设备启动」的时刻；运行时间在原累计
        # 基础上继续计入（停止期间不计入），每秒刷新。
        self._run_start_wall = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lbl_runtime_footer.setToolTip(f"开始运行时间：{self._run_start_wall}")
        self._run_session_t0 = time.monotonic()
        self._runtime_timer.start()
        self._refresh_runtime_footer()
        self._startup_log("calling production.start_playback()")
        self.production.start_playback()
        self._startup_log(f"production playing={self.production._playing} timer={self.production._play_timer.isActive()}")
        for dv in self.debug_views:
            dv.start_playback()
            dv.set_production_running(True)   # 先置生产运行态，再切换模式（守卫允许「生产运行」）
            dv.set_trigger_mode("生产运行")   # 设备启动后，调试界面相机工作模式切到「生产运行」
        self._startup_log("debug views started")
        self.production.log_operation(self.current_user["name"], "启动了生产运行")
        # 运行中保持「生产运行中」按钮可点（点击无效），由脉冲动画动态高亮
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self._update_button_states(True)  # 启动后：启动显示「生产运行中」绿底脉冲、停止转红
        self.production.set_scan_locked(True)  # 启动后锁定料号/批号录入，防止运行中误改
        self._apply_permissions()  # 运行中：禁用「管理产品」按钮（底色变灰）

    def _on_stop(self):
        """停止：相机画布停止滚动并冻结最后样张，统计冻结在最后累计值。"""
        self._playing = False
        # 底部运行时间：停止 → 本次运行段并入累计并暂停计入（标签冻结在当前值）；
        # 重新「设备启动」后在原累计基础上继续。
        if getattr(self, "_run_session_t0", None) is not None:
            self._run_accum_secs += max(0.0, time.monotonic() - self._run_session_t0)
            self._run_session_t0 = None
        if getattr(self, "_runtime_timer", None) is not None:
            self._runtime_timer.stop()
        self._refresh_runtime_footer()
        self.production.stop_playback()
        for dv in self.debug_views:
            dv.stop_playback()
            dv.set_production_running(False)   # 先解除生产运行态，再切换模式（守卫解除）
            dv.set_trigger_mode("连续取图")   # 设备停止后，调试界面相机工作模式退出「生产运行」
        self.production.log_operation(self.current_user["name"], "停止了生产运行")
        # 高级设置「设备停止统计清零」：启用时停止后自动清零生产统计（默认不启用）
        if getattr(self, "_adv_settings", {}).get("stop_clear_stats") \
                and not getattr(self.production, "_cleared", False):
            self.production._toggle_clear()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._update_button_states(False)  # 停止后：脉冲停止、启动恢复「设备启动」绿底
        self.production.set_scan_locked(False)  # 停止后解锁料号/批号录入
        self._apply_permissions()  # 停止后：恢复「管理产品」按钮可点（按权限，蓝色）

    def _open_new_product(self):
        """点击「新建产品」：弹出两步向导，完成后新增产品并更新界面。"""
        dlg = NewProductDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            from product_manager_dialog import _description_for
            product = {
                "id": str(uuid.uuid4()),
                "created_at": datetime.now().strftime("%Y%m%d %H:%M:%S"),
                "product_type": dlg.product_type,
                "product_model": dlg.product_model,
                "product_spec": dlg.product_spec,
                "description": dlg.product_description or _description_for(dlg.product_type),
                "custom_type_display": dlg.custom_type_display,
                "custom_model_display": dlg.custom_model_display,
                "camera_configs": list(dlg.camera_configs),
            }
            self.products.append(product)
            self._switch_product(product)

    def _open_manage_product(self):
        """点击「管理产品」：弹出产品管理窗口。"""
        dlg = ProductManagerDialog(self.products, self)
        dlg.exec()

    def _switch_product(self, product: dict):
        """切换产品：更新顶部状态栏的「当前产品」标签窗体。"""
        self.current_product = product
        self._prod_chip_type.setText(self._prod_display_type(product))
        self._prod_chip_model.setText(self._prod_display_model(product))
        prod_view = getattr(self, "production", None)
        if prod_view is not None:
            prod_view._report_product = product   # 同步「生产报表」筛选数据示例值
        self._align_header_buttons()

    @staticmethod
    def _prod_display_type(product: dict) -> str:
        """顶部信息栏「产品类型」窗体内容：优先自定义显示名，缺省回退默认类型。"""
        if not product:
            return ""
        return (product.get("custom_type_display") or "").strip() or product.get("product_type", "") or ""

    @staticmethod
    def _prod_display_model(product: dict) -> str:
        """顶部信息栏「产品型号」窗体内容：优先自定义显示名，缺省回退默认型号。"""
        if not product:
            return ""
        return (product.get("custom_model_display") or "").strip() or product.get("product_model", "") or ""

    def _software_display_name(self):
        """顶部信息栏显示的软件名称（与窗口标题一致）。"""
        return (self.user_manager.software_name or "").strip() or "电子元件视觉检测系统"

    def _sync_software_name(self):
        """窗口标题同步为已保存的软件名称（来自用户管理器，超级管理员可在「设备设置」中修改）。"""
        name = self._software_display_name()
        self.setWindowTitle(name)
        # 顶部信息栏左侧的软件名称标签同步刷新
        if getattr(self, "lbl_sw_name", None) is not None:
            self.lbl_sw_name.setText(name)

    def _make_app_icon(self, size: int) -> QPixmap:
        """绘制应用窗口标题栏图标：橙色圆角方块 + 白色 ZiGAA 字样。"""
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        bg = QColor(COLORS["accent_orange"])

        # 橙色圆角方块背景
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)

        # 白色 ZiGAA 字样（自适应缩放、居中）
        self._paint_wordmark(p, size, "ZiGAA", QColor("#FFFFFF"))

        p.end()
        return pm

    def _paint_wordmark(self, p, size, text, color):
        """在正方形画布内居中绘制自适应缩放的单词字样。"""
        margin = size * 0.12
        max_w = size - 2 * margin
        max_h = size - 2 * margin
        font = QFont("Microsoft YaHei", int(size * 0.6))
        font.setBold(True)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        p.setFont(font)
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(text)
        h = fm.height()
        scale = min(max_w / w, max_h / h)
        font.setPointSizeF(font.pointSizeF() * scale)
        p.setFont(font)
        p.setPen(color)
        p.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, text)

    def _align_header_buttons(self):
        """将顶部四个操作按钮的左边缘与下方「生产信息」浮动面板左边缘对齐。

        生产信息面板在 production view 中以绝对坐标布局，其 x 即为与 header 同源的
        内容左偏移；据此调整按钮组左侧占位宽度，使两者左对齐。
        """
        prod = getattr(self, "production", None)
        if prod is None or not getattr(prod, "panels", None) or len(prod.panels) < 2:
            return
        info = prod.panels[1]  # 「生产信息」面板
        info_x = info.x()
        if info_x <= 0:
            return
        # header 内容区起点相对 content 左缘还有 16px（content 外边距）+ 16px（header 内边距）
        label_w = self.lbl_product_header.sizeHint().width()
        gap = self._header_layout.spacing()
        spacer_w = info_x - label_w - gap - 16
        if spacer_w < 0:
            spacer_w = 0
        self._header_btn_spacer.changeSize(spacer_w, 0,
                                           QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self._header_layout.invalidate()

    def showEvent(self, event):
        super().showEvent(event)
        # 等子部件完成首轮布局（含 production view 的面板定位）后再对齐按钮
        QTimer.singleShot(0, self._align_header_buttons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._align_header_buttons()


def run():
    app = QApplication(sys.argv)
    # 任务栏分组标识（须在创建窗口前设置，否则部分环境任务栏图标显示为空白）
    _set_windows_app_id()
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    window = MainWindow()
    # 应用级图标：主窗口与各弹窗统一，任务栏图标更可靠
    app.setWindowIcon(window._app_icon)
    window.show()
    sys.exit(app.exec())
