"""本地图像浏览窗口：工作模式切到「本地图像」时弹出。

提供「加载图像 / 加载缺陷图 / 加载缺陷文件夹 / 上一张 / 下一张 /
运行所有图片 / 导出运行结果」七个按钮（一行排布）。
下方为已加载图片的可滚动列表，列表顶部有一行标题
（测试结果 / 序号 / 图片名 / 缩略图，测试结果列在序号列左侧，取值 OK / NG / 待定），
每行显示该图的测试结果、文件名与完整本地路径；列表占满窗口宽度，
不再保留右侧大块预览区。点击列表中任意一张图，该图会同步刷新到相机主画布及
对应的 R/G/B 三个通道；也可用「上一张 / 下一张」按钮或键盘上下箭头在已加载图片间切换。

窗口左侧可展开「统计详情」面板：底部统计行「总数」左侧有一个「详情」按钮，
点击后在窗口左侧展开一张 SPC 详情表（检测项 / 标称值 / 规格下限 / 规格上限 /
超下限数 / 超上限数 / 比例），内容与「统计信息」卡片 →「按缺陷项统计」→
「详情」中某个相机的明细完全一致（同源数据、同一样式）；再次点击按钮则收起。
面板内不再提供「相机1~相机8」切换行（固定展示相机1），避免多一层无用操作。

窗体宽度分「紧凑 / 展开」两态，与「目标查找参数设置」窗口点「分布」按钮的
做法一致（右侧展开内容 → 本窗口是左侧展开内容）：
紧凑态 = 仅原有内容（宽度与本窗口加详情面板之前完全一致）；
展开态 = 紧凑态宽度 + 详情面板宽 + 布局间距。
窗口初次打开时为紧凑态，详情面板默认隐藏。
"""
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QWidget, QSizePolicy, QFrame,
    QAbstractItemView, QHeaderView, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QSize, QEvent
from PyQt6.QtGui import QPixmap, QKeyEvent, QIcon, QColor, QFont, QFontMetrics


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")
THUMB_SIZE = 56

# 顶部 7 个按钮的字号与水平内边距（QSS 与宽度计算共用同一份，避免两边不一致
# 导致「窗口算出来的宽度」比「按钮实际需要宽度」小，文字被裁掉）
BTN_FONT_SIZE = 11
BTN_PADDING_H = 8

# 左侧统计详情面板宽度。
# ⚠️ 这个值必须≥ `DefectSPCStatTable` 7 列的**实测列宽合计**（当前 638px），
# 否则面板一展开，最右侧「比例」列就被挤出可视区 —— 表现为「展开后显示不完整」。
# 之前写死 560px 少了 78px，正是该问题的根因。启动时按实测值自动校正（见 _init_ui）。
DETAIL_PANEL_W = 660
# 详情面板在窗口内的上下留白（上下左右），与最外层布局边距保持一致
DETAIL_MARGIN_H = 12

# 演示用分类模式：基于加载序号稳定地给出 OK/NG/RST 分布，使尾部统计有合理差异。
_OK_NG_RST_PATTERN = ["OK", "NG", "OK", "RST", "OK", "NG"]

# 列表「测试结果」列的显示文案与配色：内部判定沿用 OK / NG / RST，
# 展示层把 RST（复检/待定）显示为「待定」，与设备状态、统计口径一致。
_VERDICT_TEXT = {"OK": "OK", "NG": "NG", "RST": "待定"}
_VERDICT_COLOR = {"OK": "#3FB950", "NG": "#F4584E", "RST": "#F39C12"}


def _classify_result(idx):
    """按序号稳定地把测试图片判为 OK / NG / RST 之一（演示用）。"""
    return _OK_NG_RST_PATTERN[idx % len(_OK_NG_RST_PATTERN)]


def _verdict_text(result):
    """内部判定（OK/NG/RST）→ 列表显示文案（OK/NG/待定）。"""
    return _VERDICT_TEXT.get(result, result or "-")



