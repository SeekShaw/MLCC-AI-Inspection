"""新建产品对话框（按参考图双步向导布局）。

第一步：产品选择 -> 第二步：检测设置
页面风格与调试界面一致：暗色背景 + Card 卡片容器 + accent_orange 主按钮。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QStackedWidget, QSizePolicy, QLineEdit,
)
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

    STEP_TITLES = ["第一步：产品选择", "第二步：检测设置"]

    def __init__(self, parent=None, edit_product=None):
        super().__init__(parent)
        self._is_edit = edit_product is not None
        self.setWindowTitle("编辑产品" if self._is_edit else "新建产品")
        self.setFixedSize(520, 560)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        self._step = 0

        # 收集的数据
        self.product_type = edit_product.get("product_type", "电容") if self._is_edit else "电容"
        self.product_model = edit_product.get("product_model", "01005") if self._is_edit else "01005"
        self.product_spec = edit_product.get("product_spec", "Ver01") if self._is_edit else "Ver01"
        self.product_description = edit_product.get("description", "") if self._is_edit else ""
        self.custom_type_display = edit_product.get("custom_type_display", "") if self._is_edit else ""
        self.custom_model_display = edit_product.get("custom_model_display", "") if self._is_edit else ""
        self.camera_configs = list(edit_product.get("camera_configs", self.CAMERA_DEFAULTS)) if self._is_edit else list(self.CAMERA_DEFAULTS)

        # 步骤切换时会重新填充内容，保留 combo 引用便于读取
        self._product_combos = {}
        self._camera_combos = []

        self._build_ui()
        self._apply_step()

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
            label.setStyleSheet(f"color: {COLORS['text_primary']};")
            cb = QComboBox()
            cb.addItems(items)
            cb.setFixedSize(250, 32)
            cb.setFont(_yahei(12))
            cb.setCurrentText(default)
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
