"""新建产品对话框（按参考图双步向导布局）。

第一步：产品选择 -> 第二步：检测设置
页面风格与调试界面一致：暗色背景 + Card 卡片容器 + accent_orange 主按钮。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QFrame, QStackedWidget, QSizePolicy, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QTabWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from styles import COLORS
from components import Card
from size_diagrams import ElectrodeDiagram

YAHEI = "Microsoft YaHei"


def _yahei(size, bold=False):
    f = QFont(YAHEI)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def _aggregate_rows(rows):
    """把分页规格表转换为 lookup_nominal 使用的 12 元素聚合布局。

    分页布局：(类型, 英制, 公制, L, L公差, W, W公差, T, T公差, 电极…)
    聚合布局：(类型, 英制, 公制, L, W, T, L公差, W公差, T公差, 电极1, 电极2, 电极3)
    电极列不足 3 列时以「—」补齐（电阻无 L2、电感仅有 D、晶振暂无电极数据）。
    """
    out = []
    for r in rows:
        base = (r[0], r[1], r[2], r[3], r[5], r[7], r[4], r[6], r[8])
        tail = list(r[9:12])
        tail += ["—"] * (3 - len(tail))
        out.append(base + tuple(tail))
    return out


class _AutoWidthTable(QTableWidget):
    """列宽自适应表格：按内容计算自然宽度，并铺满可视区域。

    - 自然宽度 = max(表头文字宽, 该列最宽单元格文字宽) + 内边距；
    - 若各列自然宽度总和小于可视宽度，则按比例放大分配，铺满整行；
    - 若总和大于可视宽度，则按比例压缩并保留最小宽度（允许横向滚动）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._natural = []

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_widths()

    def set_natural_widths(self, widths):
        self._natural = list(widths)
        self._apply_widths()

    def _apply_widths(self):
        if not self._natural or self.columnCount() == 0:
            return
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        avail = max(self.viewport().width(), 100)
        total = sum(self._natural)
        if total <= 0:
            return
        min_w = 56
        if total <= avail:
            # 有余量：按比例放大铺满
            extra = avail - total
            widths = [w + extra * w / total for w in self._natural]
        else:
            # 超宽：按比例压缩（不低于最小宽度，超出部分允许横向滚动）
            widths = [max(min_w, w * avail / total) for w in self._natural]
        ints = [int(w) for w in widths]
        # 取整余数补给最宽的列，保证列宽总和与可视宽度一致（无空隙）
        rest = avail - sum(ints)
        order = sorted(range(len(ints)), key=lambda c: -widths[c])
        i = 0
        while rest > 0 and order:
            ints[order[i % len(order)]] += 1
            rest -= 1
            i += 1
        for c, w in enumerate(ints):
            self.setColumnWidth(c, w)


