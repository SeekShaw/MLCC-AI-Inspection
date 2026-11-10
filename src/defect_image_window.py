"""缺陷图查看窗口：底部状态栏「缺陷图查看」点击后弹出。

展示所有工位（相机1~相机8）缓存的图像（演示数据，与生产/调试画布同款样张生成逻辑
make_sample_frames + 红框缺陷标注）。每个工位缓存的 NG 图张数可在页面中设置。
- 左侧：缩略图网格（可滚动），每张下方标注工位相机名与判定结果；
- 左侧上方：工位筛选下拉（选项含各工位缓存 NG 图数）、各工位 NG 图数汇总、
  「每工位NG缓存张数」设置与「应用」按钮；
- 点击某一张 → 右侧大图显示，可用「放大 / 缩小 / 适应窗口」调整显示比例；
- 「上一张 / 下一张」在缺陷图之间切换（含键盘左右方向键）；
- 大图下方实时显示该图的缺陷信息：序号 / 工位相机 / 缺陷项 / 检测时间 / 判定。
"""
import random
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QScrollArea, QWidget, QGridLayout, QComboBox,
    QSpinBox,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QPen, QColor, QFont, QKeyEvent

from styles import COLORS

THUMB_W, THUMB_H = 132, 99   # 缩略图尺寸