def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LocalImageWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("本地图像")
        self.resize(800, 560)
        self.images = []     # 已加载图片的绝对路径列表（表格行与其一一对应）
        self.idx = -1        # 当前显示索引
        self.results = {}    # idx -> 运行结果 dict
        self._user_engaged = False  # 用户是否已点选/切换/运行某张图（点选前不向画布同步）
        self._run_idx = 0
        self._run_timer = QTimer(self)
        self._run_timer.setInterval(450)
        self._run_timer.timeout.connect(self._run_step)
        self._init_ui()
        self._update_stats()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_ui(self):
        # 最外层为横向布局：左侧 = 可展开的「统计详情」面板（默认隐藏），
        # 右侧 = 原有内容（按钮行 / 图片列表 / 状态文本 / 统计行）。
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self._detail_visible = False
        self._detail_panel = self._build_detail_panel()
        outer.addWidget(self._detail_panel)

        right = QWidget()
        root = QVBoxLayout(right)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        outer.addWidget(right, 1)
        self._right_pane = right

        # 顶部按钮行：7 个按钮一行排完
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.b_load_img = self._mk_btn("加载图像", self._load_image)
        self.b_load_def = self._mk_btn("加载缺陷图", self._load_defect_image)
        self.b_load_dir = self._mk_btn("加载缺陷文件夹", self._load_folder)
        self.b_prev = self._mk_btn("上一张", self._prev)
        self.b_next = self._mk_btn("下一张", self._next)
        self.b_run_all = self._mk_btn("运行所有图片", self._run_all)
        self.b_export = self._mk_btn("导出运行结果", self._export)
        for b in (self.b_load_img, self.b_load_def, self.b_load_dir,
                  self.b_prev, self.b_next, self.b_run_all, self.b_export):
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        # 主体：已加载图片的可滚动列表（顶部标题行：测试结果 / 序号 / 图片名 / 缩略图）。
        # 「测试结果」列位于序号列左侧，取值 OK / NG / 待定。
        # 列表占满窗口宽度；去掉了原先右侧的大块预览区，点击行即可把该图同步到
        # 相机主画布及 R/G/B 三通道（当前图片在列表缩略图列中显示）。
        self.list_widget = QTableWidget()
        self.list_widget.setColumnCount(4)
        self.list_widget.setHorizontalHeaderLabels(
            ["测试结果", "序号", "图片名", "缩略图"])
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setShowGrid(False)
        self.list_widget.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_widget.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setStyleSheet(
            "QTableWidget{background-color:#15171B; border:1px solid #2A2D33; "
            "border-radius:4px; color:#E6E6E6; font-size:11px; gridline-color:#2A2D33;}"
            "QHeaderView::section{background-color:#22252B; color:#E6E6E6; "
            "border:none; padding:6px; font-size:12px; font-weight:bold;}"
            "QTableWidget::item{padding:2px;}"
            "QTableWidget::item:selected{background-color:#2D4A8A;}")
        hdr = self.list_widget.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)   # 测试结果
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)   # 序号
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # 图片名
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)   # 缩略图
        hdr.setFixedHeight(30)
        self.list_widget.setColumnWidth(0, 64)
        self.list_widget.setColumnWidth(1, 50)
        self.list_widget.setColumnWidth(3, THUMB_SIZE + 16)
        # 「测试结果」列仅在运行图片之后显示（运行前隐藏该列）
        self._ran = set()          # 已运行（已有检测结果）的行号
        self.list_widget.setColumnHidden(0, True)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self.list_widget, 1)

        # 底部状态文本（替代原右侧大块预览区）
        self.lbl_status = QLabel("未加载图片")
        self.lbl_status.setStyleSheet("color:#A8ABB0; font-size:11px;")
        root.addWidget(self.lbl_status)

        # 尾部统计行：测试图片总数 / 良率 / OK 数 / NG 数 / 待定数
        # （内部判定 RST，展示为「待定」）
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#2A2D33;")
        root.addWidget(sep)
        stat_row = QHBoxLayout()
        stat_row.setSpacing(18)
        # 「详情」按钮：位于「总数」左侧，点击展开/收起左侧统计详情面板
        self.b_detail = QPushButton("详情")
        self.b_detail.setCheckable(True)
        self.b_detail.setFixedHeight(22)
        self.b_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_detail.setStyleSheet(self._detail_btn_style(False))
        self.b_detail.toggled.connect(self._on_detail_toggled)
        stat_row.addWidget(self.b_detail)
        self.stat_total = QLabel("总数：0")
        self.stat_yield = QLabel("良率：--")
        self.stat_ok = QLabel("OK：0")
        self.stat_ng = QLabel("NG：0")
        self.stat_rst = QLabel("待定：0")
        self.stat_total.setStyleSheet("color:#E6E6E6; font-size:12px; font-weight:bold;")
        self.stat_yield.setStyleSheet("color:#4C9AFF; font-size:12px; font-weight:bold;")
        self.stat_ok.setStyleSheet("color:#3FB950; font-size:12px; font-weight:bold;")
        self.stat_ng.setStyleSheet("color:#F4584E; font-size:12px; font-weight:bold;")
        self.stat_rst.setStyleSheet("color:#F39C12; font-size:12px; font-weight:bold;")
        for b in (self.stat_total, self.stat_yield, self.stat_ok,
                  self.stat_ng, self.stat_rst):
            stat_row.addWidget(b)
        root.addLayout(stat_row)

        # 默认宽度 = 顶部按钮行完整显示所需的最小宽度（含左右边距与按钮间距），
        # 保证全部按钮一行可见；并设为最小宽度，避免被拖窄到按钮被截断。
        # 注意：紧凑宽度**只按原有内容计算**，不把详情面板宽算进去 ——
        # 否则窗口一打开就是「已展开」的宽度，与需求「初始显示宽度保持原样」不符。
        top_buttons = (self.b_load_img, self.b_load_def, self.b_load_dir,
                       self.b_prev, self.b_next, self.b_run_all, self.b_export)
        # ⚠️ 边距必须取**最外层** outer 的 contentsMargins（窗口左右各 12px），
        # 不能取内层 root（边距为 0）—— 取错会让算出的宽度少 24px，文字被裁。
        margins = outer.contentsMargins()
        min_w = margins.left() + margins.right()
        min_w += btn_row.spacing() * (len(top_buttons) - 1)
        # ⚠️ 不用 `b.sizeHint().width()`：QSS 里的 padding 不完全计入 sizeHint，
        # 实测会把「加载缺陷文件夹」这类长文案按钮算窄，导致文字被裁。
        # 改为按 QFontMetrics 实测文案宽度 + 按钮内边距，宽度才够放下完整文字。
        _btn_fm = QFontMetrics(QFont("Microsoft YaHei", BTN_FONT_SIZE))
        for b in top_buttons:
            min_w += _btn_fm.horizontalAdvance(b.text()) + BTN_PADDING_H * 2
        # QPushButton 默认 sizePolicy 允许收缩，给每颗按钮补一个下限，
        # 避免窗口被拖窄时按钮自己把文字压掉
        for b in top_buttons:
            b.setMinimumWidth(_btn_fm.horizontalAdvance(b.text()) + BTN_PADDING_H * 2)
        # 边框/焦点框再留2px 余量，避免各平台 DPI 舍入把最后一点文字切掉
        min_w += 2
        # ⚠️ 详情面板宽度按 SPC 表 7 列**实测需求**校正（缺 78px 会把「比例」列挤出可视区）。
        # 表此刻可能尚未 layout，故取「各列已分配宽度」与「表头文案宽度」的较大值，
        # 保证无论哪种时机计算都能覆盖真实需求。
        # 实测值存到实例属性 `self._detail_panel_w`（不能就地赋值模块常量 DETAIL_PANEL_W：
        # 函数内赋值会把它变成局部变量，其他方法就读不到了）。
        self._detail_panel_w = DETAIL_PANEL_W
        _tbl = getattr(self, "_detail_table", None)
        if _tbl is not None:
            _need_w = 0
            for _i in range(_tbl.columnCount()):
                _w = _tbl.columnWidth(_i)
                _hi = _tbl.horizontalHeaderItem(_i)
                if _hi is not None:
                    _w = max(_w, _tbl.fontMetrics().horizontalAdvance(_hi.text() or "") + 8)
                _need_w += _w
            # 每列单元格内边距(左右各 2px) + 面板边框余量
            _need_w += _tbl.columnCount() * 4 + 16
            if _need_w > self._detail_panel_w:
                self._detail_panel_w = _need_w
                self._detail_panel.setFixedWidth(self._detail_panel_w)
        # 紧凑 / 展开两态宽度（对齐「目标查找参数设置」窗口的 _COMPACT_W / _FULL_W 做法）
        self._outer_spacing = outer.spacing()
        self._compact_w = min_w
        self._full_w = min_w + self._detail_panel_w + outer.spacing()
        self.setMinimumWidth(self._compact_w)
        self.resize(self._compact_w, self.height())
        # 右上角锚点：展开/收起都以「首次显示时的右上角」为基准做等比位移，
        # 保证两态之间来回切换时右上角严格不动、不会累积漂移。
        # ⚠️ 不能用「点击瞬间的右边缘」当锚点：一旦某次因左侧空间不足而
        # 退化成「只加宽不位移」，右边缘就被永久改写，收回时窗口会停在错误位置。
        self._anchor_right_top = None

    # ------------------------------------------------------------------
    # 左侧「统计详情」面板（默认隐藏，点击底部「详情」按钮展开/收起）
    # ------------------------------------------------------------------
    def _build_detail_panel(self):
        """构建左侧统计详情面板（默认隐藏）。

        内容与「统计信息」卡片 →「按缺陷项统计」→「详情」中某一相机的明细**完全一致**：
        直接复用 `production_view.DefectSPCStatTable` 与同一份示例缺陷数据
        （`CAMERA_DEFECTS_DATA` / `_defect_totals_from_data` / `_split_defect` /
        `_DEFECT_SPEC`），保证两处口径、配色、列宽、行高一致，不会出现两套数字。
        面板**不再提供「相机1~相机8」切换行**（需求：删除该行），固定展示相机1。
        """
        from production_view import (
            DefectSPCStatTable, CAMERA_DEFECTS_DATA, _defect_totals_from_data,
            _split_defect, _DEFECT_SPEC,
        )

        panel = QWidget()
        panel.setFixedWidth(DETAIL_PANEL_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        title = QLabel("统计详情")
        title.setStyleSheet("color:#E6E6E6; font-size:12px; font-weight:bold;")
        lay.addWidget(title)

        # 固定展示「相机1」（不再有相机切换按钮行）
        self._detail_cam = "相机1"

        self._detail_table = DefectSPCStatTable()
        lay.addWidget(self._detail_table, 1)

        self._detail_defect_types = list(_DEFECT_SPEC.keys())
        self._detail_source = (
            DefectSPCStatTable, CAMERA_DEFECTS_DATA, _defect_totals_from_data,
            _split_defect, _DEFECT_SPEC,
        )
        self._fill_detail_table()
        # 初次打开窗口时详情面板默认隐藏
        panel.setVisible(False)
        return panel

    @staticmethod
    def _detail_btn_style(active):
        """底部「详情」按钮样式：展开时蓝底白字，收起时描边灰字。"""
        if active:
            return ("QPushButton{background-color:#4261FF; color:white; border:none; "
                    "border-radius:4px; padding:2px 12px; font-size:11px; font-weight:bold;}")
        return ("QPushButton{background-color:#22252B; color:#A8ABB0; "
                "border:1px solid #2A2D33; border-radius:4px; padding:2px 12px; "
                "font-size:11px;}"
                "QPushButton:hover{color:#E6E6E6; border-color:#4261FF;}")

    def _fill_detail_table(self):
        """按当前相机填充 SPC 七列表（口径与统计信息卡片详情页一致）。"""
        if not hasattr(self, "_detail_table"):
            return
        (_tbl_cls, data, totals_fn, split_fn, spec) = self._detail_source
        per_cam, _agg = totals_fn(data)
        counts = per_cam.get(self._detail_cam, {})
        cam_total = sum(counts.values()) or 1
        rows = []
        for d in self._detail_defect_types:
            total = counts.get(d, 0)
            below, above = split_fn(d, total)
            ratio = total / cam_total * 100
            nom, lo, hi = spec.get(d, ("-", "-", "-"))
            rows.append((d, nom, lo, hi, below, above, ratio))
        self._detail_table.set_rows(rows)

    def _on_detail_toggled(self, checked):
        """底部「详情」按钮：展开 / 收起左侧统计详情面板。

        宽度语义与「目标查找参数设置」窗口点「分布」一致：
        展开 → 切到 `_full_w`（紧凑宽 + 详情面板宽 + 间距）；
        收起 → 回到 `_compact_w`（即本窗口加详情面板之前的原始宽度）。

        **右上角锚定（2026-10-08 需求）**：无论展开还是收起，窗口**右上角固定不动**，
        只有宽度向左生长 / 从左侧收回，两态之间来回切换严格可逆。

        两个必须避免的坑（都实际踩过）：
        1. **锚点不能用「点击瞬间的右边缘」**。若某次因左侧空间不足而退化为
           「只加宽不位移」，右边缘就被永久改写；下一次收起会以这个错误右边缘
           为基准 → 窗口停在偏移位置（实测 x从 64 漂到 634）。必须锚定
           **首次显示时的右上角**（`_anchor_right_top`），只在真正第一次时记录。
        2. **左侧空间不足时不能「只加宽不位移」**，那会让窗口右侧超出屏幕、
           内容被裁（这正是「显示不完整」的成因）。正确做法是**压缩详情面板宽度**，
           让窗口总宽刚好等于「锚点右边缘 - 屏幕左边界」，保证完整可见。
        """
        self._detail_visible = bool(checked)
        self.b_detail.setStyleSheet(self._detail_btn_style(self._detail_visible))
        self.b_detail.setText("收起详情" if self._detail_visible else "详情")
        if self._detail_visible:
            self._fill_detail_table()
        self._detail_panel.setVisible(self._detail_visible)
        self._apply_detail_geometry(expanded=self._detail_visible)

    def _apply_detail_geometry(self, expanded):
        """按右上角锚点重排窗口几何：宽度变化时右边缘 / 上边缘严格不动。

        `expanded=True`  → 宽度 = 紧凑宽 + 详情面板宽 + 间距（左端向左生长）
        `expanded=False` → 宽度 = 紧凑宽（左端从详情面板处收回）
        两态的右上角完全一致，收起后精确回到展开前的位置。

        宽度决策只有一处（避免「压缩了忘记恢复」这类状态残留）：
        先算出展开的标准总宽，再统一夹到「锚点右边缘 - 屏幕左边界」以内；
        夹取时优先牺牲详情面板宽度（下限 = SPC 表实需宽），再退化为不显示面板。
        """
        base_w = self._compact_w
        # 首次调用时记录右上角锚点（窗口刚被 debug_view 定位好、用户还没操作）
        g = self.geometry()
        if getattr(self, "_anchor_right_top", None) is None:
            self._anchor_right_top = (g.x() + g.width(), g.y())
        anchor_right, anchor_top = self._anchor_right_top

        if not expanded:
            # 收起：宽度回到紧凑态；详情面板恢复标准固定宽（下次展开即为标准宽）
            self._detail_panel.setFixedWidth(self._detail_panel_w)
            self.setMinimumWidth(base_w)
            self.setGeometry(anchor_right - base_w, anchor_top, base_w, g.height())
            return

        # ---- 展开：标准总宽 = 紧凑宽 + 详情面板实需宽 + 布局间距 ----
        panel_w = self._detail_panel_w
        target_w = base_w + panel_w + self._outer_spacing
        # 屏幕可用区：宽度不足以容纳标准展开时，压缩详情面板而不是让窗口出屏
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        if avail is not None:
            max_w = anchor_right - avail.left()
            if target_w > max_w:
                # 可让给面板的宽度 = 屏幕内剩余 - 紧凑宽 - 间距
                room = max_w - base_w - self._outer_spacing
                if room >= self._detail_panel_w:
                    panel_w = self._detail_panel_w
                elif room >= self._detail_panel.minimumWidth():
                    panel_w = room            # 部分压缩，仍够显示表格
                else:
                    # 空间实在不够：不显示面板，仅保证原有内容完整可见
                    self._detail_panel.setVisible(False)
                    panel_w = 0
                target_w = base_w + panel_w + (self._outer_spacing if panel_w else 0)
                target_w = max(target_w, min(base_w, max_w))
        self._detail_panel.setFixedWidth(panel_w if panel_w else self._detail_panel_w)
        self.setMinimumWidth(target_w)
        # 右上角锚定：x 由右上角反推，y 直接取锚点顶边 → 两态右上角严格一致
        self.setGeometry(anchor_right - target_w, anchor_top,
                         target_w, g.height())

    def reset_detail_anchor(self):
        """把「右上角锚点」重置为窗口**当前**右上角。

        由外部（debug_view 定位浮动窗口之后）调用一次：此时窗口位置刚被
        `_place_floating` 设成「与生产统计卡片右上对齐」，正是需求所说的基准位置。
        必须在定位**之后**调用，否则锚点会记在构造时的默认位置上。

        ⚠️ 两种展开状态都要立即重算：
        收起态下若只把 `_anchor_right_top` 置None 而不重算，锚点会一直是 None，
        展开时退化成「以点击瞬间的位置为基准」，在窗口被拖动过的情况下就会漂移
        （实测表现为展开后窗口跑到别处）。
        """
        g = self.geometry()
        self._anchor_right_top = (g.x() + g.width(), g.y())
        # 已处于展开态时同步重排几何，保证锚点与当前宽度自洽
        if self._detail_visible:
            self._apply_detail_geometry(expanded=True)

    def _mk_btn(self, text, slot):
        b = QPushButton(text)
        # 字号 / 内边距用模块常量，与 _init_ui 里的宽度计算保持一致
        b.setStyleSheet(
            f"QPushButton{{background-color:#4261FF; color:white; border:none; "
            f"border-radius:4px; padding:5px {BTN_PADDING_H}px; "
            f"font-size:{BTN_FONT_SIZE}px;}}"
            f"QPushButton:hover{{background-color:#5A78FF;}}"
            f"QPushButton:disabled{{background-color:#4A4D52; color:#A8ABB0;}}")
        b.clicked.connect(slot)
        return b

    def _paint_verdict_cell(self, k):
        """刷新第 k 行最左侧的「测试结果」列：OK 绿 / NG 红 / 待定（复检）橙。
        该列仅在「运行图片」之后才显示（运行前整列隐藏），未运行的行显示占位符。"""
        r = self.results.get(k) or {}
        verdict = r.get("result") if k in self._ran else None
        item = QTableWidgetItem(_verdict_text(verdict) if verdict else "-")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(QColor(_VERDICT_COLOR.get(verdict, "#8A8F99")))
        font = item.font()
        font.setBold(bool(verdict))
        item.setFont(font)
        self.list_widget.setItem(k, 0, item)

    # ------------------------------------------------------------------
    # 加载（支持多选）
    # ------------------------------------------------------------------
    def _load_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "加载图像", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
        if paths:
            self._add_images(paths)

    def _load_defect_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "加载缺陷图", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
        if paths:
            self._add_images(paths)

    def _load_folder(self):
        d = QFileDialog.getExistingDirectory(self, "加载缺陷文件夹")
        if not d:
            return
        files = []
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(IMAGE_EXTS):
                files.append(os.path.join(d, fn))
        if files:
            self._add_images(files)
        else:
            self.lbl_status.setText(f"文件夹内未找到图片：{d}")

    def _add_images(self, paths):
        if not paths:
            return
        start = self.list_widget.rowCount()
        for p in paths:
            if p in self.images:
                continue   # 避免重复加载同一张
            self.images.append(p)
        end = len(self.images)
        if start == end:
            return
        self.list_widget.setRowCount(end)
        for k in range(start, end):
            p = self.images[k]
            # 演示用：按序号稳定分类，使尾部 OK/NG/待定 统计立即有值
            self.results[k] = {
                "file": os.path.basename(p), "path": p,
                "time": "-", "result": _classify_result(k),
            }
            # 测试结果（序号列左侧）：OK 绿 / NG 红 / 待定（复检）橙
            self._paint_verdict_cell(k)
            # 序号
            seq = QTableWidgetItem(str(k + 1))
            seq.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_widget.setItem(k, 1, seq)
            # 图片名：文件名（白）+ 完整本地路径（灰，可换行）
            name_w = QWidget()
            nv = QVBoxLayout(name_w)
            nv.setContentsMargins(4, 2, 4, 2)
            nv.setSpacing(2)
            fn = QLabel(os.path.basename(p))
            fn.setStyleSheet("color:#E6E6E6; font-size:12px;")
            fp = QLabel(p)
            fp.setStyleSheet("color:#8A8F99; font-size:10px;")
            fp.setWordWrap(True)
            nv.addWidget(fn)
            nv.addWidget(fp)
            self.list_widget.setCellWidget(k, 2, name_w)
            # 缩略图
            thumb = QLabel()
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pix = QPixmap(p)
            if not pix.isNull():
                t = pix.scaled(THUMB_SIZE, THUMB_SIZE,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                thumb.setPixmap(t)
            self.list_widget.setCellWidget(k, 3, thumb)
            self.list_widget.setRowHeight(k, THUMB_SIZE + 12)
        if self.idx < 0 and self.images:
            self.idx = 0
        self.list_widget.setCurrentCell(self.idx, 0)   # 触发选择处理
        self.lbl_status.setText(f"已加载 {len(self.images)} 张图片")
        self._update_stats()

    # ------------------------------------------------------------------
    # 显示 / 切换（统一经列表选择驱动）
    # ------------------------------------------------------------------
    def _on_selection_changed(self):
        rows = self.list_widget.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row < 0 or row >= len(self.images):
            return
        self.idx = row
        # 仅当用户已点选过图片（_user_engaged）才同步到画布；否则保持原工作模式刷新
        self._show_current(sync_to_canvas=self._user_engaged)

    def _on_cell_clicked(self, row, column):
        """用户实际点选列表中的某张图：标记已交互并立即同步到相机画布。"""
        if row < 0 or row >= len(self.images):
            return
        self._user_engaged = True
        self.idx = row
        self._show_current(sync_to_canvas=True)

    def _show_current(self, sync_to_canvas=False):
        if not self.images or self.idx < 0:
            self.lbl_status.setText("未加载图片")
            if sync_to_canvas:
                self._emit_to_canvas(None)
            return
        self.idx = max(0, min(self.idx, len(self.images) - 1))
        path = self.images[self.idx]
        self.lbl_status.setText(f"当前：({self.idx + 1}/{len(self.images)})  {path}")
        pix = QPixmap(path)
        if pix.isNull():
            self.lbl_status.setText(f"无法加载图片：{os.path.basename(path)}")
            return
        # 仅在用户已点选/切换/运行图片时才同步到相机主画布及 R/G/B 三通道；
        # 未点选之前，画布仍按当前（切换前）工作模式持续刷新。
        if sync_to_canvas:
            self._emit_to_canvas(pix)
            # 触发父级调试界面刷新检测项的检测值（按默认值上下浮动）与检测结果，
            # 用于本地图像示例演示：每切换/运行一张图，检测值均会变化。
            self._emit_detection_tick()

    def _emit_to_canvas(self, pixmap):
        """把当前图片同步刷新到相机主画布及 R/G/B 三通道（若有父级调试界面）。"""
        p = self.parent()
        if p is not None and hasattr(p, "_sync_local_image"):
            p._sync_local_image(pixmap)

    def _emit_detection_tick(self):
        """把『切换/运行一张图』事件通知父级调试界面，由其刷新检测项检测值
        （按默认值上下浮动）与检测结果，用于本地图像示例演示。"""
        p = self.parent()
        if p is not None and hasattr(p, "refresh_detection_values"):
            p.refresh_detection_values(self.idx)

    def _prev(self):
        if not self.images:
            return
        self._user_engaged = True
        self.idx = (self.idx - 1) % len(self.images)
        self.list_widget.setCurrentCell(self.idx, 0)

    def _next(self):
        if not self.images:
            return
        self._user_engaged = True
        self.idx = (self.idx + 1) % len(self.images)
        self.list_widget.setCurrentCell(self.idx, 0)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up:
            self._prev()
            event.accept()
        elif event.key() == Qt.Key.Key_Down:
            self._next()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 示例图片（用于演示：上一张/下一张/运行所有图片/导出）
    # ------------------------------------------------------------------
    def load_examples(self):
        """加载 6 张与调试界面画布同款的示例图片，便于直接演示切换/运行。

        这些示例图采用与生产/调试画布一致的样张生成逻辑（make_sample_frames），
        写入系统临时目录后作为普通图片加载，因此「上一张 / 下一张 / 运行所有图片 /
        导出运行结果」等按钮均可直接演示。"""
        import os
        import tempfile
        from components import make_sample_frames
        d = os.path.join(tempfile.gettempdir(), "vis_inspect_examples")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = tempfile.gettempdir()
        paths = []
        for i in range(6):
            p = os.path.join(d, f"示例图_{i + 1}.png")
            if not os.path.exists(p):
                frames = make_sample_frames(640, 480, count=1, seed=200 + i)
                if frames:
                    frames[0].save(p, "PNG")
            if os.path.exists(p):
                paths.append(p)
        if paths:
            self._add_images(paths)
            self.lbl_status.setText(f"已加载 {len(paths)} 张示例图片，可直接演示切换/运行")

    # ------------------------------------------------------------------
    # 运行 / 导出
    # ------------------------------------------------------------------
    def _run_all(self):
        if not self.images:
            self.lbl_status.setText("请先加载图片再运行")
            return
        if self._run_timer.isActive():
            return
        self._run_idx = 0
        self._run_timer.start()

    def _run_step(self):
        if self._run_idx >= len(self.images):
            self._run_timer.stop()
            self.lbl_status.setText(
                f"运行完成，共 {len(self.images)} 张，可导出运行结果")
            return
        self._user_engaged = True
        self.idx = self._run_idx
        self.list_widget.setCurrentCell(self.idx, 0)   # 触发显示并同步到画布
        path = self.images[self.idx]
        self.results[self.idx] = {
            "file": os.path.basename(path),
            "path": path,
            "time": _now(),
            "result": _classify_result(self.idx),
        }
        self._ran.add(self.idx)
        # 首次运行即显示「测试结果」列（运行前该列隐藏）
        self.list_widget.setColumnHidden(0, False)
        self._paint_verdict_cell(self.idx)   # 刷新「测试结果」列
        self.lbl_status.setText(f"运行中 {self.idx + 1}/{len(self.images)} ...")
        self._update_stats()
        self._run_idx += 1

    def _export(self):
        if not self.results:
            self.lbl_status.setText("暂无运行结果可导出，请先运行所有图片")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出运行结果", "运行结果.csv",
            "CSV 文件 (*.csv);;文本文件 (*.txt)")
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["序号", "文件名", "路径", "运行时间", "判定"])
                for i in sorted(self.results.keys()):
                    r = self.results[i]
                    w.writerow([i + 1, r["file"], r["path"], r["time"],
                                _verdict_text(r.get("result"))])
            self.lbl_status.setText(f"已导出运行结果：{path}")
        except Exception as e:  # noqa: BLE001
            self.lbl_status.setText(f"导出失败：{e}")

    def showEvent(self, event):
        super().showEvent(event)
        # 首次打开且无图片时，自动加载 6 张示例图片用于演示
        if not self.images:
            self.load_examples()
        # 窗口真正显示后再按当前选中项渲染一次（含缩略图与画布同步）
        if self.images:
            self.list_widget.setCurrentCell(self.idx, 0)

    # ------------------------------------------------------------------
    # 尾部统计：测试图片总数 / OK 数 / NG 数 / 待定（RST）数
    # ------------------------------------------------------------------
    def _update_stats(self):
        """刷新尾部统计行：总数与 OK/NG/待定（RST）分类计数。"""
        total = len(self.images)
        ok = ng = rst = 0
        for r in self.results.values():
            c = r.get("result")
            if c == "OK":
                ok += 1
            elif c == "NG":
                ng += 1
            elif c == "RST":
                rst += 1
        self.stat_total.setText(f"总数：{total}")
        self.stat_ok.setText(f"OK：{ok}")
        self.stat_ng.setText(f"NG：{ng}")
        self.stat_rst.setText(f"待定：{rst}")
        # 良率 = OK / (OK + NG)，待定（复检）不计入分母；无有效分母时显示 --
        _judged = ok + ng
        self.stat_yield.setText(
            f"良率：{ok / _judged * 100:.2f}%" if _judged else "良率：--")
