"""用户中心相关对话框：登录、用户中心、改密、用户管理、权限配置、设备编码。

统一蓝底浅灰风格，与产品管理弹窗保持一致。
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QTableWidget, QTableWidgetItem, QComboBox, QCheckBox, QGridLayout,
    QMessageBox, QAbstractItemView, QWidget, QSizePolicy, QStackedWidget,
    QScrollArea, QHeaderView, QFileDialog,
)

from user_manager import (
    UserManager, CATEGORIES, PERMISSIONS,
)

# 配色（与全局暗色主题 / 其它功能模块卡片一致：暗底 + 卡片 + 白字 + 橙色主操作）
BLUE = "#4261FF"            # 用户中心品牌色（导航高亮 / 信息条）
BLUE_HOVER = "#5A78FF"
BLUE_PRESS = "#3450E0"
PRIMARY = "#E95420"         # 主操作按钮（与其它功能模块一致）
PRIMARY_HOVER = "#FF6A33"
PRIMARY_PRESS = "#C8431A"
LIGHT_BG = "#1A1B1F"        # 窗体背景 = 暗底
WHITE = "#2A2D35"           # 卡片 / 面板背景
TEXT_DARK = "#FFFFFF"       # 主文字
TEXT_GRAY = "#9CA3AF"       # 次要文字
GREEN = "#0D822B"
RED = "#C81435"
NAV_ACTIVE_BG = "#26304F"   # 导航选中态底色（暗蓝）
NAV_ACTIVE_TXT = "#8FA8FF"  # 导航选中态文字（亮蓝）

# 权限配置勾选框：显式绘制指示块，暗底上已勾选也能清晰看见
CHECK_QSS = (
    "QCheckBox { spacing: 6px; color: #FFFFFF; }"
    "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; }"
    "QCheckBox::indicator:unchecked { "
    "border: 1px solid #3A3E47; background-color: #1A1B1F; }"
    "QCheckBox::indicator:checked { "
    "border: 1px solid #4261FF; background-color: #4261FF; }"
    "QCheckBox::indicator:disabled { "
    "border: 1px solid #3A3E47; background-color: #23252B; }"
    "QCheckBox::indicator:checked:disabled { "
    "border: 1px solid #3450E0; background-color: #3450E0; }"
)


def _yahei(size, bold=False):
    f = QFont("Microsoft YaHei", size)
    f.setBold(bold)
    return f


def _input_style():
    return (
        "QLineEdit { background-color: #1A1B1F; border: 1px solid #3A3E47; "
        "border-radius: 4px; padding: 4px 8px; font-size: 12px; color: #FFFFFF; }"
        "QLineEdit:focus { border: 1px solid #4261FF; }"
    )


def _combo_style():
    return (
        "QComboBox { background-color: #1A1B1F; border: 1px solid #3A3E47; "
        "border-radius: 4px; padding: 2px 8px; font-size: 12px; color: #FFFFFF; }"
        "QComboBox:focus, QComboBox:hover { border: 1px solid #4261FF; }"
        "QComboBox::drop-down { subcontrol-origin: padding; "
        "subcontrol-position: top right; width: 22px; border: none; }"
        "QComboBox QAbstractItemView { border: 1px solid #3A3E47; "
        "background-color: #2A2D35; color: #FFFFFF; "
        "selection-background-color: #4261FF; outline: 0; }"
    )


def _btn_primary():
    return (
        f"QPushButton {{ background-color: {PRIMARY}; color: white; border: none; "
        f"border-radius: 4px; font-size: 12px; padding: 0 14px; }}"
        f"QPushButton:hover {{ background-color: {PRIMARY_HOVER}; }}"
        f"QPushButton:pressed {{ background-color: {PRIMARY_PRESS}; }}"
    )


def _btn_neutral():
    return (
        "QPushButton { background-color: #2A2D35; color: #FFFFFF; "
        "border: 1px solid #3A3E47; border-radius: 4px; "
        "font-size: 12px; padding: 0 14px; }"
        "QPushButton:hover { background-color: #3A3E47; }"
    )


def _btn_green():
    return (
        f"QPushButton {{ background-color: {GREEN}; color: white; border: none; "
        f"border-radius: 4px; font-size: 12px; padding: 0 14px; }}"
        f"QPushButton:hover {{ background-color: #0B6E25; }}"
    )


def _btn_red():
    return (
        f"QPushButton {{ background-color: {RED}; color: white; border: none; "
        f"border-radius: 4px; font-size: 12px; padding: 0 14px; }}"
        f"QPushButton:hover {{ background-color: #A6102C; }}"
    )


def _all_perm_btn_style(on: bool):
    """「权限全部开启」切换按钮：开启=绿，关闭=红。"""
    color = GREEN if on else RED
    hover = "#0B6E25" if on else "#A6102C"
    return (
        f"QPushButton {{ background-color: {color}; color: white; border: none; "
        f"border-radius: 4px; font-size: 11px; padding: 0 14px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


# ---------------------------------------------------------------------------
# 通用小组件
# ---------------------------------------------------------------------------
def _kv(k, v):
    """标签-值横向行（固定标签宽，值靠左）。"""
    row = QHBoxLayout()
    lk = QLabel(k)
    lk.setFixedWidth(72)
    lk.setFont(_yahei(11, True))
    lk.setStyleSheet(f"color: {TEXT_GRAY};")
    lv = QLabel(str(v))
    lv.setFont(_yahei(11))
    lv.setStyleSheet(f"color: {TEXT_DARK};")
    row.addWidget(lk)
    row.addWidget(lv)
    row.addStretch()
    return row


def _permission_breakdown(manager: "UserManager", user: dict) -> QWidget:
    """某用户的全部权限明细（逐项列出，带 有/无 徽标），只读。"""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for key in PERMISSIONS:
        row = QHBoxLayout()
        row.setSpacing(8)
        lab = QLabel(PERMISSIONS[key])
        lab.setFixedWidth(96)
        lab.setFont(_yahei(10))
        lab.setStyleSheet(f"color: {TEXT_DARK};")
        yes = manager.can(user, key)
        badge = QLabel("有" if yes else "无")
        badge.setFixedWidth(40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "color: white; font-size: 11px; border-radius: 3px; padding: 1px 0;" +
            (f"background-color: {GREEN};" if yes else f"background-color: {RED};"))
        row.addWidget(lab)
        row.addWidget(badge)
        row.addStretch()
        lay.addLayout(row)
    return box


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------
class LoginDialog(QDialog):
    def __init__(self, manager: UserManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.user = None
        self.setWindowTitle("用户登录")
        self.setFixedSize(360, 230)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        title = QLabel("用户登录")
        title.setFont(_yahei(15, True))
        title.setStyleSheet(f"color: {TEXT_DARK};")
        root.addWidget(title)

        sub = QLabel("演示账号：admin / admin123（超级管理员）；operator01 / 123456（操作员）")
        sub.setFont(_yahei(9))
        sub.setStyleSheet(f"color: {TEXT_GRAY};")
        root.addWidget(sub)

        row1 = QHBoxLayout()
        l1 = QLabel("用户名")
        l1.setFixedWidth(56)
        l1.setFont(_yahei(11))
        candidates = manager.recent_candidates()
        self.user_combo = QComboBox()
        self.user_combo.setEditable(True)
        self.user_combo.setFixedHeight(30)
        self.user_combo.setMinimumWidth(200)
        self.user_combo.setStyleSheet(_combo_style())
        self.user_combo.addItems(candidates)
        default = manager.get_default_login()
        if default and default in candidates:
            self.user_combo.setCurrentText(default)
        else:
            self.user_combo.setCurrentText("")
        self.user_combo.lineEdit().setPlaceholderText("选择或输入用户名")
        row1.addWidget(l1)
        row1.addWidget(self.user_combo, 1)

        row2 = QHBoxLayout()
        l2 = QLabel("密码")
        l2.setFixedWidth(56)
        l2.setFont(_yahei(11))
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setFixedHeight(30)
        self.pwd_edit.setStyleSheet(_input_style())
        self.pwd_edit.returnPressed.connect(self._on_login)
        row2.addWidget(l2)
        row2.addWidget(self.pwd_edit)

        root.addLayout(row1)
        root.addLayout(row2)
        root.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(32)
        cancel.setFixedWidth(90)
        cancel.setStyleSheet(_btn_neutral())
        cancel.clicked.connect(self.reject)
        ok = QPushButton("登录")
        ok.setFixedHeight(32)
        ok.setFixedWidth(90)
        ok.setStyleSheet(_btn_primary())
        ok.clicked.connect(self._on_login)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)
        self.user_combo.setFocus()
        # 鼠标在用户名输入框内单击：弹出最近登录的 5 个账号；再次单击收起，
        # 方便手动输入用户名（不影响手动登录）。不监听聚焦/鼠标移入，避免遮挡输入。
        self.user_combo.lineEdit().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.user_combo.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            # 仅在未展开时弹出最近登录账号；已展开时交给 Qt 默认行为
            # （再次点击输入框即收起），避免遮挡输入、不影响手动登录。
            if not self.user_combo.view().isVisible():
                self.user_combo.showPopup()
        return super().eventFilter(obj, event)

    def _on_login(self):
        u = self.user_combo.currentText().strip()
        p = self.pwd_edit.text()
        if not u or not p:
            QMessageBox.information(self, "提示", "请输入用户名和密码。")
            return
        user = self.manager.authenticate(u, p)
        if user is None:
            QMessageBox.warning(self, "登录失败", "用户名或密码错误。")
            return
        self.manager.record_login(u)
        self.user = user
        self.accept()


# ---------------------------------------------------------------------------
# 修改 / 重置密码
# ---------------------------------------------------------------------------
class ChangePasswordDialog(QDialog):
    def __init__(self, manager: UserManager, user: dict, parent=None,
                 is_self: bool = True):
        super().__init__(parent)
        self.manager = manager
        self.user = user
        self.is_self = is_self
        self.setWindowTitle("修改密码" if is_self else f"重置密码 - {user['username']}")
        self.setFixedSize(360, 250)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        info = QLabel(f"用户：{user['username']}（{user['category']}）")
        info.setFont(_yahei(11))
        info.setStyleSheet(f"color: {TEXT_DARK};")
        root.addWidget(info)

        def _row(label_text):
            row = QHBoxLayout()
            lab = QLabel(label_text)
            lab.setFixedWidth(72)
            lab.setFont(_yahei(11))
            ed = QLineEdit()
            ed.setEchoMode(QLineEdit.EchoMode.Password)
            ed.setFixedHeight(30)
            ed.setStyleSheet(_input_style())
            row.addWidget(lab)
            row.addWidget(ed)
            return row, ed

        r1, self.pwd1 = _row("新密码")
        r2, self.pwd2 = _row("确认密码")
        root.addLayout(r1)
        root.addLayout(r2)
        root.addStretch()

        tip = QLabel("密码长度至少 6 位。")
        tip.setFont(_yahei(9))
        tip.setStyleSheet(f"color: {TEXT_GRAY};")
        root.addWidget(tip)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(32)
        cancel.setFixedWidth(90)
        cancel.setStyleSheet(_btn_neutral())
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确认")
        ok.setFixedHeight(32)
        ok.setFixedWidth(90)
        ok.setStyleSheet(_btn_primary())
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _on_ok(self):
        p1 = self.pwd1.text()
        p2 = self.pwd2.text()
        if len(p1) < 6:
            QMessageBox.information(self, "提示", "密码长度至少 6 位。")
            return
        if p1 != p2:
            QMessageBox.warning(self, "提示", "两次输入的密码不一致。")
            return
        if self.is_self:
            ok_flag, msg = self.manager.change_own_password(
                self.user["username"], p1)
        else:
            ok_flag, msg = self.manager.reset_password(
                self.user["username"], p1)
        if ok_flag:
            QMessageBox.information(self, "成功", msg)
            self.accept()
        else:
            QMessageBox.warning(self, "失败", msg)


# ---------------------------------------------------------------------------
# 用户中心
# ---------------------------------------------------------------------------
class UserCenterDialogA(QDialog):
    def __init__(self, manager: UserManager, user: dict, parent=None,
                 device_code_callback=None):
        super().__init__(parent)
        self.manager = manager
        self.current_user = user
        self.switch_requested = False
        self._device_cb = device_code_callback or (lambda v: None)
        self.setWindowTitle("用户中心")
        self.setFixedSize(440, 660)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("用户中心")
        title.setFont(_yahei(15, True))
        title.setStyleSheet(f"color: {TEXT_DARK};")
        root.addWidget(title)

        # 当前用户信息卡片（逐项展示，避免文字笼统 / 显示混乱）
        card = QFrame()
        card.setStyleSheet(
            f"background-color: {WHITE}; border: 1px solid #3A3E47; "
            f"border-radius: 6px; padding: 14px;")
        cl = QVBoxLayout(card)
        cl.setSpacing(8)
        u = user
        cl.addLayout(_kv("用户名", u["username"]))
        cl.addLayout(_kv("姓名", u["name"]))
        cl.addLayout(_kv("用户类别", u["category"]))
        if u.get("created_at"):
            cl.addLayout(_kv("创建时间", u["created_at"]))
        perm_label = QLabel("功能权限")
        perm_label.setFont(_yahei(11, True))
        perm_label.setStyleSheet(f"color: {TEXT_GRAY}; margin-top: 4px;")
        cl.addWidget(perm_label)
        cl.addWidget(_permission_breakdown(manager, u))
        root.addWidget(card, 1)  # 卡片占满中间，按钮/登录条贴底，无灰底空白

        # 功能按钮网格
        grid = QGridLayout()
        grid.setSpacing(10)
        self.btn_change_pwd = self._action_btn("修改密码", self._on_change_pwd)
        self.btn_user_manage = self._action_btn("用户管理", self._on_user_manage)
        self.btn_perm = self._action_btn("权限配置", self._on_perm)
        self.btn_device = self._action_btn("设备设置", self._on_device)
        self.btn_switch = self._action_btn("切换用户 / 退出登录",
                                           self._on_switch, style=_btn_neutral())
        grid.addWidget(self.btn_change_pwd, 0, 0)
        grid.addWidget(self.btn_user_manage, 0, 1)
        grid.addWidget(self.btn_perm, 1, 0)
        grid.addWidget(self.btn_device, 1, 1)
        grid.addWidget(self.btn_switch, 2, 0, 1, 2)
        root.addLayout(grid)

        # 底部当前登录信息条（填充原空白区域，减少留白）
        login_bar = QFrame()
        login_bar.setStyleSheet(
            f"background-color: {BLUE}; border-radius: 6px;")
        lb = QHBoxLayout(login_bar)
        lb.setContentsMargins(14, 9, 14, 9)
        lb.setSpacing(10)
        icon = QLabel("👤")
        icon.setFont(_yahei(16))
        icon.setStyleSheet("color: white;")
        lb.addWidget(icon)
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        t1 = QLabel("当前登录用户")
        t1.setFont(_yahei(9))
        t1.setStyleSheet("color: rgba(255,255,255,0.8);")
        t2 = QLabel(f"{u['name']}　（{u['category']}）")
        t2.setFont(_yahei(13, True))
        t2.setStyleSheet("color: white;")
        info_col.addWidget(t1)
        info_col.addWidget(t2)
        lb.addLayout(info_col)
        lb.addStretch()
        sub = QLabel(f"账号：{u['username']}")
        sub.setFont(_yahei(10))
        sub.setStyleSheet("color: rgba(255,255,255,0.85);")
        lb.addWidget(sub)
        root.addWidget(login_bar)

        # 按权限显隐（设备编码仅超级管理员）
        self.btn_user_manage.setVisible(manager.can(u, "user_manage"))
        self.btn_perm.setVisible(manager.can(u, "perm_config"))
        self.btn_device.setVisible(manager.can(u, "device_code"))

    def _action_btn(self, text, slot, style=None):
        btn = QPushButton(text)
        btn.setFixedHeight(38)
        btn.setFont(_yahei(12))
        btn.setStyleSheet(style or _btn_primary())
        btn.clicked.connect(slot)
        return btn

    def _on_change_pwd(self):
        ChangePasswordDialog(self.manager, self.current_user, self, is_self=True).exec()

    def _on_user_manage(self):
        UserManageDialog(self.manager, self).exec()

    def _on_perm(self):
        PermissionConfigDialog(self.manager, self).exec()

    def _on_device(self):
        can_name = self.manager.can(self.current_user, "device_software_name")
        DeviceCodeDialog(self.manager, self, on_saved=self._device_cb,
                         can_edit_software_name=can_name).exec()

    def _on_switch(self):
        self.switch_requested = True
        self.accept()


# ---------------------------------------------------------------------------
# 用户中心 B 版：左侧标签导航 + 右侧内容（设置面板式，窗口更大、可滚动）
# ---------------------------------------------------------------------------
class UserCenterDialogB(QDialog):
    def __init__(self, manager: UserManager, user: dict, parent=None,
                 device_code_callback=None):
        super().__init__(parent)
        self.manager = manager
        self.current_user = user
        self.switch_requested = False
        self._device_cb = device_code_callback or (lambda v: None)
        self.setWindowTitle("用户中心")
        self.setFixedSize(640, 560)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 上部分：左侧导航 + 右侧内容 ----
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)

        nav = QFrame()
        nav.setFixedWidth(152)
        nav.setStyleSheet(
            f"background-color: {WHITE}; border-right: 1px solid #3A3E47;")
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(0)
        nv.setAlignment(Qt.AlignmentFlag.AlignTop)

        brand = QLabel("用户中心")
        brand.setFont(_yahei(15, True))
        brand.setStyleSheet(f"color: {TEXT_DARK}; padding: 18px 18px 14px;")
        nv.addWidget(brand)

        self._nav_map = {}
        for key, icon, label in [
            ("profile", "👤", "个人信息"),
            ("security", "🔒", "账号安全"),
            ("user_manage", "👥", "用户管理"),
            ("perm_config", "🛡", "权限配置"),
            ("device", "🖥", "设备配置"),
        ]:
            b = QPushButton(f"{icon}  {label}")
            b.setFixedHeight(44)
            b.setStyleSheet(self._nav_style(False))
            b.clicked.connect(lambda _, k=key: self._select(k))
            nv.addWidget(b)
            self._nav_map[key] = b
        nv.addStretch(1)

        top.addWidget(nav)

        # ---- 右侧内容 ----
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {LIGHT_BG};")
        self._stack.addWidget(self._page_profile())
        self._stack.addWidget(self._page_security())
        self._stack.addWidget(self._page_user_manage())
        self._stack.addWidget(self._page_perm_config())
        self._stack.addWidget(self._page_device())
        top.addWidget(self._stack, 1)

        root.addLayout(top, 1)

        # ---- 底部蓝色信息/操作栏（常驻，不会被右侧内容覆盖） ----
        bottom = QFrame()
        bottom.setStyleSheet(f"background-color: {BLUE};")
        bottom.setFixedHeight(60)
        bh = QHBoxLayout(bottom)
        bh.setContentsMargins(16, 0, 12, 0)
        bh.setSpacing(8)

        info = QVBoxLayout()
        info.setSpacing(1)
        info.addWidget(self._mini("当前登录", 9, "rgba(255,255,255,0.8)"))
        info.addWidget(self._mini(
            f"{user['name']}（{user['category']}）", 13, "white", bold=True))
        bh.addLayout(info)
        bh.addStretch(1)

        logout = QPushButton("切换用户 / 退出登录")
        logout.setFixedHeight(32)
        logout.setFont(_yahei(11))
        logout.setStyleSheet(
            f"QPushButton {{ background-color: rgba(255,255,255,0.18); "
            f"color: white; border: 1px solid rgba(255,255,255,0.35); "
            f"border-radius: 4px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background-color: rgba(255,255,255,0.30); }}")
        logout.clicked.connect(self._on_switch)
        bh.addWidget(logout)

        root.addWidget(bottom)

        # 管理页与个人信息/账号安全同级内嵌，按权限显隐
        self._page_index = {
            "profile": 0, "security": 1, "user_manage": 2,
            "perm_config": 3, "device": 4,
        }
        self._active_page = "profile"
        self._nav_map["user_manage"].setVisible(
            manager.can(user, "user_manage"))
        self._nav_map["perm_config"].setVisible(
            manager.can(user, "perm_config"))
        self._nav_map["device"].setVisible(
            manager.can(user, "device_code")
            or manager.can(user, "device_software_name"))
        self._select("profile")

    # ----- 辅助 -----
    def _mini(self, text, size, color, bold=False):
        l = QLabel(text)
        l.setFont(_yahei(size, bold))
        l.setStyleSheet(f"color: {color};")
        return l

    def _nav_style(self, active):
        return (
            f"QPushButton {{ background-color: "
            f"{NAV_ACTIVE_BG if active else 'transparent'}; "
            f"color: {NAV_ACTIVE_TXT if active else TEXT_DARK}; border: none; "
            f"border-left: 3px solid {BLUE if active else 'transparent'}; "
            f"text-align: left; padding-left: 18px; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: #23252B; }}")

    def _select(self, key):
        self._active_page = key
        self._stack.setCurrentIndex(self._page_index[key])
        for k, b in self._nav_map.items():
            b.setStyleSheet(self._nav_style(k == key))

    def _panel(self, title_text):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; "
                             "border: none; }")

        page = QWidget()
        page.setStyleSheet("background-color: transparent;")
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(14)
        title = QLabel(title_text)
        title.setFont(_yahei(15, True))
        title.setStyleSheet(f"color: {TEXT_DARK};")
        v.addWidget(title)
        body = QVBoxLayout()
        body.setSpacing(12)
        v.addLayout(body)
        v.addStretch(1)
        scroll.setWidget(page)
        scroll._body = body
        return scroll

    def _fit_rows(self, table, n, row_h=32):
        """固定表格可视高度，使其恰好显示 n 行；超出部分走表格自身竖向滚动条。"""
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 显式设定每行高度（含 cell widget 的行不会自动收缩，必须手动设）
        for i in range(table.rowCount()):
            table.setRowHeight(i, row_h)
        hh = table.horizontalHeader().height()
        rc = table.rowCount()
        shown = min(rc, n)
        total = hh + shown * row_h + (4 if rc > n else 0) + 2
        table.setFixedHeight(total)

    def _avatar(self, text, size, color):
        f = QFrame()
        f.setFixedSize(size, size)
        f.setStyleSheet(
            f"QFrame {{ background-color: {color}; border-radius: {size // 2}px; }}")
        fl = QVBoxLayout(f)
        fl.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setFont(_yahei(int(size * 0.38), True))
        lab.setStyleSheet("color: white;")
        fl.addWidget(lab)
        return f

    def _hline(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #3A3E47;")
        return line

    def _permission_grid(self, manager, user):
        box = QWidget()
        lay = QGridLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(18)
        lay.setVerticalSpacing(9)
        for i, key in enumerate(PERMISSIONS):
            yes = manager.can(user, key)
            item = QHBoxLayout()
            item.setSpacing(6)
            dot = QLabel("●")
            dot.setFont(_yahei(9))
            dot.setStyleSheet(f"color: {GREEN if yes else '#9CA3AF'};")
            lab = QLabel(PERMISSIONS[key])
            lab.setFont(_yahei(11))
            lab.setStyleSheet(f"color: {TEXT_DARK if yes else '#9CA3AF'};")
            item.addWidget(dot)
            item.addWidget(lab)
            item.addStretch(1)
            w = QWidget()
            w.setLayout(item)
            lay.addWidget(w, i // 2, i % 2)
        return box

    def _page_profile(self):
        page = self._panel("个人信息")
        u, m = self.current_user, self.manager

        # ---- 头部：头像 + 姓名 + 类别徽标 ----
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(
            self._avatar((u["name"] or u["username"])[:1].upper(), 56, BLUE))
        hinfo = QVBoxLayout()
        hinfo.setSpacing(6)
        name = QLabel(u["name"])
        name.setFont(_yahei(17, True))
        name.setStyleSheet(f"color: {TEXT_DARK};")
        hinfo.addWidget(name)
        badge = QLabel(u["category"])
        badge.setFont(_yahei(11))
        badge.setStyleSheet(
            f"background-color: {NAV_ACTIVE_BG}; color: {NAV_ACTIVE_TXT}; "
            f"border-radius: 4px; padding: 3px 12px;")
        hbadge = QHBoxLayout()
        hbadge.addWidget(badge)
        hbadge.addStretch()
        hinfo.addLayout(hbadge)
        head.addLayout(hinfo)
        head.addStretch(1)
        page._body.addLayout(head)

        page._body.addWidget(self._hline())

        # ---- 信息 2×2 网格 ----
        granted = sum(1 for k in PERMISSIONS if m.can(u, k))
        grid = QGridLayout()
        grid.setContentsMargins(2, 4, 2, 4)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        for i, (k, v) in enumerate([
            ("用户名", u["username"]),
            ("用户类别", u["category"]),
            ("创建时间", u.get("created_at") or "—"),
            ("功能权限", f"{granted} / {len(PERMISSIONS)} 项"),
        ]):
            grid.addLayout(_kv(k, v), i // 2, i % 2)
        page._body.addLayout(grid)

        page._body.addWidget(self._hline())

        # ---- 功能权限明细（彩色点网格） ----
        pl = QLabel("功能权限明细")
        pl.setFont(_yahei(11, True))
        pl.setStyleSheet(f"color: {TEXT_GRAY};")
        page._body.addWidget(pl)
        page._body.addWidget(self._permission_grid(m, u))
        page._body.addStretch(1)
        return page

    def _page_security(self):
        page = self._panel("账号安全")
        b1 = QPushButton("修改密码")
        b1.setFixedHeight(40)
        b1.setFont(_yahei(12))
        b1.setStyleSheet(_btn_primary())
        b1.clicked.connect(lambda: ChangePasswordDialog(
            self.manager, self.current_user, self, is_self=True).exec())
        page._body.addWidget(b1)
        b2 = QPushButton("切换用户 / 退出登录")
        b2.setFixedHeight(40)
        b2.setFont(_yahei(12))
        b2.setStyleSheet(_btn_neutral())
        b2.clicked.connect(self._on_switch)
        page._body.addWidget(b2)
        return page

    def _center(self, widget):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(widget)
        return box

    # ---------- 用户管理（内嵌，不弹窗） ----------
    def _page_user_manage(self):
        page = self._panel("用户管理")
        self._um_table = QTableWidget()
        self._um_table.setColumnCount(5)
        self._um_table.setHorizontalHeaderLabels(
            ["用户名", "姓名", "用户类别", "创建时间", "默认"])
        # 用表格自带表头（蓝色），列宽随面板自适应，避免横向被裁
        self._um_table.horizontalHeader().setVisible(True)
        self._um_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._um_table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background-color: #23252B; color: white; "
            f"padding: 5px; font-size: 11px; font-weight: 600; border: none; "
            f"border-right: 1px solid #3A3E47; }}")
        self._um_table.verticalHeader().setVisible(False)
        self._um_table.verticalHeader().setDefaultSectionSize(32)
        self._um_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._um_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._um_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._um_table.setStyleSheet(
            f"QTableWidget {{ background-color: {WHITE}; border: 1px solid #3A3E47; "
            f"gridline-color: #3A3E47; color: {TEXT_DARK}; font-size: 12px; }}"
            f"QTableWidget::item {{ padding: 6px; border-bottom: 1px solid #3A3E47; }}"
            # 选中行：醒目蓝底 + 白色加粗文字，避免与底色对比不明显
            f"QTableWidget::item:selected {{ background-color: #E95420; "
            f"color: white; font-weight: 600; }}")
        for i, w in enumerate([120, 110, 130, 150, 60]):
            self._um_table.setColumnWidth(i, w)
        self._um_table.cellDoubleClicked.connect(
            lambda r, c: self._um_view())
        page._body.addWidget(self._um_table)
        self._um_refresh()
        self._fit_rows(self._um_table, 10, 32)

        # 第一行按钮：设为默认登录 / 新增用户 / 编辑用户 / 删除用户 / 重置密码
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for txt, slot, st in [
            ("设为默认登录", self._um_set_default, _btn_primary()),
            ("新增用户", self._um_add, _btn_primary()),
            ("编辑用户", self._um_edit, _btn_primary()),
            ("删除用户", self._um_delete, _btn_red()),
            ("重置密码", self._um_reset, _btn_green()),
        ]:
            btn = QPushButton(txt)
            btn.setFixedHeight(30)
            btn.setFont(_yahei(10))
            btn.setStyleSheet(st)
            btn.clicked.connect(slot)
            row1.addWidget(btn, 1)   # 等宽分布，整行对齐
        page._body.addLayout(row1)

        # 第二行按钮：导入 / 导出（左对齐）
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for txt, slot, st in [
            ("导入", self._um_import, _btn_neutral()),
            ("导出", self._um_export, _btn_neutral()),
        ]:
            btn = QPushButton(txt)
            btn.setFixedHeight(30)
            btn.setFont(_yahei(10))
            btn.setStyleSheet(st)
            btn.clicked.connect(slot)
            row2.addWidget(btn)
        row2.addStretch()
        page._body.addLayout(row2)
        return page

    def _um_refresh(self):
        t = self._um_table
        t.setRowCount(len(self.manager.users))
        default = self.manager.get_default_login()
        for r, u in enumerate(self.manager.users):
            for c, key in enumerate(
                    ["username", "name", "category", "created_at"]):
                item = QTableWidgetItem(str(u.get(key, "")))
                item.setFont(_yahei(10))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(r, c, item)
            # 第 5 列：默认登录用户以 ★ 标记（金色）
            star = QTableWidgetItem("★" if u.get("username") == default else "")
            star.setFont(_yahei(10))
            star.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            star.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if u.get("username") == default:
                star.setForeground(QColor("#F9AA0B"))
            t.setItem(r, 4, star)
        if self.manager.users:
            t.selectRow(0)

    def _um_selected_row(self):
        sel = self._um_table.selectedIndexes()
        return sel[0].row() if sel else -1

    def _um_view(self):
        row = self._um_selected_row()
        if row < 0:
            return
        UserDetailDialog(self.manager, self.manager.users[row], self).exec()

    def _um_add(self):
        dlg = UserEditDialog(self.manager, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._um_refresh()

    def _um_edit(self):
        row = self._um_selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的用户。")
            return
        dlg = UserEditDialog(self.manager, self.manager.users[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._um_refresh()

    def _um_delete(self):
        row = self._um_selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的用户。")
            return
        u = self.manager.users[row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除用户「{u['username']}（{u['name']}）」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            ok_flag, msg = self.manager.delete_user(u["username"])
            if ok_flag:
                self._um_refresh()
            else:
                QMessageBox.warning(self, "失败", msg)

    def _um_reset(self):
        row = self._um_selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要重置密码的用户。")
            return
        u = self.manager.users[row]
        ChangePasswordDialog(self.manager, u, self, is_self=False).exec()

    def _um_set_default(self):
        row = self._um_selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要设为默认登录的用户。")
            return
        u = self.manager.users[row]
        if self.manager.set_default_login(u["username"]):
            self._um_refresh()
            QMessageBox.information(
                self, "已设置",
                f"已将「{u['username']}（{u['name']}）」设为默认登录用户。\n"
                f"下次打开登录框将自动选中该账号。")

    def _um_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入用户", "", "用户文件 (*.json *.csv);;JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        added, updated, skipped = self.manager.import_users(path)
        self._um_refresh()
        QMessageBox.information(
            self, "导入完成",
            f"导入结果：新增 {added} 个、更新 {updated} 个、跳过 {skipped} 个。")

    def _um_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出用户", "users_export",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        n = self.manager.export_users(path)
        QMessageBox.information(self, "导出完成", f"已导出 {n} 个用户到：\n{path}")

    # ---------- 权限配置（内嵌） ----------
    def _page_perm_config(self):
        page = self._panel("权限配置")
        m = self.manager
        note = QLabel("说明：不同用户类别的功能权限不同，由超级管理员统一配置。"
                      "「设备设置」仅超级管理员可用，已锁定。")
        note.setFont(_yahei(10))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_GRAY};")
        page._body.addWidget(note)

        # 行=权限功能，列=用户类别（与原先互换）
        table = QTableWidget(len(PERMISSIONS), len(CATEGORIES))
        table.setHorizontalHeaderLabels(CATEGORIES)
        table.setVerticalHeaderLabels([PERMISSIONS[k] for k in PERMISSIONS])
        # 表头取消底色（透明）、文字改黑色，避免蓝底白字与整体风格冲突
        _perm_header_qss = (
            "QHeaderView::section { background-color: transparent; "
            "color: #FFFFFF; padding: 4px; font-size: 11px; font-weight: 600; "
            "border: 1px solid #3A3E47; }")
        table.horizontalHeader().setStyleSheet(_perm_header_qss)
        table.verticalHeader().setStyleSheet(_perm_header_qss)
        table.setStyleSheet(
            f"QTableWidget {{ background-color: {WHITE}; "
            f"gridline-color: #3A3E47; color: #FFFFFF; }}"
            f"QTableWidget::item {{ padding: 4px; }}")
        # 列宽随面板自适应，避免横向被裁
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(46)
        self._perm_checks = {}
        for r, pk in enumerate(PERMISSIONS):
            for c, cat in enumerate(CATEGORIES):
                cb = QCheckBox()
                cb.setChecked(m.category_permissions[cat][pk])
                cb.setStyleSheet(CHECK_QSS)
                if pk == "device_code":
                    cb.setEnabled(False)
                self._perm_checks[(cat, pk)] = cb
                table.setCellWidget(r, c, self._center(cb))
        table.verticalHeader().setDefaultSectionSize(34)
        page._body.addWidget(table)
        self._fit_rows(table, 10, 34)

        # 「权限全部开启」切换按钮：默认关闭（红），点击后勾选所有类别的全部权限
        self._all_on = False
        self._all_btn = QPushButton("权限全部开启")
        self._all_btn.setFixedHeight(32)
        self._all_btn.setFont(_yahei(11))
        self._all_btn.setStyleSheet(_all_perm_btn_style(False))
        self._all_btn.clicked.connect(self._on_toggle_all_perms)

        save_row = QHBoxLayout()
        save_row.addWidget(self._all_btn)
        save_row.addStretch()
        save = QPushButton("保存配置")
        save.setFixedHeight(32)
        save.setFixedWidth(110)
        save.setFont(_yahei(11))
        save.setStyleSheet(_btn_primary())
        save.clicked.connect(self._perm_save)
        save_row.addWidget(save)
        page._body.addLayout(save_row)
        return page

    def _on_toggle_all_perms(self):
        self._all_on = not self._all_on
        for (cat, pk), cb in self._perm_checks.items():
            if pk == "device_code":
                continue
            cb.setChecked(self._all_on)
        self._all_btn.setStyleSheet(_all_perm_btn_style(self._all_on))

    def _perm_save(self):
        m = self.manager
        for cat in CATEGORIES:
            for pk in PERMISSIONS:
                if pk == "device_code":
                    m.category_permissions[cat][pk] = (cat == "超级管理员")
                else:
                    m.category_permissions[cat][pk] = \
                        self._perm_checks[(cat, pk)].isChecked()
        m.save()
        QMessageBox.information(self, "已保存", "权限配置已更新。")

    # ---------- 设备配置（合并原「设置」的设备/软件信息） ----------
    def _page_device(self):
        page = self._panel("设备配置")
        u, m = self.current_user, self.manager
        can_name = m.can(u, "device_software_name")
        can_dev = m.can(u, "device_code")

        tip = QLabel("以下为示例设备与软件信息，仅相关权限用户可编辑。")
        tip.setFont(_yahei(10))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_GRAY};")
        page._body.addWidget(tip)

        self._dev_sw = QLineEdit(str(m.software_name))
        self._dev_sw.setFixedHeight(30)
        self._dev_sw.setStyleSheet(_input_style())
        self._dev_sw.setReadOnly(not can_name)
        page._body.addLayout(self._kv_row("软件名称", self._dev_sw))

        self._dev_edits = {}
        # 设备型号 / 出厂日期 / 设备功率：首次打开时展示示例输入信息，便于直接演示
        device_examples = {
            "设备编码": "",
            "设备名称": "",
            "产线编号": "",
            "设备型号": "VI-3000S",
            "出厂日期": "2025-01-20",
            "设备功率": "2.4 kW",
        }
        for key in ["设备编码", "设备名称", "产线编号", "设备型号", "出厂日期", "设备功率"]:
            ed = QLineEdit(str(m.device_code.get(key, device_examples.get(key, ""))))
            ed.setFixedHeight(30)
            ed.setStyleSheet(_input_style())
            ed.setReadOnly(not can_dev)
            self._dev_edits[key] = ed
            page._body.addLayout(self._kv_row(key, ed))

        # 软件操作锁定间隔（示例下拉，仅相关权限用户可编辑）
        self._lock_combo = QComboBox()
        self._lock_combo.addItems(
            ["1分钟", "5分钟", "10分钟", "30分钟", "60分钟"])
        idx = self._lock_combo.findText(m.lock_interval)
        self._lock_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._lock_combo.setFixedHeight(30)
        self._lock_combo.setStyleSheet(_combo_style())
        self._lock_combo.setDisabled(not (can_name or can_dev))
        page._body.addLayout(
            self._kv_row("软件操作锁定间隔", self._lock_combo, label_width=120))

        if can_name or can_dev:
            save_row = QHBoxLayout()
            save_row.addStretch()
            save = QPushButton("保存")
            save.setFixedHeight(36)
            save.setFixedWidth(90)
            save.setFont(_yahei(12))
            save.setStyleSheet(_btn_primary())
            save.clicked.connect(self._on_save_device)
            save_row.addWidget(save)
            page._body.addLayout(save_row)
        return page

    def _kv_row(self, label_text, widget, label_width=72):
        row = QHBoxLayout()
        lab = QLabel(label_text)
        lab.setFixedWidth(label_width)
        lab.setFont(_yahei(11))
        # 显式深色文字，避免继承全局暗色主题的白色文字（白底白字看不见）
        lab.setStyleSheet(f"color: {TEXT_DARK};")
        row.addWidget(lab)
        row.addWidget(widget)
        return row

    def _on_save_device(self):
        u = self.current_user
        values = {k: ed.text().strip() for k, ed in self._dev_edits.items()}
        self.manager.set_device_code(values)
        if self.manager.can(u, "device_software_name"):
            name = self._dev_sw.text().strip()
            if name:
                self.manager.set_software_name(name)
        self.manager.set_lock_interval(self._lock_combo.currentText())
        self._device_cb(values)
        QMessageBox.information(self, "成功", "设备配置已保存。")

    def _on_switch(self):
        self.switch_requested = True
        self.accept()


def make_user_center(manager: UserManager, user: dict, parent=None,
                     device_code_callback=None):
    """按 USER_CENTER_VARIANT 环境变量选择用户中心版本（默认 A）。

    A：单栏卡片堆叠（沿用原设计）；B：左侧导航 + 右侧内容（设置面板式）。
    入口脚本 main_a.py / main_b.py 会在导入 app 前烘焙该环境变量到对应 exe。
    """
    variant = os.environ.get("USER_CENTER_VARIANT", "A").upper()
    if variant == "B":
        return UserCenterDialogB(manager, user, parent, device_code_callback)
    return UserCenterDialogA(manager, user, parent, device_code_callback)


# ---------------------------------------------------------------------------
# 用户详情（只读，从用户管理列表双击进入）
# ---------------------------------------------------------------------------
class UserDetailDialog(QDialog):
    def __init__(self, manager: UserManager, user: dict, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.user = user
        self.setWindowTitle(f"用户详情 - {user['username']}")
        self.setFixedSize(440, 440)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("用户详情")
        title.setFont(_yahei(15, True))
        title.setStyleSheet(f"color: {TEXT_DARK};")
        root.addWidget(title)

        card = QFrame()
        card.setStyleSheet(
            f"background-color: {WHITE}; border: 1px solid #3A3E47; "
            f"border-radius: 6px; padding: 14px;")
        cl = QVBoxLayout(card)
        cl.setSpacing(8)
        u = user
        cl.addLayout(_kv("用户名", u["username"]))
        cl.addLayout(_kv("姓名", u["name"]))
        cl.addLayout(_kv("用户类别", u["category"]))
        if u.get("created_at"):
            cl.addLayout(_kv("创建时间", u["created_at"]))
        perm_label = QLabel("功能权限")
        perm_label.setFont(_yahei(11, True))
        perm_label.setStyleSheet(f"color: {TEXT_GRAY}; margin-top: 4px;")
        cl.addWidget(perm_label)
        cl.addWidget(_permission_breakdown(manager, u))
        root.addWidget(card)
        root.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        close = QPushButton("关闭")
        close.setFixedHeight(32)
        close.setFixedWidth(90)
        close.setStyleSheet(_btn_neutral())
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        root.addLayout(btns)


# ---------------------------------------------------------------------------
# 用户管理（新增 / 编辑 / 删除 / 重置密码）
# ---------------------------------------------------------------------------
class UserManageDialog(QDialog):
    def __init__(self, manager: UserManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("用户管理")
        self.setFixedSize(640, 440)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"background-color: {BLUE}; border-radius: 3px;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)
        for txt, w in [("用户名", 120), ("姓名", 120), ("用户类别", 140),
                       ("创建时间", 200)]:
            lab = QLabel(txt)
            lab.setFixedWidth(w)
            lab.setFont(_yahei(12, True))
            lab.setStyleSheet("color: white;")
            hl.addWidget(lab)
        hl.addStretch()
        root.addWidget(header)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["用户名", "姓名", "用户类别", "创建时间"])
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {WHITE}; border: 1px solid #3A3E47; "
            f"gridline-color: #3A3E47; color: {TEXT_DARK}; font-size: 12px; }}"
            f"QTableWidget::item {{ padding: 6px; border-bottom: 1px solid #3A3E47; }}"
            f"QTableWidget::item:selected {{ background-color: #E95420; }}"
        )
        for i, w in enumerate([120, 120, 140, 200]):
            self.table.setColumnWidth(i, w)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.cellDoubleClicked.connect(lambda r, c: self._on_view())
        root.addWidget(self.table, 1)
        self._refresh()

        # 第一行按钮：设为默认登录 / 新增用户 / 编辑用户 / 删除用户 / 重置密码
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        for txt, slot, st in [
            ("设为默认登录", self._on_set_default, _btn_primary()),
            ("新增用户", self._on_add, _btn_primary()),
            ("编辑用户", self._on_edit, _btn_primary()),
            ("删除用户", self._on_delete, _btn_red()),
            ("重置密码", self._on_reset, _btn_green()),
        ]:
            btn = QPushButton(txt)
            btn.setFixedHeight(32)
            btn.setFont(_yahei(11))
            btn.setStyleSheet(st)
            btn.clicked.connect(slot)
            row1.addWidget(btn, 1)   # 等宽分布，整行对齐
        root.addLayout(row1)

        # 第二行按钮：导入 / 导出（左对齐）
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        for txt, slot, st in [
            ("导入", self._on_import, _btn_neutral()),
            ("导出", self._on_export, _btn_neutral()),
        ]:
            btn = QPushButton(txt)
            btn.setFixedHeight(32)
            btn.setFont(_yahei(11))
            btn.setStyleSheet(st)
            btn.clicked.connect(slot)
            row2.addWidget(btn)
        row2.addStretch()
        root.addLayout(row2)

    def _refresh(self):
        self.table.setRowCount(len(self.manager.users))
        for r, u in enumerate(self.manager.users):
            for c, key in enumerate(["username", "name", "category", "created_at"]):
                item = QTableWidgetItem(str(u.get(key, "")))
                item.setFont(_yahei(11))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, c, item)
        self.table.resizeRowsToContents()
        if self.manager.users:
            self.table.selectRow(0)

    def _selected_row(self):
        sel = self.table.selectedIndexes()
        return sel[0].row() if sel else -1

    def _on_view(self):
        row = self._selected_row()
        if row < 0:
            return
        UserDetailDialog(self.manager, self.manager.users[row], self).exec()

    def _on_add(self):
        dlg = UserEditDialog(self.manager, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _on_edit(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的用户。")
            return
        dlg = UserEditDialog(self.manager, self.manager.users[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _on_delete(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的用户。")
            return
        u = self.manager.users[row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除用户「{u['username']}（{u['name']}）」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            ok_flag, msg = self.manager.delete_user(u["username"])
            if ok_flag:
                self._refresh()
            else:
                QMessageBox.warning(self, "失败", msg)

    def _on_reset(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要重置密码的用户。")
            return
        u = self.manager.users[row]
        ChangePasswordDialog(self.manager, u, self, is_self=False).exec()

    def _on_set_default(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要设为默认登录的用户。")
            return
        u = self.manager.users[row]
        if self.manager.set_default_login(u["username"]):
            QMessageBox.information(
                self, "已设置",
                f"已将「{u['username']}（{u['name']}）」设为默认登录用户。")

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入用户", "", "用户文件 (*.json *.csv);;JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        added, updated, skipped = self.manager.import_users(path)
        self._refresh()
        QMessageBox.information(
            self, "导入完成",
            f"导入结果：新增 {added} 个、更新 {updated} 个、跳过 {skipped} 个。")

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出用户", "users_export",
            "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        n = self.manager.export_users(path)
        QMessageBox.information(self, "导出完成", f"已导出 {n} 个用户到：\n{path}")


# ---------------------------------------------------------------------------
# 新增 / 编辑用户
# ---------------------------------------------------------------------------
class UserEditDialog(QDialog):
    def __init__(self, manager: UserManager, user: dict | None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.user = user  # None 表示新增
        self.setWindowTitle("编辑用户" if user else "新增用户")
        self.setFixedSize(360, 280)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)

        def _field(label_text, echo=False, readonly=False):
            row = QHBoxLayout()
            lab = QLabel(label_text)
            lab.setFixedWidth(64)
            lab.setFont(_yahei(11))
            ed = QLineEdit()
            if echo:
                ed.setEchoMode(QLineEdit.EchoMode.Password)
            if readonly:
                ed.setReadOnly(True)
            ed.setFixedHeight(30)
            ed.setStyleSheet(_input_style())
            row.addWidget(lab)
            row.addWidget(ed)
            return row, ed

        r0, self.username_edit = _field("用户名", readonly=(user is not None))
        r1, self.name_edit = _field("姓名")
        root.addLayout(r0)
        root.addLayout(r1)

        # 用户类别
        cat_row = QHBoxLayout()
        cl = QLabel("用户类别")
        cl.setFixedWidth(64)
        cl.setFont(_yahei(11))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATEGORIES)
        self.cat_combo.setFixedHeight(30)
        # 显式设置文字颜色，避免继承全局暗色主题的白色文字（白底白字看不见）
        self.cat_combo.setStyleSheet(_combo_style())
        cat_row.addWidget(cl)
        cat_row.addWidget(self.cat_combo, 1)
        root.addLayout(cat_row)

        r3, self.pwd_edit = _field("密码" if user is None else "新密码（留空不改）",
                                   echo=True)
        root.addLayout(r3)
        root.addStretch()

        if user is not None:
            self.username_edit.setText(user["username"])
            self.name_edit.setText(user["name"])
            idx = self.cat_combo.findText(user["category"])
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(32)
        cancel.setFixedWidth(90)
        cancel.setStyleSheet(_btn_neutral())
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setFixedHeight(32)
        ok.setFixedWidth(90)
        ok.setStyleSheet(_btn_primary())
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _on_ok(self):
        username = self.username_edit.text().strip()
        name = self.name_edit.text().strip() or username
        category = self.cat_combo.currentText()
        password = self.pwd_edit.text()
        if self.user is None:
            ok_flag, msg = self.manager.add_user(
                username, name, category, password)
        else:
            ok_flag, msg = self.manager.update_user(
                self.user["username"], name=name,
                category=category, password=password)
        if ok_flag:
            QMessageBox.information(self, "成功", msg)
            self.accept()
        else:
            QMessageBox.warning(self, "失败", msg)


# ---------------------------------------------------------------------------
# 权限配置（按用户类别）
# ---------------------------------------------------------------------------
class PermissionConfigDialog(QDialog):
    def __init__(self, manager: UserManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("权限配置（按用户类别）")
        self.setFixedSize(720, 420)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        note = QLabel("说明：不同用户类别的功能权限不同，由超级管理员统一配置。"
                      "「设备设置」仅超级管理员可用，已锁定。")
        note.setFont(_yahei(10))
        note.setStyleSheet(f"color: {TEXT_GRAY};")
        root.addWidget(note)

        self.table = QTableWidget(len(CATEGORIES), len(PERMISSIONS))
        self.table.setHorizontalHeaderLabels(
            [PERMISSIONS[k] for k in PERMISSIONS])
        self.table.setVerticalHeaderLabels(CATEGORIES)
        _perm_header_qss = (
            "QHeaderView::section { background-color: transparent; "
            "color: #FFFFFF; padding: 4px; font-size: 11px; font-weight: 600; "
            "border: 1px solid #3A3E47; }")
        self.table.horizontalHeader().setStyleSheet(_perm_header_qss)
        self.table.verticalHeader().setStyleSheet(_perm_header_qss)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {WHITE}; gridline-color: #3A3E47; "
            f"color: #FFFFFF; }}"
            f"QTableWidget::item {{ padding: 4px; }}"
        )
        for c, w in enumerate([90, 90, 110, 90, 90, 90, 110]):
            self.table.setColumnWidth(c, w)
        self.checks = {}
        for r, cat in enumerate(CATEGORIES):
            for c, pk in enumerate(PERMISSIONS):
                cb = QCheckBox()
                cb.setChecked(self.manager.category_permissions[cat][pk])
                if pk == "device_code":
                    cb.setEnabled(False)  # 仅超级管理员，强制锁定
                self.checks[(cat, pk)] = cb
                self.table.setCellWidget(r, c, self._center(cb))
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.table, 1)

        footer = QFrame()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(12)
        # 「权限全部开启」切换按钮：默认关闭（红），点击后勾选所有类别的全部权限
        self._all_on = False
        self._all_btn = QPushButton("权限全部开启")
        self._all_btn.setFixedHeight(32)
        self._all_btn.setFont(_yahei(11))
        self._all_btn.setStyleSheet(_all_perm_btn_style(False))
        self._all_btn.clicked.connect(self._on_toggle_all_perms)
        fl.addWidget(self._all_btn)
        fl.addStretch()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(32)
        cancel.setFixedWidth(90)
        cancel.setStyleSheet(_btn_neutral())
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存配置")
        ok.setFixedHeight(32)
        ok.setFixedWidth(110)
        ok.setStyleSheet(_btn_primary())
        ok.clicked.connect(self._on_save)
        fl.addWidget(cancel)
        fl.addWidget(ok)
        root.addWidget(footer)

    @staticmethod
    def _center(widget: QWidget) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(widget)
        return box

    def _on_toggle_all_perms(self):
        self._all_on = not self._all_on
        for (cat, pk), cb in self.checks.items():
            if pk == "device_code":
                continue
            cb.setChecked(self._all_on)
        self._all_btn.setStyleSheet(_all_perm_btn_style(self._all_on))

    def _on_save(self):
        new_perms = {}
        for cat in CATEGORIES:
            new_perms[cat] = {}
            for pk in PERMISSIONS:
                if pk == "device_code":
                    new_perms[cat][pk] = (cat == "超级管理员")
                else:
                    new_perms[cat][pk] = self.checks[(cat, pk)].isChecked()
        for cat in CATEGORIES:
            for pk in PERMISSIONS:
                self.manager.category_permissions[cat][pk] = new_perms[cat][pk]
        for cat in self.manager.category_permissions:
            self.manager.category_permissions[cat]["device_code"] = (
                cat == "超级管理员")
        self.manager.save()
        QMessageBox.information(self, "已保存", "权限配置已更新。")
        self.accept()


# ---------------------------------------------------------------------------
# 设备编码设置（仅超级管理员）
# ---------------------------------------------------------------------------
class DeviceCodeDialog(QDialog):
    def __init__(self, manager: UserManager, parent=None, on_saved=None,
                 can_edit_software_name=True):
        super().__init__(parent)
        self.manager = manager
        self._on_saved = on_saved or (lambda v: None)
        self._can_name = can_edit_software_name
        self.setWindowTitle("设备设置")
        self.setFixedSize(420, 340)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        tip = QLabel("以下为示例设备编码信息，仅超级管理员可设置。")
        tip.setFont(_yahei(10))
        tip.setStyleSheet(f"color: {TEXT_GRAY};")
        root.addWidget(tip)

        # 软件名称（拥有「设备软件名称」权限者可改；默认超级管理员拥有该权限）
        srow = QHBoxLayout()
        srow.setSpacing(8)
        slab = QLabel("软件名称")
        slab.setFixedWidth(72)
        slab.setFont(_yahei(11))
        self.sw_edit = QLineEdit()
        self.sw_edit.setFixedHeight(30)
        self.sw_edit.setStyleSheet(_input_style())
        self.sw_edit.setText(str(self.manager.software_name))
        self.sw_edit.setReadOnly(not self._can_name)
        srow.addWidget(slab)
        srow.addWidget(self.sw_edit)
        root.addLayout(srow)

        self.edits = {}
        for key in ["设备编码", "设备名称", "产线编号"]:
            row = QHBoxLayout()
            lab = QLabel(key)
            lab.setFixedWidth(72)
            lab.setFont(_yahei(11))
            ed = QLineEdit()
            ed.setFixedHeight(30)
            ed.setStyleSheet(_input_style())
            ed.setText(str(self.manager.device_code.get(key, "")))
            row.addWidget(lab)
            row.addWidget(ed)
            self.edits[key] = ed
            root.addLayout(row)
        root.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(32)
        cancel.setFixedWidth(90)
        cancel.setStyleSheet(_btn_neutral())
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存")
        ok.setFixedHeight(32)
        ok.setFixedWidth(90)
        ok.setStyleSheet(_btn_primary())
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _on_ok(self):
        values = {k: ed.text().strip() for k, ed in self.edits.items()}
        self.manager.set_device_code(values)
        name = self.sw_edit.text().strip()
        if name:
            self.manager.set_software_name(name)
        self._on_saved(values)
        QMessageBox.information(self, "成功", "设备设置已保存。")
        self.accept()
