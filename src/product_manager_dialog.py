"""产品管理对话框。

表格展示已创建产品，底部按钮支持编辑/切换/拷贝/删除/导入/导出。
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QMessageBox,
    QAbstractItemView, QSizePolicy, QHeaderView,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from styles import COLORS
from new_product_dialog import NewProductDialog


_TYPE_DESCRIPTION = {
    "电容": "MLCC",
    "电阻": "贴片厚膜电阻",
    "电感": "叠层电感",
    "磁珠": "磁珠",
    "晶振": "晶振",
    "LTCC": "LTCC",
    "LED": "LED",
}


def _yahei(size, bold=False):
    # 使用像素字号（12px），与列头样式表的 font-size:12px 严格一致，
    # 避免 QFont(...,12) 被解释为 12pt（≈16px）导致字号不一致。
    f = QFont("Microsoft YaHei")
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def _description_for(product_type: str) -> str:
    return _TYPE_DESCRIPTION.get(product_type, product_type)


def _now_str() -> str:
    return datetime.now().strftime("%Y%m%d %H:%M:%S")


def _make_default_product() -> dict:
    """生成与界面初始状态一致的默认产品。"""
    return {
        "id": str(uuid4()),
        "created_at": _now_str(),
        "product_type": "电容",
        "product_model": "0402",
        "product_spec": "Ver01",
        "description": _description_for("电容"),
        "camera_configs": list(NewProductDialog.CAMERA_DEFAULTS),
    }


def _make_template_product(product_type: str, product_model: str) -> dict:
    """生成一个不可删除的母版产品（电容 0402 / 电阻 0603）。"""
    return {
        "id": str(uuid4()),
        "created_at": _now_str(),
        "product_type": product_type,
        "product_model": product_model,
        "product_spec": "Ver01",
        "description": _description_for(product_type) + "，母版，不可删除",
        "camera_configs": list(NewProductDialog.CAMERA_DEFAULTS),
        "is_template": True,
    }


def _make_template_products() -> list[dict]:
    """默认产品列表：两个不可删除的母版（电容 0402 / 电阻 0603）。"""
    return [
        _make_template_product("电容", "0402"),
        _make_template_product("电阻", "0603"),
    ]


class ProductManagerDialog(QDialog):
    def __init__(self, products: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("产品管理")
        self.setFixedSize(800, 460)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        self.products = products
        self._build_ui()
        self._refresh_table()
        if self.products:
            self.table.selectRow(0)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 产品表格：使用真实表头（bg_panel 底、列宽按内容自适应，文字完整显示不被遮挡）
        # 页面内不显示标题行（需求：删除顶部「产品管理」四字）
        headers = ["创建时间", "产品类型", "产品型号",
                   "产品类型（自定义）", "产品型号（自定义）", "产品描述"]
        self.table = QTableWidget()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"gridline-color: {COLORS['border']}; color: {COLORS['text_primary']}; "
            f"font-size: 12px; }}"
            f"QTableWidget::item {{ padding: 5px 6px; "
            f"border-bottom: 1px solid {COLORS['border']}; }}"
            f"QTableWidget::item:selected {{ background-color: {COLORS['accent_orange']}; "
            f"color: white; }}"
        )
        # 页面内不出现滚动条（需求），列宽按内容自适应保证文字完整显示
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        h = self.table.horizontalHeader()
        h.setVisible(True)
        h.setStyleSheet(
            f"QHeaderView::section {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"padding: 6px 8px; font-size: 12px; font-weight: bold; }}"
        )
        h.setFont(_yahei(12, True))
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # 列宽按内容自适应（含表头文字），超出可视范围出现横向滚动条，文字不被截断
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.table, 1)

        # 底部按钮
        footer = QFrame()
        footer.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(12)
        fl.addStretch()

        for txt, slot in [
            ("编辑产品", self._on_edit),
            ("切换产品", self._on_switch),
            ("拷贝产品", self._on_copy),
            ("删除产品", self._on_delete),
            ("导入产品", self._on_import),
            ("导出产品", self._on_export),
        ]:
            btn = QPushButton(txt)
            btn.setFixedHeight(34)
            btn.setFont(_yahei(12))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
                f"border: none; border-radius: 6px; padding: 0 16px; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: #C9430F; }}"
                f"QPushButton:pressed {{ background-color: #A9370C; }}"
            )
            btn.clicked.connect(slot)
            fl.addWidget(btn)
            if txt == "删除产品":
                self._btn_delete = btn
        root.addWidget(footer)
        # 选中行变化时：母版产品不可删除 → 禁用「删除产品」按钮
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _refresh_table(self):
        self.table.setRowCount(len(self.products))
        for r, p in enumerate(self.products):
            items = [
                p.get("created_at", ""),
                p.get("product_type", ""),
                p.get("product_model", ""),
                p.get("custom_type_display", ""),
                p.get("custom_model_display", ""),
                p.get("description", _description_for(p.get("product_type", ""))),
            ]
            for c, val in enumerate(items):
                item = QTableWidgetItem(str(val))
                item.setFont(_yahei(12))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, c, item)
        # 列宽按内容自适应（含表头文字），保证列头与内容都完整显示；
        # 滚动条已关闭，对话框按内容总宽自适应加宽，确保文字完整且无横向滚动条
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        needed = self.table.horizontalHeader().length() + 40  # 边距(32)+边框(2)+余量
        new_w = min(max(self.width(), needed), 1200)
        self.setFixedSize(new_w, self.height())

    def _selected_row(self) -> int:
        sel = self.table.selectedIndexes()
        return sel[0].row() if sel else -1

    def _on_selection_changed(self):
        """选中行变化：母版产品（不可删除）选中时禁用「删除产品」按钮，否则启用。"""
        row = self._selected_row()
        is_template = False
        if row >= 0 and row < len(self.products):
            is_template = bool(self.products[row].get("is_template", False))
        if getattr(self, "_btn_delete", None) is not None:
            self._btn_delete.setEnabled(not is_template)

    def _on_edit(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要编辑的产品。")
            return
        product = self.products[row]
        dlg = NewProductDialog(self, edit_product=product)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            product.update({
                "product_type": dlg.product_type,
                "product_model": dlg.product_model,
                "product_spec": dlg.product_spec,
                "description": dlg.product_description or _description_for(dlg.product_type),
                "custom_type_display": dlg.custom_type_display,
                "custom_model_display": dlg.custom_model_display,
                "camera_configs": list(dlg.camera_configs),
            })
            self._refresh_table()
            self.table.selectRow(row)

    def _on_switch(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要切换的产品。")
            return
        product = self.products[row]
        parent = self.parent()
        if parent is not None and hasattr(parent, "_switch_product"):
            parent._switch_product(product)
        self.accept()

    def _on_copy(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要拷贝的产品。")
            return
        src = self.products[row]
        new_product = {
            "id": str(uuid4()),
            "created_at": _now_str(),
            "product_type": src["product_type"],
            "product_model": src["product_model"],
            "product_spec": src["product_spec"],
            "description": src.get("description", _description_for(src["product_type"])),
            "custom_type_display": src.get("custom_type_display", ""),
            "custom_model_display": src.get("custom_model_display", ""),
            "camera_configs": list(src.get("camera_configs", NewProductDialog.CAMERA_DEFAULTS)),
        }
        self.products.append(new_product)
        self._refresh_table()
        self.table.selectRow(len(self.products) - 1)

    def _on_delete(self):
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择要删除的产品。")
            return
        product = self.products[row]
        if product.get("is_template", False):
            QMessageBox.information(self, "提示", "母版产品不可删除。\n可通过「拷贝产品」复制母版后，再修改产品型号等内容。")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除产品「{product['product_type']} {product['product_model']} {product['product_spec']}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.products[row]
            self._refresh_table()
            if self.products:
                self.table.selectRow(min(row, len(self.products) - 1))

    def _on_import(self):
        QMessageBox.information(self, "提示", "导入产品功能开发中。")

    def _on_export(self):
        QMessageBox.information(self, "提示", "导出产品功能开发中。")