def _build_defect_samples(ng_per_station=6, ok_per_station=3, rst_per_station=2):
    """生成「最新图像」演示数据：按工位（相机1~8）逐工位生成，每个工位固定缓存
    ng_per_station 张 NG 图（NG1/NG2 随机），另含 ok_per_station 张 OK、rst_per_station
    张 RST，使各「显示方式」筛选均有人看；整体按检测时间倒序排列。

    每条记录：{"pixmap": 图像, "camera": 工位相机名, "defect": 缺陷项,
               "time": 检测时间字符串, "result": "OK"/"NG1"/"NG2"/"RST"}
    判定结果（result）与剔除口对应：OK 良品；NG1/NG2/RST 为分通道不良
    （与 OK/NG1/NG2/RST 剔除口一一对应）。其中 NG = NG1 + NG2 的合计，
    单条记录不会是独立的「NG」，由「显示NG图像」下拉将 NG1 与 NG2 一并过滤显示。
    """
    from production_view import _DEFECT_TYPES, _DEFECT_BASE
    from components import make_sample_frames

    rng = random.Random(20260924)
    # 缺陷项按基准权重分布（数量多的缺陷出现得更频繁）
    pool = []
    for d, w in _DEFECT_BASE.items():
        pool += [d] * max(1, w // 4)
    cams = [f"相机{i}" for i in range(1, 9)]
    now = datetime.now()
    items = []
    seq = 0
    per = ng_per_station + ok_per_station + rst_per_station
    for cam in cams:
        for k in range(per):
            # 每工位前 ng_per_station 张为 NG（NG1/NG2 随机），其后为 OK，最后为 RST
            if k < ng_per_station:
                result = rng.choice(["NG1", "NG2"])
            elif k < ng_per_station + ok_per_station:
                result = "OK"
            else:
                result = "RST"
            defect = rng.choice(pool) if result != "OK" else "无"
            t = now - timedelta(seconds=30 * (seq + 1) + rng.randint(0, 20))
            pix = make_sample_frames(THUMB_W * 3, THUMB_H * 3, count=1,
                                     seed=9000 + seq)
            if pix:
                img = pix[0]
                if result != "OK":
                    # 不良图：红框标注缺陷位置 + 缺陷项文字（OK 良品图不加标注）
                    p = QPainter(img)
                    pen = QPen(QColor("#F4584E"), 4)
                    p.setPen(pen)
                    mx, my = img.width(), img.height()
                    bx, by = int(mx * rng.uniform(0.15, 0.55)), int(my * rng.uniform(0.15, 0.55))
                    bw, bh = int(mx * 0.3), int(my * 0.3)
                    p.drawRect(bx, by, bw, bh)
                    f = QFont("Microsoft YaHei", 16)
                    f.setBold(True)
                    p.setFont(f)
                    p.setPen(QColor("#F4584E"))
                    p.drawText(bx, max(30, by - 10), defect)
                    p.end()
                items.append({
                    "pixmap": img,
                    "camera": cam,
                    "defect": defect,
                    "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": result,
                })
            seq += 1
    # 整体按检测时间倒序（最新在前）
    items.sort(key=lambda it: it["time"], reverse=True)
    return items


class DefectImageWindow(QDialog):
    """缺陷图查看窗口：缩略图网格 + 大图预览（放大/缩小/上一张/下一张/缺陷信息）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("缺陷图查看")
        self.resize(1080, 660)
        # 各工位缓存张数设置（NG 为每工位固定缓存张数；OK/RST 为每工位辅助张数，供其它显示方式筛选）
        self._ng_per_station = 6
        self._ok_per_station = 3
        self._rst_per_station = 2
        self._all_items = _build_defect_samples(
            self._ng_per_station, self._ok_per_station, self._rst_per_station)
        self._filter_mode = "显示所有图像"           # 当前显示方式（底部下拉同步）
        self._station_filter = None                 # 工位筛选：None=全部工位，否则为相机名
        self._items = list(self._all_items)          # 按显示方式过滤后的图像
        self._idx = 0            # 当前查看的图像索引
        self._zoom = 1.0         # 大图显示比例（1.0=适应窗口）
        self._init_ui()
        if self._items:
            self._show_current()
        self._update_zoom_label()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 顶部标题行：说明 + 数量统计
        head = QHBoxLayout()
        self._title_label = QLabel(f"所有工位最新 {len(self._items)} 张缺陷图")
        self._title_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: bold;")
        head.addWidget(self._title_label)
        head.addStretch()
        tip = QLabel("点击缩略图查看大图；可用 上一张/下一张 切换，放大/缩小 调整显示比例")
        tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        head.addWidget(tip)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        # —— 左：缩略图网格（QListWidget 图标模式，可滚动）——
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(THUMB_W, THUMB_H))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setSpacing(8)
        self._list.setFixedWidth(THUMB_W * 3 + 80)
        self._list.setStyleSheet(
            f"QListWidget {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"color: {COLORS['text_primary']}; font-size: 11px; }}"
            f"QListWidget::item {{ width: {THUMB_W}px; }}"
            f"QListWidget::item:selected {{ background-color: #2D4A8A; "
            f"border-radius: 4px; }}")
        self._rebuild_list()
        self._list.currentItemChanged.connect(self._on_item_changed)
        self._list.itemClicked.connect(
            lambda _it: self._sync_from_selection())

        # 左侧整体：工位缓存 NG 图数面板（可点选按工位筛选）+ 缩略图网格
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._build_stat_panel())
        left.addWidget(self._list, 1)
        body.addLayout(left, 0)

        # —— 右：大图预览 + 缺陷信息 ——
        right = QVBoxLayout()
        right.setSpacing(8)
        # 工具行：上一张 / 放大 / 缩小 / 适应窗口 / 下一张
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.b_prev = self._mk_btn("◀ 上一张", self._prev)
        self.b_next = self._mk_btn("下一张 ▶", self._next)
        self.b_zoom_in = self._mk_btn("放大 ＋", lambda: self._zoom_step(1.25))
        self.b_zoom_out = self._mk_btn("缩小 －", lambda: self._zoom_step(0.8))
        self.b_fit = self._mk_btn("适应窗口", self._zoom_fit)
        for b in (self.b_prev, self.b_next, self.b_zoom_in,
                  self.b_zoom_out, self.b_fit):
            btns.addWidget(b)
        btns.addStretch()
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px;")
        btns.addWidget(self.lbl_zoom)
        right.addLayout(btns)

        # 大图预览区（可滚动，缩放超出视口时出滚动条）
        self._img_area = QScrollArea()
        self._img_area.setWidgetResizable(False)
        self._img_area.setStyleSheet(
            f"QScrollArea {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
        self._img_holder = QWidget()
        gl = QGridLayout(self._img_holder)
        gl.setContentsMargins(0, 0, 0, 0)
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("background-color: #0B0C0E;")
        gl.addWidget(self._img_label, 0, 0)
        self._img_area.setWidget(self._img_holder)
        right.addWidget(self._img_area, 1)

        # 缺陷信息区：序号 / 工位相机 / 缺陷项 / 检测时间 / 判定
        info_box = QFrame()
        info_box.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
        info = QHBoxLayout(info_box)
        info.setContentsMargins(12, 8, 12, 8)
        info.setSpacing(24)
        self.lbl_seq = self._mk_info(info, "序号")
        self.lbl_cam = self._mk_info(info, "工位相机")
        self.lbl_defect = self._mk_info(info, "缺陷项")
        self.lbl_time = self._mk_info(info, "检测时间")
        self.lbl_result = self._mk_info(info, "判定")
        right.addWidget(info_box)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

    # ------------------------------------------------------------------
    # 外部显示方式（由底部状态栏「显示所有图像」下拉切换）
    #   - 显示所有图像 / 显示OK图像 / 显示非OK图像 / 显示NG图像 /
    #     显示NG1图像 / 显示NG2图像 / 显示RST图像
    # 按记录的 result 字段过滤缩略图列表。其中 NG 是 NG1 + NG2 的合计：
    # 选「显示NG图像」会同时显示 NG1 与 NG2 的图，选「显示NG1/NG2」则只显示对应结果；
    # 「显示非OK图像」用排除法取 result != "OK"（NG1+NG2+RST），避免日后新增判定类型时漏掉。
    # ------------------------------------------------------------------
    # 显示方式 → 匹配的 result 值集合（None 表示全部）
    _FILTER_KEYS = {
        "显示OK图像": ("OK",),
        "显示NG图像": ("NG1", "NG2"),   # NG = NG1 + NG2 合计
        "显示NG1图像": ("NG1",),
        "显示NG2图像": ("NG2",),
        "显示RST图像": ("RST",),
    }

    def set_filter_mode(self, mode):
        if not isinstance(mode, str) or not mode:
            return
        self._filter_mode = mode
        self._apply_filter()

    def _apply_filter(self):
        """按当前显示方式（底部下拉）+ 工位筛选 过滤 self._items 并重建缩略图列表。

        两个筛选条件取交集：result 过滤（显示方式）与 camera 过滤（按工位）。
        """
        keys = self._FILTER_KEYS.get(self._filter_mode)
        if self._filter_mode == "显示非OK图像":
            # 非OK = 除 OK 外的全部判定结果（NG1/NG2/RST）
            base = [it for it in self._all_items if it.get("result") != "OK"]
        elif keys is None:
            base = list(self._all_items)
        else:
            base = [it for it in self._all_items if it.get("result") in keys]
        if self._station_filter is not None:
            base = [it for it in base if it.get("camera") == self._station_filter]
        self._items = base
        self._rebuild_list()

    def _rebuild_list(self):
        """按 self._items 重建缩略图列表，并刷新标题与首张预览。"""
        if getattr(self, "_list", None) is None:
            return
        self._list.blockSignals(True)
        self._list.clear()
        for i, it in enumerate(self._items):
            icon_item = QListWidgetItem(
                QIcon(_thumb_pixmap(it["pixmap"])),
                f"{it['camera']}  {it['result']}")
            icon_item.setData(Qt.ItemDataRole.UserRole, i)
            icon_item.setToolTip(
                f"{it['camera']}  {it['defect']}  [{it['result']}]\n{it['time']}")
            self._list.addItem(icon_item)
        self._list.blockSignals(False)
        self._idx = 0
        # 首次构建时右侧预览/信息控件尚未创建，跳过（__init__ 末尾统一刷新）
        if getattr(self, "lbl_seq", None) is None:
            return
        if self._items:
            self._list.setCurrentRow(0)
            self._show_current()
        else:
            for lbl in (self.lbl_seq, self.lbl_cam, self.lbl_defect,
                        self.lbl_time, self.lbl_result):
                lbl.setText("--")
            self._img_label.clear()
        if getattr(self, "_title_label", None) is not None:
            station_txt = self._station_filter if self._station_filter else "全部工位"
            self._title_label.setText(
                f"所有工位最新 {len(self._all_items)} 张图像　·　"
                f"显示：{self._filter_mode}　工位：{station_txt}（{len(self._items)} 张）")

    # ------------------------------------------------------------------
    # 工位筛选（下拉式）+ 各工位缓存 NG 图数
    # ------------------------------------------------------------------
    def _build_stat_panel(self):
        """构建「工位筛选」面板：下拉选择工位（全部工位 / 相机1~8）进行筛选，
        下拉项内显示该工位缓存的 NG 图数（NG = NG1 + NG2）；下方另以只读文字
        汇总各工位缓存 NG 图数，便于一眼看出哪个工位不良最多。"""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; }}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)

        # 计算每个工位缓存的 NG 图数（NG = NG1 + NG2，与缓存数据一致，固定不随结果筛选变化）
        cams = [f"相机{i}" for i in range(1, 9)]   # 与 _build_defect_samples 的工位一致
        ng_counts = {c: 0 for c in cams}
        for it in self._all_items:
            if it.get("result") in ("NG1", "NG2"):
                ng_counts[it.get("camera")] = ng_counts.get(it.get("camera"), 0) + 1
        total_ng = sum(ng_counts.values())
        self._ng_counts = ng_counts

        # 工位筛选下拉框（选项内含各工位缓存 NG 图数）
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel("工位筛选")
        lbl.setFixedWidth(56)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        row.addWidget(lbl)
        self._station_combo = QComboBox()
        self._station_combo.setFixedWidth(180)
        self._station_combo.setStyleSheet(
            f"QComboBox {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 3px 6px; font-size: 12px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; }}")
        # 选项顺序：全部工位(NG 总数) + 相机1~8(NG n)
        self._station_options = [None] + cams
        self._station_combo.addItem(f"全部工位  (NG {total_ng})")
        for c in cams:
            self._station_combo.addItem(f"{c}  (NG {ng_counts[c]})")
        # 默认选中：与当前 _station_filter 对应（None → 第 0 项）
        sel_idx = 0
        if self._station_filter in cams:
            sel_idx = self._station_options.index(self._station_filter)
        self._station_combo.setCurrentIndex(sel_idx)
        self._station_combo.currentIndexChanged.connect(self._on_station_combo)
        row.addWidget(self._station_combo)
        row.addStretch()
        lay.addLayout(row)

        # 各工位缓存 NG 图数汇总（只读）
        stat_txt = "　".join(f"{c}:{ng_counts[c]}" for c in cams)
        stat = QLabel(f"各工位缓存 NG 图数：{stat_txt}")
        stat.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; "
            f"background-color: transparent;")
        self._station_stat_label = stat
        lay.addWidget(stat)

        # 每工位 NG 缓存张数设置：设置后点击「应用」即按该张数重建各工位缓存
        set_row = QHBoxLayout()
        set_row.setSpacing(8)
        set_lbl = QLabel("每工位NG缓存张数")
        set_lbl.setFixedWidth(112)
        set_lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        self._ng_cache_spin = QSpinBox()
        self._ng_cache_spin.setFixedWidth(80)
        self._ng_cache_spin.setRange(1, 50)
        self._ng_cache_spin.setSingleStep(1)
        self._ng_cache_spin.setValue(int(getattr(self, "_ng_per_station", 6)))
        self._ng_cache_spin.setStyleSheet(
            f"QSpinBox {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px 6px; font-size: 12px; }}")
        self._ng_cache_apply = QPushButton("应用")
        self._ng_cache_apply.setFixedHeight(26)
        self._ng_cache_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ng_cache_apply.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {COLORS['accent_blue']}; }}")
        self._ng_cache_apply.clicked.connect(
            lambda: self._rebuild_cache(int(self._ng_cache_spin.value())))
        set_row.addWidget(set_lbl)
        set_row.addWidget(self._ng_cache_spin)
        set_row.addSpacing(8)
        set_row.addWidget(self._ng_cache_apply)
        set_row.addStretch()
        lay.addLayout(set_row)
        return frame

    def _refresh_stat_counts(self):
        """刷新下拉项与各工位 NG 图数汇总（缓存重建后调用，保留当前工位筛选）。"""
        cams = [f"相机{i}" for i in range(1, 9)]
        ng_counts = {c: 0 for c in cams}
        for it in self._all_items:
            if it.get("result") in ("NG1", "NG2"):
                ng_counts[it.get("camera")] = ng_counts.get(it.get("camera"), 0) + 1
        self._ng_counts = ng_counts
        total_ng = sum(ng_counts.values())
        if getattr(self, "_station_combo", None) is not None:
            self._station_combo.setItemText(0, f"全部工位  (NG {total_ng})")
            for i, c in enumerate(cams):
                self._station_combo.setItemText(i + 1, f"{c}  (NG {ng_counts[c]})")
        if getattr(self, "_station_stat_label", None) is not None:
            self._station_stat_label.setText(
                "各工位缓存 NG 图数：" + "　".join(f"{c}:{ng_counts[c]}" for c in cams))

    def _rebuild_cache(self, ng_per):
        """按设置的每工位 NG 缓存张数重建各工位图像缓存，并重算统计与筛选。"""
        if ng_per < 1:
            ng_per = 1
        self._ng_per_station = ng_per
        self._all_items = _build_defect_samples(
            self._ng_per_station, self._ok_per_station, self._rst_per_station)
        self._refresh_stat_counts()
        self._apply_filter()

    def _on_station_combo(self, idx):
        """下拉切换工位筛选：0=全部工位，其余为对应相机名。"""
        cam = self._station_options[idx] if 0 <= idx < len(self._station_options) else None
        self._station_filter = cam
        self._apply_filter()

    def _set_station(self, cam):
        """设置工位筛选（供外部调用）：同步更新下拉框选中项并重新过滤。"""
        self._station_filter = cam
        if getattr(self, "_station_combo", None) is not None:
            if cam in self._station_options:
                self._station_combo.setCurrentIndex(self._station_options.index(cam))
            else:
                self._station_combo.setCurrentIndex(0)
        self._apply_filter()

    def _mk_btn(self, text, slot):
        b = QPushButton(text)
        b.setFixedHeight(28)
        b.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['bg_panel']}; }}")
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _mk_info(layout, title):
        """缺陷信息组：小标题（灰）+ 值（白，粗体），返回值标签。"""
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("color: #8A8F99; font-size: 10px; border: none;")
        v = QLabel("--")
        v.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12px; "
            f"font-weight: bold; border: none;")
        box.addWidget(t)
        box.addWidget(v)
        layout.addLayout(box)
        return v

    # ------------------------------------------------------------------
    # 显示 / 切换 / 缩放
    # ------------------------------------------------------------------
    def _on_item_changed(self, cur, _prev):
        if cur is not None:
            self._idx = int(cur.data(Qt.ItemDataRole.UserRole))
            self._show_current()

    def _sync_from_selection(self):
        cur = self._list.currentItem()
        if cur is not None:
            self._idx = int(cur.data(Qt.ItemDataRole.UserRole))
            self._show_current()

    def _show_current(self):
        if not self._items:
            return
        self._idx = max(0, min(self._idx, len(self._items) - 1))
        it = self._items[self._idx]
        self.lbl_seq.setText(f"{self._idx + 1} / {len(self._items)}")
        self.lbl_cam.setText(it["camera"])
        self.lbl_defect.setText(it["defect"])
        self.lbl_time.setText(it["time"])
        self.lbl_result.setText(it["result"])
        # 判定着色：OK 绿色；NG1/NG2 红色；RST 橙色（分通道不良）
        color = {"OK": "#3DBE7B", "NG1": "#F4584E", "NG2": "#F4584E"}.get(
            it["result"], "#E8A33D")
        self.lbl_result.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: bold; border: none;")
        self._render_image()

    def _render_image(self):
        """按当前缩放比例渲染大图（1.0=适应预览区宽度）。"""
        if not self._items:
            return
        src = self._items[self._idx]["pixmap"]
        base_w = max(200, self._img_area.width() - 24)
        base_h = max(150, self._img_area.height() - 24)
        fit = src.scaled(base_w, base_h,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        w = int(fit.width() * self._zoom)
        h = int(fit.height() * self._zoom)
        self._img_label.setPixmap(fit.scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self._img_label.setFixedSize(w, h)
        self._img_holder.setFixedSize(w, h)
        self.lbl_zoom.setText(f"{int(round(self._zoom * 100))}%")

    def _zoom_step(self, factor):
        self._zoom = max(0.2, min(5.0, self._zoom * factor))
        self._render_image()

    def _zoom_fit(self):
        self._zoom = 1.0
        self._render_image()

    def _update_zoom_label(self):
        self.lbl_zoom.setText(f"{int(round(self._zoom * 100))}%")

    def _prev(self):
        if not self._items:
            return
        self._idx = (self._idx - 1) % len(self._items)
        self._list.setCurrentRow(self._idx)

    def _next(self):
        if not self._items:
            return
        self._idx = (self._idx + 1) % len(self._items)
        self._list.setCurrentRow(self._idx)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Left:
            self._prev()
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self._next()
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_image()


def _thumb_pixmap(img):
    """由源 QImage/QPixmap 生成缩略图 QPixmap。"""
    pm = img if isinstance(img, QPixmap) else QPixmap.fromImage(img)
    return pm.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