class ProductSizeReferenceDialog(QDialog):
    """产品尺寸参考：按产品类型分页的规格清单（非模态、不置顶、不遮挡）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("产品尺寸参考")
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self.setFixedSize(1180, 800)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        tip = QLabel("各产品类型的标称尺寸与电极参数参考（单位：mm），按类型分页查看。")
        tip.setFont(_yahei(10))
        tip.setStyleSheet(f"color: {COLORS['text_secondary']};")
        root.addWidget(tip)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {COLORS['border']}; "
            f"background-color: {COLORS['bg_card']}; border-radius: 4px; }}"
            f"QTabBar::tab {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_secondary']}; padding: 6px 18px; "
            f"border: 1px solid {COLORS['border']}; border-bottom: none; "
            f"border-top-left-radius: 4px; border-top-right-radius: 4px; "
            f"font-size: 11px; }}"
            f"QTabBar::tab:selected {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['accent_orange']}; font-weight: bold; }}")
        self._tables = {}
        for tab_name, headers, data_table, note_text, img_kind in NewProductDialog.REFERENCE_PAGES:
            page, table = self._build_page(headers, data_table, note_text, img_kind)
            self.tabs.addTab(page, tab_name)
            self._tables[tab_name] = table
        root.addWidget(self.tabs, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(80, 28)
        close_btn.setFont(_yahei(10))
        close_btn.setStyleSheet(self._close_btn_style())
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _build_page(self, headers, data_table, note_text, img_kind):
        """构建单个分页：上部表格 + 下部电极结构图示说明。返回 (承载 QWidget, 表格)。"""
        page = QFrame()
        page.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; }}")
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        table = _AutoWidthTable()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        rows = data_table
        table.setRowCount(len(rows))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(56)
        table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; gridline-color: {COLORS['border']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; font-size: 10px; }}"
            f"QHeaderView::section {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['accent_orange']}; font-weight: bold; "
            f"border: 1px solid {COLORS['border']}; padding: 4px; }}"
            f"QTableWidget::item {{ padding: 2px; }}")
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                shown = text
                if c == 2 and text.startswith("L"):   # 公制列删除首字母 L 显示
                    shown = text[1:]
                item = QTableWidgetItem(shown if shown else "—")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, item)
        # 自然列宽 = max(表头宽, 最宽单元格宽) + 内边距
        fm = table.fontMetrics()
        natural = []
        for c in range(table.columnCount()):
            head_item = table.horizontalHeaderItem(c)
            w = fm.horizontalAdvance(head_item.text() if head_item else "") + 30
            for r in range(table.rowCount()):
                it = table.item(r, c)
                if it is not None:
                    w = max(w, fm.horizontalAdvance(it.text()) + 30)
            natural.append(max(w, 56))
        table.set_natural_widths(natural)
        v.addWidget(table, 1)

        # 图示说明区（矢量绘制：线条分明、文字清晰）
        diag_box = QFrame()
        diag_box.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_panel']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
        diag_layout = QHBoxLayout(diag_box)
        diag_layout.setContentsMargins(10, 8, 10, 8)
        diag_layout.setSpacing(14)
        if img_kind:
            diagram = ElectrodeDiagram(img_kind)
            diagram.setObjectName("diagram_image")
            diagram.setMinimumHeight(200)
            diag_layout.addWidget(diagram, 3)
        note = QLabel("尺寸 / 电极参数说明（单位：mm）\n\n" + note_text)
        note.setFont(_yahei(11))
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignTop)
        note.setStyleSheet(f"color: {COLORS['text_primary']};")
        diag_layout.addWidget(note, 2)
        v.addWidget(diag_box)
        return page, table

    @staticmethod
    def _close_btn_style():
        return (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; font-size: 11px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; }}")


class NewProductDialog(QDialog):
    PRODUCT_TYPES = ["电容", "电阻", "电感", "磁珠", "晶振", "LTCC", "LED"]
    PRODUCT_MODELS = ["01005", "0201", "0402", "0603", "0805", "1206"]
    SPECS = ["Ver01", "Ver02", "Ver03", "Ver04"]
    CAMERA_OPTIONS = ["上表面检测", "下表面检测", "前端面检测", "后端面检测",
                      "外侧面检测", "内侧面检测", "无"]
    CAMERA_DEFAULTS = ["上表面检测", "下表面检测", "前端面检测", "后端面检测",
                       "外侧面检测", "内侧面检测", "无", "无"]

    # 2026-11-17 需求：产品型号（产品规格）联动标称尺寸(mm)
    # 按电容表（英制 0201=公制 0603）校正，取代上一轮口头示例值。
    # 用于旧配方/无匹配类型时的兜底映射。
    MODEL_NOMINAL_SIZES = {
        "01005": ("0.40", "0.20", "0.20"),
        "0201": ("0.60", "0.30", "0.30"),
        "0402": ("1.00", "0.50", "0.50"),
        "0603": ("1.60", "0.80", "0.80"),
        "0805": ("2.00", "1.25", "1.25"),
        "1206": ("3.20", "1.60", "1.60"),
    }
    REFERENCE_TYPES = ("电容", "电阻", "电感", "晶振")
    # 各分页表头：前两列统一为「产品规格（英制）/（公制）」
    _SPEC_HEAD = ("产品类型", "产品规格（英制）", "产品规格（公制）")
    # 电容表头：L/W/T + 公差 + 电极 BWmin/BWmax/L2
    CAPACITOR_HEADERS = _SPEC_HEAD + (
        "L 长度", "L长度公差", "W 宽度", "W宽度公差",
        "T 厚度", "T厚度公差",
        "最小电极宽度\nBWmin", "最大电极宽度\nBWmax", "最小电极间距\nL2")
    # 电阻表头：L/W/T + 公差 + 顶面电极宽度A / 底面电极宽度B（无 L2）
    RESISTOR_HEADERS = _SPEC_HEAD + (
        "L 长度", "L长度公差", "W 宽度", "W宽度公差",
        "T 厚度", "T厚度公差",
        "顶面电极宽度\nA", "底面电极宽度\nB")
    # 电感表头：L/W/T + 公差 + 电极宽度 D
    INDUCTOR_HEADERS = _SPEC_HEAD + (
        "L 长度", "L长度公差", "W 宽度", "W宽度公差",
        "T 厚度", "T厚度公差", "电极宽度\nD")
    # 晶振表头：沿用 L/W/T + 公差 + 电极占位（暂无详细数据）
    CRYSTAL_HEADERS = CAPACITOR_HEADERS
    # 向后兼容别名
    REFERENCE_HEADERS = CAPACITOR_HEADERS
    SIMPLE_HEADERS = CAPACITOR_HEADERS
    # 贴片电阻规格表（7 行）——按用户提供的 Chip-R 规格表逐行录入
    RESISTOR_SIZE_TABLE = [
        ("电阻", "01005", "0402", "0.40", "±0.02", "0.20", "±0.02", "0.13", "±0.02", "0.10±0.03", "0.10±0.03"),
        ("电阻", "0201", "0603", "0.60", "±0.03", "0.30", "±0.03", "0.23", "±0.03", "0.10±0.05", "0.15±0.05"),
        ("电阻", "0402", "1005", "1.00", "±0.05", "0.50", "±0.05", "0.35", "±0.05", "0.20±0.10", "0.25±0.10"),
        ("电阻", "0603", "1608", "1.60", "±0.10", "0.80", "±0.10", "0.45", "±0.10", "0.30±0.20", "0.35±0.10"),
        ("电阻", "0805", "2012", "2.00", "±0.20", "1.25", "±0.15", "0.55", "±0.10", "0.40±0.20", "0.35±0.20"),
        ("电阻", "1206", "3216", "3.20", "±0.20", "1.60", "±0.15", "0.62", "±0.10", "0.45±0.20", "0.40±0.20"),
        ("电阻", "1210", "3225", "3.20", "±0.20", "2.55", "±0.20", "0.62", "±0.10", "0.45±0.20", "0.40±0.20"),
    ]
    # 贴片电感规格表（8 行）——按用户提供的 Chip Inductor 规格表逐行录入
    INDUCTOR_SIZE_TABLE = [
        ("电感", "01005", "0402", "0.40", "±0.02", "0.20", "±0.02", "0.20", "±0.02", "0.095±0.025"),
        ("电感", "0201", "0603", "0.60", "±0.03", "0.30", "±0.03", "0.30", "±0.03", "0.15±0.05"),
        ("电感", "0402", "1005", "1.00", "±0.15", "0.50", "±0.15", "0.50", "±0.15", "0.25±0.10"),
        ("电感", "0603", "1608", "1.60", "±0.20", "0.80", "±0.20", "0.80", "±0.20", "0.30±0.20"),
        ("电感", "0805", "2012", "2.00", "±0.20", "1.20", "±0.20", "0.90", "±0.20", "0.50±0.25"),
        ("电感", "1206", "3216", "3.20", "±0.20", "1.60", "±0.20", "0.90", "±0.20", "0.50±0.25"),
        ("电感", "1210", "3225", "3.20", "±0.20", "2.50", "±0.20", "1.30", "±0.20", "0.50±0.25"),
        ("电感", "1812", "4832", "4.80", "±0.20", "3.20", "±0.20", "1.50", "±0.20", "0.50±0.30"),
    ]
    # 贴片电容规格表（8 行）——按用户提供的 MLCC 规格表逐行录入
    CAPACITOR_SIZE_TABLE = [
        ("电容", "008004", "0201", "0.250", "±0.013", "0.125", "±0.013", "0.125", "±0.013", "0.05", "0.10", "0.05"),
        ("电容", "01005", "0402", "0.40", "±0.02", "0.20", "±0.02", "0.20", "±0.02", "0.07", "0.14", "0.13"),
        ("电容", "0201", "0603", "0.60", "±0.05", "0.30", "±0.05", "0.30", "±0.05", "0.10", "0.20", "0.20"),
        ("电容", "0402", "1005", "1.00", "±0.05", "0.50", "±0.05", "0.50", "±0.10", "0.15", "0.35", "0.30"),
        ("电容", "0603", "1608", "1.60", "±0.15", "0.80", "±0.15", "0.80", "±0.15", "0.20", "0.60", "0.40"),
        ("电容", "0805", "2012", "2.00", "±0.20", "1.25", "±0.20", "1.25", "±0.20", "0.25", "0.75", "0.70"),
        ("电容", "1206", "3216", "3.20", "±0.20", "1.60", "±0.20", "1.60", "±0.20", "0.25", "0.75", "1.40"),
        ("电容", "1210", "3225", "3.20", "±0.20", "2.50", "±0.20", "2.20", "±0.20", "0.25", "0.75", "1.40"),
    ]
    # 贴片晶振规格表（6 行）——公差/电极暂无数据，占位 —
    CRYSTAL_SIZE_TABLE = [
        ("晶振", "01005", "0402", "0.40", "—", "0.20", "—", "0.20", "—", "—", "—", "—"),
        ("晶振", "", "1210", "1.20", "—", "1.00", "—", "0.30", "—", "—", "—", "—"),
        ("晶振", "", "1612", "1.60", "—", "1.20", "—", "0.35", "—", "—", "—", "—"),
        ("晶振", "", "2016", "2.00", "—", "1.60", "—", "0.45", "—", "—", "—", "—"),
        ("晶振", "", "2520", "2.50", "—", "2.00", "—", "0.45", "—", "—", "—", "—"),
        ("晶振", "", "3225", "3.20", "—", "2.50", "—", "0.55", "—", "—", "—", "—"),
    ]
    # 2026-11-17 需求：四类产品的尺寸规格清单聚合视图（由各分页规格表派生），
    # 每项 12 元素 (产品类型, 英制, 公制, L, W, T, L公差, W公差, T公差, 电极1, 电极2, 电极3)，
    # 供 lookup_nominal 二维查表使用（避免数据重复维护）。
    PRODUCT_SIZE_TABLE = (
        _aggregate_rows(CAPACITOR_SIZE_TABLE)
        + _aggregate_rows(RESISTOR_SIZE_TABLE)
        + _aggregate_rows(INDUCTOR_SIZE_TABLE)
        + _aggregate_rows(CRYSTAL_SIZE_TABLE)
    )
    # 分页配置：(tab 名, 表头, 数据表, 说明文字, 示意图键)
    REFERENCE_PAGES = (
        ("MLCC电容", CAPACITOR_HEADERS, CAPACITOR_SIZE_TABLE,
         "电容本体尺寸与两端电极（BW）结构：L 长度、W 宽度、T 厚度；"
         "BWmin~BWmax 为电极覆盖宽度范围，L2 为两端电极间最小净距 (L2 = L − 左BW − 右BW)。",
         "mlcc"),
        ("贴片电阻", RESISTOR_HEADERS, RESISTOR_SIZE_TABLE,
         "贴片电阻三视图：L 长度、W 宽度、T 厚度；"
         "A 为顶面电极宽度、B 为底面电极宽度（详见 Top/Side/Bottom View）。",
         "resistor"),
        ("贴片电感", INDUCTOR_HEADERS, INDUCTOR_SIZE_TABLE,
         "贴片电感本体尺寸与电极结构：L 长度、W 宽度、T 厚度；"
         "D 为两端电极（镀层端头）覆盖宽度。",
         "inductor"),
        ("晶振", CRYSTAL_HEADERS, CRYSTAL_SIZE_TABLE,
         "贴片晶振常见尺寸参考（公差/电极参数待后续补充）。",
         ""),
    )
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
        self.setFixedWidth(560)   # 2026-11-17：宽度固定；高度在构建后按内容自适应
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
        # 高度按内容自适应：取两步页面所需高度较大者 + 边距，避免过大留白
        content_h = max(self.stack.widget(0).sizeHint().height(),
                        self.stack.widget(1).sizeHint().height())
        self.setFixedHeight(content_h + 136)   # 步骤标题/底部按钮/内外边距
        self._ui_ready = True
        self._apply_step()

    # ---------- 尺寸数据 ----------
    @classmethod
    def lookup_nominal(cls, product_type, product_model):
        """按(产品类型, 规格)查 PRODUCT_SIZE_TABLE，返回 (L, W, T)。

        产品型号下拉中的规格以英制为主（0201/0402…），故优先按英制列精确匹配；
        英制列为空（如电阻前两行、晶振多数行）时按公制列匹配；均未命中则回退
        电容口径的 MODEL_NOMINAL_SIZES。
        """
        for row in cls.PRODUCT_SIZE_TABLE:
            if row[0] == product_type and row[1] and product_model == row[1]:
                return (row[3], row[4], row[5])
        for row in cls.PRODUCT_SIZE_TABLE:
            if row[0] == product_type and row[2] and product_model == row[2]:
                return (row[3], row[4], row[5])
        return cls.MODEL_NOMINAL_SIZES.get(product_model, ("", "", ""))

    def _default_nominal(self, key):
        """按当前产品类型 + 产品型号返回该维度的标称尺寸。"""
        sizes = self.lookup_nominal(self.product_type, self.product_model)
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
        """产品型号/类型变更后，用映射表刷新三个标称尺寸输入框（连带公差重算规格）。"""
        if not hasattr(self, "_size_edits"):
            return
        for key, _label in self.DIMENSIONS:
            self._size_edits[f"product_{key}"].setText(self._default_nominal(key))

    def _open_size_reference(self):
        """打开「产品尺寸参考」分类表格窗口（非模态、不置顶、不遮挡当前窗口）。"""
        if getattr(self, "_size_ref_window", None) is None or not self._size_ref_window.isVisible():
            self._size_ref_window = ProductSizeReferenceDialog(self)
        win = self._size_ref_window
        win.show()
        # 置于当前新建产品窗口左侧偏下，避免遮挡（不 activateWindow、不 raise_）
        self._place_reference_window(win)

    def _place_reference_window(self, win):
        """把参考窗放到当前窗口左侧，避免遮挡正在操作的新建产品向导。"""
        try:
            parent_pos = self.mapToGlobal(self.rect().topLeft())
            x = max(0, parent_pos.x() - win.width() - 12)
            y = parent_pos.y()
            win.move(x, y)
        except Exception:
            pass

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
            if attr in ("product_model", "product_type"):
                cb.currentTextChanged.connect(
                    lambda v, a=attr: (setattr(self, a, v), self._apply_model_sizes()))
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
        size_header = QHBoxLayout()
        size_header.setSpacing(12)
        size_title = QLabel("3.输入产品尺寸")
        size_title.setFont(_yahei(12, True))
        size_title.setStyleSheet(f"color: {COLORS['accent_orange']};")
        size_header.addWidget(size_title)
        size_header.addStretch()
        self._btn_size_ref = QPushButton("产品尺寸参考")
        self._btn_size_ref.setFixedSize(110, 26)
        self._btn_size_ref.setFont(_yahei(10))
        self._btn_size_ref.setStyleSheet(self._btn_ghost_style())
        self._btn_size_ref.setToolTip("查看各产品类型的尺寸规格参考表")
        self._btn_size_ref.clicked.connect(self._open_size_reference)
        size_header.addWidget(self._btn_size_ref)
        layout.addLayout(size_header)

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
