"""用户与权限管理数据模型（演示用，密码明文存储）。

提供：
- 5 种用户类别
- 7 项功能权限
- 按用户类别的权限模板（演示用默认值，超级管理员可修改）
- 用户增删改、改密 / 重置他人密码
- 权限配置（按类别）
- 设备编码存储（仅超级管理员可用）

说明：本模块为演示实现，生产环境应使用加密存储与后端服务。
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

# 用户类别（从高到低）
CATEGORIES = [
    "超级管理员",
    "设备管理员",
    "设备工程师",
    "设备技术员",
    "设备操作员",
]

# 权限项：key -> 中文标签
PERMISSIONS = {
    "create_product": "新建产品",
    "manage_product": "管理产品",
    "start_stop": "启动/停止生产",
    "camera_debug": "相机调试",
    "camera_calibration": "相机标定",
    "image_save": "图片保存",
    "user_manage": "用户管理",
    "perm_config": "权限配置",
    "device_code": "设备设置",
    "device_software_name": "设备软件名称",
}

# 演示用默认权限模板（超级管理员可在「权限配置」中修改）
# 注：image_save（图片保存）默认所有用户类别均拥有。
DEFAULT_CATEGORY_PERMISSIONS = {
    "设备操作员": {
        "create_product": False, "manage_product": False, "start_stop": True,
        "camera_debug": True, "camera_calibration": False, "image_save": True,
        "user_manage": False,
        "perm_config": False, "device_code": False, "device_software_name": False,
    },
    "设备技术员": {
        "create_product": True, "manage_product": True, "start_stop": True,
        "camera_debug": True, "camera_calibration": True, "image_save": True,
        "user_manage": False,
        "perm_config": False, "device_code": False, "device_software_name": False,
    },
    "设备工程师": {
        "create_product": True, "manage_product": True, "start_stop": True,
        "camera_debug": True, "camera_calibration": True, "image_save": True,
        "user_manage": False,
        "perm_config": False, "device_code": False, "device_software_name": False,
    },
    "设备管理员": {
        "create_product": True, "manage_product": True, "start_stop": True,
        "camera_debug": True, "camera_calibration": True, "image_save": True,
        "user_manage": True,
        "perm_config": False, "device_code": False, "device_software_name": False,
    },
    "超级管理员": {k: True for k in PERMISSIONS},
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class UserManager:
    """用户与权限的内存 + JSON 持久化管理器。"""

    def __init__(self, path: str | None = None):
        if path is None:
            path = self._default_path()
        self.path = Path(path)
        # 深拷贝默认模板，避免改动类属性
        self.category_permissions = {
            c: dict(DEFAULT_CATEGORY_PERMISSIONS[c]) for c in CATEGORIES
        }
        self.device_code = {
            "设备编码": "EQ-2026-0001",
            "设备名称": "MLCC 视觉检测线",
            "产线编号": "LINE-A1",
        }
        self.software_name = "电子元件视觉检测系统"  # 软件名称（超级管理员可在设备设置中修改）
        self.lock_interval = "5分钟"  # 软件操作锁定间隔（设备设置中可选 1/5/10/30/60 分钟）
        self.autostart = True  # 设备开机自启动（高级设置，默认开启：开机后自动启动本软件）
        # 料盒抽出超时未放回的剔除逻辑（高级设置）：
        # "对应抽出料盒走待定"（默认）或 "全部料盒走待定"
        self.bin_taken_reject_mode = "对应抽出料盒走待定"
        # 密码输入确认时间周期（高级设置，默认 3 分钟）：当前登录用户超过该时长未操作软件，
        # 再次操作（点操作按钮 / 扫码录入 / 改算法参数等）需重新输入密码确认。
        self.confirm_interval = "3分钟"
        # 玻璃盘清洁提示时间周期（高级设置，默认 7 天）：超过该天数未清洁玻璃盘时，
        # 系统给出清洁提示（仅记录设置，提示触发由生产界面接入）。
        self.glass_clean_interval = "7天"
        # 高级设置「系统参数 / 联动与时序」各项取值（缺失项读取时自动补默认值）
        self.adv_options = self.adv_option_defaults()
        self.users: list[dict] = []
        self.recent_users: list[str] = []  # 最近登录用户（最多 5 个，最新在前）
        self.default_login: str | None = None  # 设为默认登录的用户名（开登录框时自动选中）
        self.load()

    # ---------- 持久化 ----------
    @staticmethod
    def _default_path() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys.executable).parent / "users.json"
        return Path(__file__).resolve().parent.parent / "users.json"

    def load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.users = data.get("users", [])
                for cat, perms in data.get("category_permissions", {}).items():
                    if cat in self.category_permissions:
                        self.category_permissions[cat].update(perms)
                if data.get("device_code"):
                    self.device_code.update(data["device_code"])
                self.software_name = data.get("software_name", "电子元件视觉检测系统")
                self.lock_interval = data.get("lock_interval", "5分钟")
                self.recent_users = data.get("recent_users", [])
                self.default_login = data.get("default_login")
                # 高级设置（需持久化）：开机自启动默认开启；抽盒超时剔除逻辑默认「对应抽出料盒走待定」
                self.autostart = bool(data.get("autostart", True))
                self.bin_taken_reject_mode = str(
                    data.get("bin_taken_reject_mode", "对应抽出料盒走待定"))
                self.confirm_interval = str(
                    data.get("confirm_interval", "3分钟"))
                self.glass_clean_interval = str(
                    data.get("glass_clean_interval", "7天"))
                # 高级设置各项：以出厂默认值为底，用已保存值覆盖（新增项自动补齐）
                _adv = self.adv_option_defaults()
                _saved_adv = data.get("adv_options")
                if isinstance(_saved_adv, dict):
                    for _k, _v in _saved_adv.items():
                        if _k in _adv:
                            _adv[_k] = _v
                self.adv_options = _adv
                if self.users:
                    return
            except Exception:
                pass
        self._seed()

    def _seed(self):
        now = _now_str()
        self.users = [
            {"username": "admin", "name": "系统管理员", "category": "超级管理员",
             "password": "admin123", "created_at": now},
            {"username": "devadmin01", "name": "赵管理员", "category": "设备管理员",
             "password": "123456", "created_at": now},
            {"username": "eng01", "name": "王工程师", "category": "设备工程师",
             "password": "123456", "created_at": now},
            {"username": "tech01", "name": "李技术员", "category": "设备技术员",
             "password": "123456", "created_at": now},
            {"username": "operator01", "name": "张操作员", "category": "设备操作员",
             "password": "123456", "created_at": now},
        ]
        self.save()

    def save(self):
        data = {
            "users": self.users,
            "category_permissions": self.category_permissions,
            "device_code": self.device_code,
            "software_name": self.software_name,
            "lock_interval": self.lock_interval,
            "recent_users": self.recent_users,
            "default_login": self.default_login,
            "autostart": bool(self.autostart),
            "bin_taken_reject_mode": self.bin_taken_reject_mode,
            "confirm_interval": self.confirm_interval,
            "glass_clean_interval": self.glass_clean_interval,
            "adv_options": dict(self.adv_options or {}),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 查询 ----------
    def get_user(self, username: str) -> dict | None:
        for u in self.users:
            if u["username"] == username:
                return u
        return None

    def authenticate(self, username: str, password: str) -> dict | None:
        user = self.get_user(username)
        if user is not None and user["password"] == password:
            return user
        return None

    def permissions_of(self, user: dict | None) -> dict:
        if user is None:
            return {}
        return dict(self.category_permissions.get(user["category"], {}))

    def can(self, user: dict | None, perm_key: str) -> bool:
        """判断用户是否拥有某项权限。
        设备编码设置仅超级管理员可用（强制，不受模板影响）。"""
        if user is None:
            return False
        if perm_key == "device_code":
            return user["category"] == "超级管理员"
        return bool(self.permissions_of(user).get(perm_key, False))

    # ---------- 用户 CRUD ----------
    def add_user(self, username: str, name: str, category: str, password: str) -> tuple[bool, str]:
        username = (username or "").strip()
        if not username:
            return False, "用户名不能为空。"
        if len(password) < 6:
            return False, "密码长度至少 6 位。"
        if self.get_user(username):
            return False, f"用户名「{username}」已存在。"
        if category not in CATEGORIES:
            return False, "用户类别无效。"
        self.users.append({
            "username": username,
            "name": name or username,
            "category": category,
            "password": password,
            "created_at": _now_str(),
        })
        self.save()
        return True, "添加成功。"

    def update_user(self, username: str, name: str | None = None,
                    category: str | None = None, password: str | None = None) -> tuple[bool, str]:
        user = self.get_user(username)
        if user is None:
            return False, "用户不存在。"
        if name is not None:
            user["name"] = name
        if category is not None:
            if category not in CATEGORIES:
                return False, "用户类别无效。"
            user["category"] = category
        if password:  # 空字符串表示不修改
            if len(password) < 6:
                return False, "密码长度至少 6 位。"
            user["password"] = password
        self.save()
        return True, "保存成功。"

    def delete_user(self, username: str) -> tuple[bool, str]:
        if username == "admin":
            return False, "超级管理员账号不可删除。"
        user = self.get_user(username)
        if user is None:
            return False, "用户不存在。"
        self.users = [u for u in self.users if u["username"] != username]
        self.save()
        return True, "已删除。"

    def reset_password(self, username: str, new_password: str) -> tuple[bool, str]:
        """管理员重置他人密码。"""
        if len(new_password) < 6:
            return False, "密码长度至少 6 位。"
        user = self.get_user(username)
        if user is None:
            return False, "用户不存在。"
        user["password"] = new_password
        self.save()
        return True, "密码已重置。"

    def change_own_password(self, username: str, new_password: str) -> tuple[bool, str]:
        """用户修改 / 重置自己的密码。"""
        return self.reset_password(username, new_password)

    # ---------- 权限配置 ----------
    def set_category_permissions(self, category: str, perms: dict):
        if category not in self.category_permissions:
            return
        for k, v in perms.items():
            if k in self.category_permissions[category]:
                self.category_permissions[category][k] = bool(v)
        # 设备编码设置强制仅超级管理员
        for cat in self.category_permissions:
            self.category_permissions[cat]["device_code"] = (cat == "超级管理员")
        self.save()

    # ---------- 设备编码 ----------
    def set_device_code(self, values: dict):
        self.device_code.update(values)
        self.save()

    def set_software_name(self, name: str):
        """修改并持久化软件名称（超级管理员权限控制在前端门控）。"""
        self.software_name = name
        self.save()

    def set_lock_interval(self, value: str):
        """修改并持久化软件操作锁定间隔（如 '5分钟'）。"""
        self.lock_interval = value
        self.save()

    # ---------- 最近登录 ----------
    def record_login(self, username: str):
        """记录一次成功登录：把该用户提到最近登录列表最前，最多保留 5 个。"""
        if not username:
            return
        rec = [u for u in self.recent_users if u != username]
        rec.insert(0, username)
        self.recent_users = rec[:5]
        self.save()

    def recent_candidates(self) -> list[str]:
        """登录下拉候选：最近登录过的用户（已存在的），最多 5 个；
        若尚无登录记录则回退为全部用户，保证开箱即用。"""
        rec = [u for u in self.recent_users if self.get_user(u)]
        if rec:
            return rec[:5]
        return [u["username"] for u in self.users]

    # ---------- 默认登录 ----------
    def set_default_login(self, username: str) -> bool:
        """将某用户设为默认登录账号（开登录框时自动选中）。"""
        if self.get_user(username) is None:
            return False
        self.default_login = username
        self.save()
        return True

    def get_default_login(self) -> str | None:
        """返回当前默认登录用户名（不存在则返回 None）。"""
        if self.default_login and self.get_user(self.default_login):
            return self.default_login
        return None

    # ---------- 高级设置（持久化项） ----------
    def set_autostart(self, enabled: bool) -> None:
        """设置「设备开机自启动」（默认开启），并持久化。"""
        self.autostart = bool(enabled)
        self.save()

    def set_bin_taken_reject_mode(self, mode: str) -> None:
        """设置「料盒抽出超时未放回的剔除逻辑」，并持久化。

        取值："对应抽出料盒走待定"（默认）或 "全部料盒走待定"。
        """
        mode = str(mode or "").strip()
        if mode not in ("对应抽出料盒走待定", "全部料盒走待定"):
            mode = "对应抽出料盒走待定"
        self.bin_taken_reject_mode = mode
        self.save()

    def get_bin_taken_reject_mode(self) -> str:
        """返回「料盒抽出超时未放回的剔除逻辑」（非法值回退默认）。"""
        mode = str(getattr(self, "bin_taken_reject_mode", "") or "")
        return mode if mode in ("对应抽出料盒走待定", "全部料盒走待定") \
            else "对应抽出料盒走待定"

    # ---------- 高级设置：系统参数 / 联动与时序 ----------
    # 每项：key -> (显示名称, 类型, 默认值, 选项/范围)
    #   类型 "combo"：选项为字符串列表；类型 "int"：范围为 (min, max)
    #   特殊项类型 "label"：仅作分组小标题（如「启动检测的过程」/「停止检测的过程」）
    ADV_OPTIONS = [
        ("special_port", "特殊串口", "combo", "COM16",
         [f"COM{i}" for i in range(1, 21)]),
        ("algo_threads", "算法线程数", "int", 3, (1, 64)),
        ("size_decimals", "尺寸测量小数点位数", "int", 4, (0, 6)),
        ("startup_check_algo", "启动时检查算法状态", "combo", "禁用", ["禁用", "启用"]),
        ("startup_input_product", "启动时输入产品明细", "combo", "禁用", ["禁用", "启用"]),
        ("min_refresh_interval", "主界面最小刷新间隔", "int", 10, (0, 10000)),
        ("main_display_mode", "主界面显示模式", "combo", "保持比例显示",
         ["保持比例显示", "拉伸填充显示", "居中原始尺寸"]),
        ("reject_mode", "剔除模式", "combo", "逻辑剔除", ["逻辑剔除", "物理剔除"]),
        ("flash_meter_mode", "闪测仪模式", "combo", "禁用", ["禁用", "启用"]),
        ("spot_check", "点检功能", "combo", "禁用", ["禁用", "启用"]),
        ("grr_func", "GRR 功能", "combo", "禁用", ["禁用", "启用"]),
        ("primary_language", "首选语言", "combo", "跟随系统",
         ["跟随系统", "简体中文", "English"]),
        ("second_language", "第二语言", "combo", "English", ["English", "简体中文", "无"]),
        ("pending_redirect", "待定结果重定向", "combo", "禁用", ["禁用", "启用"]),
        ("link_mode", "上下位机启停联动模式", "combo", "检测与设备联动模式（默认）",
         ["检测与设备联动模式（默认）", "仅设备联动模式", "仅检测联动模式"]),
        ("link_start_caption", "启动检测的过程", "label", "", None),
        ("start_out_belt_to_glass_ms", "出料皮带带到玻璃盘的延时(ms)", "int", 10, (0, 60000)),
        ("start_glass_to_in_belt_ms", "玻璃盘到进料皮带的延时(ms)", "int", 10, (0, 60000)),
        ("link_stop_caption", "停止检测的过程", "label", "", None),
        ("stop_in_belt_to_glass_ms", "进料皮带到玻璃盘的延时(ms)", "int", 10, (0, 60000)),
        ("stop_glass_to_out_belt_ms", "玻璃盘到出料皮带的延时(ms)", "int", 10, (0, 60000)),
        ("start_algo_delay_ms", "启动检测算法延时(ms)", "int", 1000, (0, 60000)),
        ("stop_algo_delay_ms", "停止检测算法延时(ms)", "int", 1000, (0, 60000)),
        ("sequential_exec", "顺序执行功能", "combo", "是", ["是", "否"]),
    ]

    @classmethod
    def adv_option_defaults(cls):
        """高级设置各项的出厂默认值（仅实际设置项，不含分组小标题）。"""
        return {k: dv for k, _lab, kind, dv, _opt in cls.ADV_OPTIONS if kind != "label"}

    def set_adv_option(self, key, value) -> None:
        """写入单个高级设置项并持久化（未知键 / 分组小标题忽略）。"""
        spec = next((s for s in self.ADV_OPTIONS if s[0] == key), None)
        if spec is None or spec[2] == "label":
            return
        kind = spec[2]
        if kind == "int":
            try:
                value = int(value)
            except Exception:
                return
        else:
            value = str(value)
        self.adv_options[key] = value
        self.save()

    def get_adv_options(self) -> dict:
        """返回高级设置全部取值（缺失项自动补默认值）。"""
        merged = self.adv_option_defaults()
        merged.update({k: v for k, v in (self.adv_options or {}).items()
                       if k in merged})
        return merged

    # ---------- 密码输入确认时间周期 ----------
    # 下拉可选值（顺序即下拉顺序），默认第 2 项「3分钟」
    CONFIRM_INTERVAL_OPTIONS = [
        "1分钟", "3分钟", "5分钟", "10分钟", "20分钟", "30分钟", "45分钟",
        "1小时", "2小时", "8小时", "24小时",
    ]
    DEFAULT_CONFIRM_INTERVAL = "3分钟"

    @classmethod
    def confirm_interval_options(cls):
        return list(cls.CONFIRM_INTERVAL_OPTIONS)

    def set_confirm_interval(self, value: str) -> None:
        """设置「密码输入确认时间周期」，并持久化（非法值回退默认 3 分钟）。"""
        value = str(value or "").strip()
        if value not in self.CONFIRM_INTERVAL_OPTIONS:
            value = self.DEFAULT_CONFIRM_INTERVAL
        self.confirm_interval = value
        self.save()

    def get_confirm_interval(self) -> str:
        """返回「密码输入确认时间周期」（非法值回退默认）。"""
        value = str(getattr(self, "confirm_interval", "") or "")
        return value if value in self.CONFIRM_INTERVAL_OPTIONS \
            else self.DEFAULT_CONFIRM_INTERVAL

    def confirm_interval_seconds(self) -> int:
        """把「密码输入确认时间周期」换算为秒（如 '3分钟' → 180、'2小时' → 7200）。"""
        value = self.get_confirm_interval()
        try:
            if value.endswith("分钟"):
                return int(value[:-2]) * 60
            if value.endswith("小时"):
                return int(value[:-2]) * 3600
        except Exception:
            pass
        return 180

    # ---------- 玻璃盘清洁提示时间周期 ----------
    # 下拉可选值（顺序即下拉顺序），默认「7天」
    GLASS_CLEAN_OPTIONS = [
        "1天", "3天", "7天", "14天", "30天", "60天", "90天",
    ]
    DEFAULT_GLASS_CLEAN_INTERVAL = "7天"

    def set_glass_clean_interval(self, value: str) -> None:
        """设置「玻璃盘清洁提示时间周期」，并持久化（非法值回退默认 7 天）。"""
        value = str(value or "").strip()
        if value not in self.GLASS_CLEAN_OPTIONS:
            value = self.DEFAULT_GLASS_CLEAN_INTERVAL
        self.glass_clean_interval = value
        self.save()

    def get_glass_clean_interval(self) -> str:
        """返回「玻璃盘清洁提示时间周期」（非法值回退默认）。"""
        value = str(getattr(self, "glass_clean_interval", "") or "")
        return value if value in self.GLASS_CLEAN_OPTIONS \
            else self.DEFAULT_GLASS_CLEAN_INTERVAL

    # ---------- 导入 / 导出 ----------
    def export_users(self, path: str) -> int:
        """导出全部用户到文件。.csv 导出用户名/姓名/类别/创建时间（不含密码）；
        .json 导出完整用户字典（含密码，便于整机迁移）。返回导出条数。"""
        p = Path(path)
        users = [dict(u) for u in self.users]
        if p.suffix.lower() == ".csv":
            with p.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["username", "name", "category", "created_at"])
                for u in users:
                    w.writerow([u.get("username", ""), u.get("name", ""),
                                u.get("category", ""), u.get("created_at", "")])
        else:
            p.write_text(
                json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(users)

    def import_users(self, path: str) -> tuple[int, int, int]:
        """从文件导入用户并合并进当前列表：新增不存在的用户、更新已存在用户的姓名/类别。
        返回 (新增数, 更新数, 跳过数)。CSV 无密码列时新用户默认密码 123456。"""
        p = Path(path)
        if not p.exists():
            return 0, 0, 0
        records: list[dict] = []
        if p.suffix.lower() == ".csv":
            with p.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    records.append({
                        "username": (row.get("username") or "").strip(),
                        "name": (row.get("name") or "").strip(),
                        "category": (row.get("category") or "").strip(),
                        "created_at": (row.get("created_at") or _now_str()),
                        "password": (row.get("password") or "123456").strip() or "123456",
                    })
        else:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return 0, 0, 0
            # 兼容两种形态：纯用户列表，或完整的 users.json（含 "users" 键）
            if isinstance(data, dict) and isinstance(data.get("users"), list):
                data = data["users"]
            for d in data:
                records.append({
                    "username": str(d.get("username", "")).strip(),
                    "name": str(d.get("name", "")).strip(),
                    "category": str(d.get("category", "")).strip(),
                    "created_at": str(d.get("created_at", _now_str())),
                    "password": str(d.get("password", "123456")),
                })
        added = updated = skipped = 0
        seen = {u["username"] for u in self.users}
        for r in records:
            uname = r["username"]
            if not uname:
                skipped += 1
                continue
            cat = r["category"] if r["category"] in CATEGORIES else "设备操作员"
            if uname in seen:
                user = self.get_user(uname)
                user["name"] = r["name"] or uname
                user["category"] = cat
                updated += 1
            else:
                self.users.append({
                    "username": uname,
                    "name": r["name"] or uname,
                    "category": cat,
                    "password": r["password"],
                    "created_at": r["created_at"],
                })
                seen.add(uname)
                added += 1
        self.save()
        return added, updated, skipped
