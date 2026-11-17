"""新建产品对话框（按参考图双步向导布局）。

第一步：产品选择 -> 第二步：检测设置
页面风格与调试界面一致：暗色背景 + Card 卡片容器 + accent_orange 主按钮。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QFrame, QStackedWidget, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from styles import COLORS
from components import Card

YAHEI = "Microsoft YaHei"


def _yahei(size, bold=False):
    f = QFont(YAHEI)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


class NewProductDialog(QDialog):
    PRODUCT_TYPES = ["电容", "电阻", "电感", "磁珠", "晶振", "LTCC", "LED"]
    PRODUCT_MODELS = ["01005", "0201", "0402", "0603", "0805", "1206"]
    SPECS = ["Ver01", "Ver02", "Ver03", "Ver04"]
    CAMERA_OPTIONS = ["上表面检测", "下表面检测", "前端面检测", "后端面检测",
                      "外侧面检测", "内侧面检测", "无"]
    CAMERA_DEFAULTS = ["上表面检测", "下表面检测", "前端面检测", "后端面检测",
                       "外侧面检测", "内侧面检测", "无", "无"]

    # 2026-11-17 需求：产品型号（产品规格）联动标称尺寸(mm)
    # 前 3 项为用户明确指定；其余按行业常见公制尺寸补全。
    MODEL_NOMINAL_SIZES = {
        "01005": ("0.40", "0.20", "0.20"),
        "0201": ("0.50", "0.25", "0.20"),
        "0402": ("1.00", "0.50", "0.50"),
        "0603": ("1.60", "0.80", "0.80"),
        "0805": ("2.00", "1.25", "1.25"),
        "1206": ("3.20", "1.60", "1.60"),
    }
    # 尺寸字段顺序：键后缀、中文标签
    DIMENSIONS = [
        ("length", "长度"),
        ("width", "宽度"),
        ("thickness", "厚度"),
    ]
    DEFAULT_LOWER_TOL = "-0.05"
    DEFAULT_UPPER_TOL = "0.05"

    STEP_TITLES = ["第一步：产品选择", "第二步：检测设置"]

    def __init__(self, parent=None, edit_product=None):
        super().__init__(parent)
        self._is_edit = edit_product is not None
        self.setWindowTitle("编辑产品" if self._is_edit else "新建产品")
        self.setFixedSize(560, 820)   # 2026-11-17：尺寸区扩展为公差/规格五行，高度 640 → 820
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        self._step = 0
        self._ui_ready = False

        # 收集的数据
        self.product_type = edit_product.get("product_type", "电容") if self._is_edit else "电容"
        self.product_model = edit_product.get("product_model", "01005") if self._is_edit else "01005"
        self.product_spec = edit_product.get("product_spec", "Ver01") if self._is_edit else "Ver01"
        self.product_description = edit_product.get("description", "") if self._is_edit else ""
        self.custom_type_display = edit_product.get("custom_type_display", "") if self._is_edit else ""
        self.custom_model_display = edit_product.get("custom_model_display", "") if self._is_edit else ""

        # 2026-11-17 需求：尺寸 = 标称值 + 下公差 + 上公差，规格下限/上限自动计算
        ep = edit_product or {}
        for key, _label in self.DIMENSIONS:
            self._init_dimension(key, ep)

        self.camera_configs = list(edit_product.get("camera_configs", self.CAMERA_DEFAULTS)) if self._is_edit else list(self.CAMERA_DEFAULTS)

        # 步骤切换时会重新填充内容，保留 combo 引用便于读取
        self._product_combos = {}
        self._camera_combos = []

        self._build_ui()
        self._ui_ready = True
        self._apply_step()

    # ---------- 尺寸数据 ----------
    def _default_nominal(self, key):
        """按当前产品型号返回该维度的标称尺寸。"""
        sizes = self.MODEL_NOMINAL_SIZES.get(self.product_model, ())
        idx = [k for k, _ in self.DIMENSIONS].index(key)
        return sizes[idx] if idx < len(sizes) else ""

    @staticmethod
    def _compute_spec(nominal, tolerance):
        """规格上限/下限 = 标称尺寸 + 公差；小数位取两者较大者且至少 2 位。"""
        try:
            value = float(nominal) + float(tolerance)
        except (TypeError, ValueError):
            return ""
        if abs(value) < 1e-9:
            value = 0.0

        def _decimals(text):
            s = str(text)
            return len(s.split(".")[1]) if "." in s else 0

        digits = min(max(2, _decimals(nominal), _decimals(tolerance)), 4)
        return f"{value:.{digits}f}"

    def _init_dimension(self, key, ep):
        """初始化并回显单个尺寸的标称/公差/规格属性（兼容旧配方仅含标称值）。"""
        base = f"product_{key}"
        setattr(self, base, str(ep.get(base, self._default_nominal(key))))
        setattr(self, f"{base}_lower_tol",
                str(ep.get(f"{base}_lower_tol", self.DEFAULT_LOWER_TOL)))
        setattr(self, f"{base}_upper_tol",
                str(ep.get(f"{base}_upper_tol", self.DEFAULT_UPPER_TOL)))
        self._recalc_spec(key)

    def _recalc_spec(self, key):
        """由标称值与上下公差重算规格下限/上限属性。"""
        base = f"product_{key}"
        nominal = getattr(self, base)
        lower = getattr(self, f"{base}_lower_tol")
        upper = getattr(self, f"{base}_upper_tol")
        setattr(self, f"{base}_spec_lower", self._compute_spec(nominal, lower))
        setattr(self, f"{base}_spec_upper", self._compute_spec(nominal, upper))

    def _on_dimension_edited(self, key, field):
        """输入框编辑回调：写回属性，联动重算规格显示。"""
        if field == "nominal":
            attr = f"product_{key}"
            edits = self._size_edits
        else:
            attr = f"product_{key}_{field}"
            edits = self._tol_edits
        setattr(self, attr, edits[attr].text())
        self._recalc_spec(key)
        if self._ui_ready:
            self._sync_spec_displays(key)

    def _sync_spec_displays(self, key):
        """把计算出的规格下限/上限刷新到只读显示框。"""
        base = f"product_{key}"
        self._spec_displays[f"{base}_spec_lower"].setText(
            getattr(self, f"{base}_spec_lower"))
        self._spec_displays[f"{base}_spec_upper"].setText(
            getattr(self, f"{base}_spec_upper"))

    def _apply_model_sizes(self):
        """产品型号变更后，用映射表刷新三个标称尺寸输入框（连带公差重算规格）。"""
        if not hasattr(self, "_size_edits"):
            return
        for key, _label in self.DIMENSIONS:
            self._size_edits[f"product_{key}"].setText(self._default_nominal(key))

    # ---------- 构建 ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 步骤指示
        self.step_title = QLabel(self.STEP_TITLES[0])
        self.step_title.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.step_title.setFont(_yahei(12, True))
        root.addWidget(self.step_title)

        # 内容卡片
        card = Card()
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: transparent;")
        self.stack.addWidget(self._build_select_page())
        self.stack.addWidget(self._build_camera_page())
        card.layout.addWidget(self.stack, 1)
        root.addWidget(card, 1)

        # 底部动作按钮
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        # 上一步：仅第二步显示
        self.back_btn = QPushButton("‹  上一步")
        self.back_btn.setFixedHeight(40)
        self.back_btn.setFixedWidth(120)
        self.back_btn.setFont(_yahei(12, True))
        self.back_btn.setStyleSheet(self._btn_ghost_style())
        self.back_btn.clicked.connect(self._on_back)
        self.back_btn.hide()
        footer.addWidget(self.back_btn)
        # 主操作按钮：第一步填充剩余宽度
        self.action_btn = QPushButton("▶    确认，并进行下一步")
        self.action_btn.setFixedHeight(40)
        self.action_btn.setFont(_yahei(12, True))
        self.action_btn.setStyleSheet(self._btn_primary_style())
        self.action_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.action_btn.clicked.connect(self._on_action)
        footer.addWidget(self.action_btn)
        root.addLayout(footer)

    def _build_select_page(self):
        page = QFrame()
        page.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(16)

        # 第1行：产品类型
        # 第2行：产品型号
        rows = [
            ("1.产品类型：", self.PRODUCT_TYPES, "product_type", self.product_type),
            ("2.产品型号：", self.PRODUCT_MODELS, "product_model", self.product_model),
        ]
        for lab, items, attr, default in rows:
            row = QHBoxLayout()
            row.setSpacing(12)
            label = QLabel(lab)
            label.setFixedWidth(150)
            label.setFont(_yahei(12))
            # 2026-11-17：「1.产品类型」「2.产品型号」改为橙色，与「3.输入产品尺寸」一致
            label.setStyleSheet(f"color: {COLORS['accent_orange']};")
            cb = QComboBox()
            cb.addItems(items)
            cb.setFixedSize(250, 32)
            cb.setFont(_yahei(12))
            cb.setCurrentText(default)
            if attr == "product_model":
                cb.currentTextChanged.connect(
                    lambda v: (setattr(self, "product_model", v),
                               self._apply_model_sizes()))
            else:
                cb.currentTextChanged.connect(lambda v, a=attr: setattr(self, a, v))
            self._product_combos[attr] = cb
            row.addWidget(label)
            row.addWidget(cb)
            row.addStretch()
            layout.addLayout(row)

        # 第3行：产品描述（非必填，可自定义输入；有输入则显示，文字清晰可见）
        desc_row = QHBoxLayout()
        desc_row.setSpacing(12)
        desc_label = QLabel("产品描述：")
        desc_label.setFixedWidth(150)
        desc_label.setFont(_yahei(12))
        desc_label.setStyleSheet(f"color: {COLORS['text_primary']};")
        self._desc_edit = QLineEdit(self.product_description)
        self._desc_edit.setFixedSize(250, 32)
        self._desc_edit.setFont(_yahei(12))
        self._desc_edit.setPlaceholderText("（可选）")
        self._desc_edit.textChanged.connect(
            lambda v: setattr(self, "product_description", v))
        desc_row.addWidget(desc_label)
        desc_row.addWidget(self._desc_edit)
        desc_row.addStretch()
        layout.addLayout(desc_row)

        # 第4/5行：产品类型/型号 自定义显示名称（非必填，覆盖默认展示文案；有输入则显示）
        # 标签名与产品管理页表头一致：「产品类型（自定义）」「产品型号（自定义）」
        custom_rows = [
            ("产品类型（自定义）", "custom_type_display", self.custom_type_display),
            ("产品型号（自定义）", "custom_model_display", self.custom_model_display),
        ]
        for lab, attr, default in custom_rows:
            row = QHBoxLayout()
            row.setSpacing(12)
            label = QLabel(lab)
            label.setFixedWidth(150)
            label.setFont(_yahei(12))
            label.setStyleSheet(f"color: {COLORS['text_primary']};")
            le = QLineEdit(default)
            le.setFixedSize(250, 32)
            le.setFont(_yahei(12))
            le.setPlaceholderText("（可选）")
            le.textChanged.connect(lambda v, a=attr: setattr(self, a, v))
            row.addWidget(label)
            row.addWidget(le)
            row.addStretch()
            layout.addLayout(row)

        # 第6行起：3.输入产品尺寸
        # 排列：标称值 / 下公差 / 上公差 / 规格下限 / 规格上限
        # 规格下限/上限由「标称值+公差」自动计算，仅显示不可输入。
        size_title = QLabel("3.输入产品尺寸")
        size_title.setFont(_yahei(12, True))
        size_title.setStyleSheet(f"color: {COLORS['accent_orange']};")
        layout.addWidget(size_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        headers = ("", "标称值", "下公差", "上公差", "规格下限", "规格上限")
        for col, text in enumerate(headers):
            head = QLabel(text)
            head.setFont(_yahei(10))
            head.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.setStyleSheet(f"color: {COLORS['text_secondary']};")
            grid.addWidget(head, 0, col)

        self._size_edits = {}
        self._tol_edits = {}
        self._spec_displays = {}
        for r, (key, label_text) in enumerate(self.DIMENSIONS, start=1):
            base = f"product_{key}"
            name = QLabel(f"{label_text}：")
            name.setFixedWidth(58)
            name.setFont(_yahei(11))
            name.setStyleSheet(f"color: {COLORS['text_primary']};")
            grid.addWidget(name, r, 0)

            nominal = QLineEdit(getattr(self, base))
            nominal.setFixedSize(72, 30)
            nominal.setFont(_yahei(11))
            nominal.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nominal.textChanged.connect(
                lambda _v, k=key: self._on_dimension_edited(k, "nominal"))
            self._size_edits[base] = nominal
            grid.addWidget(nominal, r, 1)

            for col, field in ((2, "lower_tol"), (3, "upper_tol")):
                tol = QLineEdit(getattr(self, f"{base}_{field}"))
                tol.setFixedSize(72, 30)
                tol.setFont(_yahei(11))
                tol.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tol.textChanged.connect(
                    lambda _v, k=key, f=field: self._on_dimension_edited(k, f))
                self._tol_edits[f"{base}_{field}"] = tol
                grid.addWidget(tol, r, col)

            for col, field in ((4, "spec_lower"), (5, "spec_upper")):
                spec = QLineEdit(getattr(self, f"{base}_{field}"))
                spec.setFixedSize(72, 30)
                spec.setFont(_yahei(11))
                spec.setAlignment(Qt.AlignmentFlag.AlignCenter)
                spec.setReadOnly(True)
                spec.setStyleSheet(
                    f"QLineEdit {{ background-color: {COLORS['bg_panel']}; "
                    f"color: {COLORS['text_secondary']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
                self._spec_displays[f"{base}_{field}"] = spec
                grid.addWidget(spec, r, col)

        grid.setColumnStretch(6, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return page

    def _build_camera_page(self):
        page = QFrame()
        page.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 14, 20, 8)
        layout.setSpacing(10)

        self._camera_combos.clear()
        for i in range(8):
            row = QHBoxLayout()
            row.setSpacing(12)
            label = QLabel(f"相机{i + 1}：")
            label.setFixedWidth(90)
            label.setFont(_yahei(12))
            label.setStyleSheet(f"color: {COLORS['text_primary']};")
            cb = QComboBox()
            cb.addItems(self.CAMERA_OPTIONS)
            cb.setFixedSize(250, 30)
            cb.setFont(_yahei(12))
            cb.setCurrentText(self.camera_configs[i])
            idx = i
            cb.currentTextChanged.connect(
                lambda v, k=idx: self.camera_configs.__setitem__(k, v))
            self._camera_combos.append(cb)
            row.addWidget(label)
            row.addWidget(cb)
            row.addStretch()
            layout.addLayout(row)

        layout.addStretch()
        return page

    def _btn_primary_style(self):
        return (
            f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
            f"border: none; border-radius: 6px; font-size: 12px; padding: 0; }}"
            f"QPushButton:hover {{ background-color: #C9430F; }}"
            f"QPushButton:pressed {{ background-color: #A9370C; }}"
        )

    def _btn_ghost_style(self):
        return (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"font-size: 12px; padding: 0; }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; }}"
            f"QPushButton:pressed {{ background-color: {COLORS['bg_panel']}; }}"
        )

    # ---------- 导航 ----------
    def _apply_step(self):
        self.step_title.setText(self.STEP_TITLES[self._step])
        self.stack.setCurrentIndex(self._step)
        if self._step == 0:
            self.action_btn.setText("▶    确认，并进行下一步")
            self.back_btn.hide()
        else:
            done_text = "确认，完成产品编辑" if self._is_edit else "确认，完成产品新建"
            self.action_btn.setText(f"▶    {done_text}")
            self.back_btn.show()

    def _on_action(self):
        if self._step == 0:
            self._step = 1
            self._apply_step()
        else:
            self.accept()

    def _on_back(self):
        if self._step == 1:
            self._step = 0
            self._apply_step()
