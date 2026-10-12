"""缺陷图查看窗口：底部状态栏「缺陷图查看」点击后弹出。

展示所有工位（相机1~相机8）中最新的 50 张缺陷图（演示数据，与生产/调试画布
同款样张生成逻辑 make_sample_frames + 红框缺陷标注）。
- 左侧：50 张缺陷图的缩略图网格（可滚动），每张下方标注工位相机名；
- 点击某一张 → 右侧大图显示，可用「放大 / 缩小 / 适应窗口」调整显示比例；
- 「上一张 / 下一张」在缺陷图之间切换（含键盘左右方向键）；
- 大图下方实时显示该图的缺陷信息：序号 / 工位相机 / 缺陷项 / 检测时间 / 判定。
"""
import random
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QScrollArea, QWidget, QGridLayout,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QPen, QColor, QFont, QKeyEvent

from styles import COLORS

DEFECT_COUNT = 50        # 展示的最新缺陷图数量
THUMB_W, THUMB_H = 132, 99   # 缩略图尺寸


def _build_defect_samples():
    """生成 50 张「最新缺陷图」演示数据：按时间倒序、跨 8 个工位相机分布。

    每条记录：{"pixmap": 带红框标注的缺陷图, "camera": 工位相机名,
               "defect": 缺陷项, "time": 检测时间字符串, "result": "NG"}
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
    for i in range(DEFECT_COUNT):
        cam = cams[rng.randrange(len(cams))]
        defect = rng.choice(pool)
        t = now - timedelta(seconds=30 * (i + 1) + rng.randint(0, 20))
        pix = make_sample_frames(THUMB_W * 3, THUMB_H * 3, count=1,
                                 seed=9000 + i)
        if pix:
            img = pix[0]
            # 红框标注缺陷位置 + 缺陷项文字
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
                "result": "NG",
            })
    return items


class DefectImageWindow(QDialog):
    """缺陷图查看窗口：缩略图网格 + 大图预览（放大/缩小/上一张/下一张/缺陷信息）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("缺陷图查看")
        self.resize(1080, 660)
        self._items = _build_defect_samples()
        self._idx = 0            # 当前查看的缺陷图索引
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
        for i, it in enumerate(self._items):
            icon_item = QListWidgetItem(QIcon(_thumb_pixmap(it["pixmap"])), it["camera"])
            icon_item.setData(Qt.ItemDataRole.UserRole, i)
            icon_item.setToolTip(
                f"{it['camera']}  {it['defect']}\n{it['time']}")
            self._list.addItem(icon_item)
        self._list.currentItemChanged.connect(self._on_item_changed)
        self._list.itemClicked.connect(
            lambda _it: self._sync_from_selection())
        body.addWidget(self._list, 0)

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
    # 外部筛选模式（由底部状态栏「显示所有图像」下拉切换）
    #   - 显示所有图像 / 仅显示不良品图像 / 仅显示良品图像
    # 当前演示数据为全缺陷图，方法主要用于同步窗口标题以反馈当前筛选模式；
    # 后续接入真实良品/全量图源时可直接据此过滤 self._items。
    # ------------------------------------------------------------------
    def set_filter_mode(self, mode):
        if not isinstance(mode, str) or not mode:
            return
        self._filter_mode = mode
        if getattr(self, "_title_label", None) is not None:
            self._title_label.setText(
                f"所有工位最新 {len(self._items)} 张缺陷图　·　筛选：{mode}")

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
        self.lbl_result.setStyleSheet(
            "color: #F4584E; font-size: 12px; font-weight: bold; border: none;")
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
