"""相机标定对话框。

支持两种标定方式：
- 使用像素比例：按「获取图像 → 自动计算像素长宽 → 输入实际长宽 → 更新标定」四步完成。
- 使用标定文件：从已保存的标定参数文件加载（当前为占位）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QDoubleSpinBox, QTabWidget, QSizePolicy, QComboBox,
    QScrollArea, QGridLayout, QFrame, QPlainTextEdit, QFileDialog,
    QMessageBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (QPainter, QPen, QBrush, QColor, QPixmap, QImage,
                         QFont, QLinearGradient)
from PyQt6.QtCore import QRectF

from styles import COLORS

import random
import json
import os
import datetime

# 出厂标定九宫格缩略图尺寸（可统一调整）
_FC_CELL_W, _FC_CELL_H = 120, 134
_FC_IMG_W, _FC_IMG_H = 92, 60
_FC_GRID_SP = 10


class _RmsAxisWidget(QWidget):
    """重投影误差 RMS 结果坐标轴。

    三段色带：0-0.5 渐变绿、0.5-1.0 渐变黄、1.0 以上红色；
    当前结果值标注在色带上对应位置，0.5 / 1.0 处画刻度，
    并按结果所在区间在色带下方对应位置显示结论文字。
    """
    SEG_MSGS = ["推荐使用", "可接受，但可能影响高精度应用", "标定误差较大，需重新标定"]
    SEG_COLORS = ["#1E8E5A", "#D4A800", "#E02020"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rms = None
        self.setMinimumHeight(54)
        self.setMinimumWidth(360)

    def set_value(self, rms):
        self._rms = rms
        self.update()

    def _value_x(self, seg_w, rms):
        """RMS 值映射到色带 x 坐标（>1.0 时向右端收敛）。"""
        if rms < 0.5:
            return seg_w * (rms / 0.5)
        if rms <= 1.0:
            return seg_w + seg_w * ((rms - 0.5) / 0.5)
        return seg_w * 2 + seg_w * min((rms - 1.0) / 0.5, 1.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 28
        seg_w = w / 3.0
        # 三段色带
        g1 = QLinearGradient(0, 0, seg_w, 0)
        g1.setColorAt(0.0, QColor("#1E8E5A"))
        g1.setColorAt(1.0, QColor("#7FD6A8"))
        g2 = QLinearGradient(seg_w, 0, seg_w * 2, 0)
        g2.setColorAt(0.0, QColor("#EAF3C8"))
        g2.setColorAt(1.0, QColor("#F1C40F"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g1))
        p.drawRect(QRectF(0, 0, seg_w, bar_h))
        p.setBrush(QBrush(g2))
        p.drawRect(QRectF(seg_w, 0, seg_w, bar_h))
        p.setBrush(QColor("#E02020"))
        p.drawRect(QRectF(seg_w * 2, 0, seg_w, bar_h))
        # 段间白色分隔线
        p.setBrush(QColor("#FFFFFF"))
        p.drawRect(QRectF(seg_w - 1, 0, 2, bar_h))
        p.drawRect(QRectF(seg_w * 2 - 1, 0, 2, bar_h))

        # 0.5 / 1.0 刻度线与刻度值
        tick_pen = QPen(QColor("#9AA0A8"), 1)
        p.setFont(QFont("Microsoft YaHei", 9))
        p.setPen(tick_pen)
        for i, tx in enumerate((int(seg_w), int(seg_w * 2))):
            p.drawLine(tx, bar_h, tx, bar_h + 8)
            p.drawText(tx - 20, bar_h + 8, 40, 16,
                       Qt.AlignmentFlag.AlignCenter, "0.5" if i == 0 else "1.0")

        rms = self._rms
        if rms is None:
            p.end()
            return

        # 当前结果值标注在色带对应位置
        vx = max(24, min(w - 24, self._value_x(seg_w, rms)))
        f = QFont("Microsoft YaHei", 10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(int(vx) - 40, 0, 80, bar_h,
                   Qt.AlignmentFlag.AlignCenter, f"{rms:.2f}")
        p.end()


class CameraCalibrationDialog(QDialog):
    """相机标定对话框。"""

    def __init__(self, parent=None, anchor_card=None, run_log=None):
        super().__init__(parent)
        self.setWindowTitle("相机标定")
        # 仅设较小的下限，避免与「根据内容自适应宽高 + 右上/底部锚定」的几何冲突
        self.setMinimumSize(360, 160)
        # 用于「与「生产统计」卡片右上角对齐」的锚点（由调试界面传入）
        self._anchor_card = anchor_card
        self._run_log = run_log
        # 初始给一个合理尺寸；真正的位置/尺寸在 showEvent 中按生产统计卡片对齐
        self.resize(880, 430)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        tabs = QTabWidget()
        tabs.setStyleSheet(self._tab_style())
        self._tabs = tabs

        # ---------- 使用像素比例 ----------
        pixel_page = self._build_pixel_page()
        tabs.addTab(pixel_page, "使用像素比例")

        # ---------- 使用标定文件 ----------
        file_page = self._build_file_page()
        tabs.addTab(file_page, "使用标定文件")

        # ---------- 出厂标定 ----------
        factory_page = self._build_factory_page()
        self._factory_page = factory_page
        tabs.addTab(factory_page, "出厂标定")

        # 切换子页时按当前页内容自适应对话框宽高，互不影响
        # （必须在所有 addTab 之后连接：addTab 会触发 currentChanged，构造期不应调整尺寸）
        tabs.currentChanged.connect(self._on_tab_changed)

        lay.addWidget(tabs, 1)

        # 底部确认按钮
        confirm = QPushButton("确认")
        confirm.setStyleSheet(self._btn_blue_style())
        confirm.setFixedWidth(90)
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(self.accept)
        lay.addWidget(confirm, alignment=Qt.AlignmentFlag.AlignRight)
        self._confirm_btn = confirm

    # ------------------------------------------------------------------
    # 业务逻辑
    # ------------------------------------------------------------------
    def _frame_margins(self):
        """返回整窗框架（标题栏 + 边框）相对客户区的四向偏移 (left, top, right, bottom)。

        用于把「客户区尺寸/坐标」换算成「整窗（含标题栏）尺寸/坐标」：
        setGeometry() 设置的是客户区，整窗 = 客户区 + 框架偏移。
        离屏/无框架环境下 frameGeometry() == geometry()，四值均为 0，
        此时 setGeometry 即作用于整窗，无需额外换算。
        """
        fg = self.frameGeometry()
        g = self.geometry()
        fl = g.x() - fg.x()
        ft = g.y() - fg.y()
        fr = fg.right() - g.right()
        fb = fg.bottom() - g.bottom()
        return max(fl, 0), max(ft, 0), max(fr, 0), max(fb, 0)

    def _place_on_screen(self, w: int, h: int):
        """把对话框调整到目标尺寸，并钳制 + 居中到当前屏幕可用区域。

        避免从较窄的子页（使用像素比例）切换到「出厂标定」页放大窗口时，
        仅用 resize() 向右下生长导致右/下边缘超出屏幕被裁切（右侧显示不完整）。
        考虑整窗框架（标题栏 + 边框）后居中，预留安全边距，避免窗口边框导致略微超出可用区域。
        """
        from PyQt6.QtWidgets import QApplication
        fl, ft, fr, fb = self._frame_margins()
        w_outer = w + fl + fr
        h_outer = h + ft + fb
        scr = self.screen() or QApplication.primaryScreen()
        if scr is None:
            self.setGeometry(fl, ft, w, h)
            return
        avail = scr.availableGeometry()
        M = 10  # 安全边距（像素），给窗口边框留余量
        w_outer = min(w_outer, avail.width() - M)
        h_outer = min(h_outer, avail.height() - M)
        w = w_outer - fl - fr
        h = h_outer - ft - fb
        x = avail.x() + max(0, (avail.width() - w_outer) // 2)
        y = avail.y() + max(0, (avail.height() - h_outer) // 2)
        # 客户区左上 = 整窗左上 + 框架偏移
        self.setGeometry(x + fl, y + ft, w, h)

    def _align_to_anchor(self):
        """将对话框锚定到右侧信息栏（「生产统计」卡片 + 「运行日志」卡片）：

        统一逻辑（三个子页完全一致，切换后均复执行）：
        1) 整窗（含「相机标定」标题栏）**右上角**始终对齐「生产统计」卡片右上角
           （且整窗**顶部**对齐其顶部，标题栏高度计入预算）；
        2) 每个子页切换后，对话框宽高**按当前页内容自适应**：取当前页自身的
           sizeHint（三页均用 QScrollArea 包裹，sizeHint 即内容自然大小，不取
           QTabWidget 的最大值，也不受切换过渡态脏值影响）；
        3) 若当前页内容在高度方向放不下（内容高 > 「生产统计顶→运行日志底」
           列高），则：整窗**高度填满整列**（顶部=生产统计顶、底部=运行日志底），
           页内滚动区自动出现滚动条承载溢出内容；若放得下，则保持内容自身高度
           （顶部锚定、底部随内容，不强行拉到运行日志底）。
        无锚点（卡片不可见）时回退到屏幕居中。
        """
        from PyQt6.QtWidgets import QApplication
        anchor = getattr(self, "_anchor_card", None)
        if anchor is None or not anchor.isVisible():
            self._place_on_screen(self.width() or 880, self.height() or 430)
            return

        fl, ft, fr, fb = self._frame_margins()

        # 生产统计卡片：右上角 + 顶部锚
        ag = anchor.geometry()
        a_tl = anchor.mapToGlobal(ag.topLeft())
        right_x = a_tl.x() + ag.width()
        top_y = a_tl.y()

        # 运行日志卡片：给出整列高度的底部边界
        rl = getattr(self, "_run_log", None)
        if rl is not None and rl.isVisible():
            rg = rl.geometry()
            r_tl = rl.mapToGlobal(rg.topLeft())
            bottom_y = r_tl.y() + rg.height()
        else:
            bottom_y = top_y + ag.height()

        # 整列高度（整窗可占用，含标题栏）：生产统计顶 -> 运行日志底
        max_outer_h = bottom_y - top_y
        # 可用客户区高度（不含框架），供 _sync_factory_layout 钳制放大面板/宫格
        self._max_client_h = max(max_outer_h - ft - fb, 240)

        scr = self.screen() or QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else None
        M = 10  # 安全边距，给窗口边框留余量

        # 当前子页面自身内容大小（三页均为 QWidget+QScrollArea，sizeHint = 内容自然大小，
        # 与切换过渡态、QTabWidget 最大值均无关，稳定可靠）
        page = self._tabs.currentWidget()
        psh = page.sizeHint()

        # 对话框外壳在「页内容」之外的固定开销：
        #   上边距16 + 页签栏 + 间距12 + 确认按钮 + 下边距16（左右各 16）
        tab_h = self._tabs.tabBar().sizeHint().height()
        conf_h = self._confirm_btn.sizeHint().height()
        chrome_h = 16 + tab_h + 12 + conf_h + 16
        chrome_w = 16 + 16

        # 期望客户区尺寸 = 内容 + 外壳开销
        want_client_w = psh.width() + chrome_w
        want_client_h = psh.height() + chrome_h

        # 高度：超过整列则用整列（页内滚动条承载溢出），否则按内容
        col_client_h = max_outer_h - ft - fb
        client_h = min(want_client_h, col_client_h)
        client_h = max(client_h, 160)

        # 宽度：按当前页内容自适应（出厂标定等较宽页会自动加宽）。
        # 仅受「整屏可用宽度」约束（不超过屏幕），从而保证整页在宽度方向完整显示；
        # 不再用「卡片右缘 - 屏幕左缘」来钳制宽度——否则较宽页会被横向裁切、且横向滚动条已关闭时
        # 右侧（放大面板/九宫格）显示不完整。右缘尽量对齐卡片右缘（见下方 x_outer 钳制），
        # 若内容过宽导致对齐后左缘会越出屏幕，则整体左移到屏内、整页完整显示（右缘可能略超出卡片）。
        client_w = want_client_w
        if avail is not None:
            client_w = min(client_w, avail.width() - M)
        client_w = max(client_w, 360)

        # 整窗尺寸（客户区 + 框架偏移）与右上角定位
        w_outer = client_w + fl + fr
        h_outer = client_h + ft + fb
        x_outer = right_x - w_outer          # 右上角对齐卡片右上角
        y_outer = top_y                      # 顶部对齐卡片顶部
        if avail is not None:
            x_outer = max(avail.left() + 4, min(x_outer, avail.right() - w_outer - 4))
            y_outer = max(avail.top() + 4, min(y_outer, avail.bottom() - h_outer - 4))

        # setGeometry 设的是客户区，落定整窗位置
        self.setGeometry(x_outer + fl, y_outer + ft, client_w, client_h)

    def _on_tab_changed(self, idx: int):
        """切换子页时让对话框尺寸自适应当前子页，并与「生产统计」卡片右上角对齐。"""
        page = self._tabs.widget(idx)
        # 先按当前页设定尺寸与位置（右上角对齐），再同步出厂标定页 4:3 布局
        QTimer.singleShot(0, self._align_to_anchor)
        if page is self._factory_page:
            QTimer.singleShot(0, self._sync_factory_layout)

    def _auto_compute(self):
        """自动计算像素长宽（占位：后续可接入真实 ROI 测量）。"""
        # 默认示例值：长度 360 Pix、宽度 180 Pix
        self.len_pix.setValue(360)
        self.wid_pix.setValue(180)

    def _update_ratio(self):
        """根据像素长宽与实际长宽更新像素比例。"""
        lp = self.len_pix.value()
        wp = self.wid_pix.value()
        lm = self.len_mm.value()
        wm = self.wid_mm.value()
        if lp <= 0 or wp <= 0:
            return
        ratio = (lm / lp + wm / wp) / 2.0
        self.ratio.setValue(round(ratio, 5))

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _step_label(self, text: str, width: int = 110) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")
        lbl.setFixedWidth(width)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return lbl

    def _combo_style(self) -> str:
        return (
            f"QComboBox {{ color: {COLORS['text_primary']}; background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}"
            f"QComboBox:hover {{ border: 1px solid {COLORS['accent_blue']}; }}"
            f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; "
            f"width: 18px; border: none; }}"
            f"QComboBox QAbstractItemView {{ color: {COLORS['text_primary']}; "
            f"background-color: {COLORS['bg_card']}; selection-background-color: {COLORS['accent_blue']}; }}")

    def _plain_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px;")
        return lbl

    def _make_spin(self, decimals: int, value: float, suffix: str = "", readonly: bool = False) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        # 注意：QDoubleSpinBox 默认最大值为 99.99，必须先设上下限再 setValue，
        # 否则 setValue(>99.99) 会被默认上限截断为 99.99。
        spin.setMinimum(0.00001)
        spin.setMaximum(999999.99999)
        spin.setValue(value)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setSuffix(f" {suffix}".rstrip())
        spin.setFixedWidth(90)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if readonly:
            # 自动计算/自动填充的字段：仅展示、不可手动输入
            spin.setReadOnly(True)
        spin.setStyleSheet(
            f"QDoubleSpinBox {{ color: {COLORS['text_primary']}; background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; padding: 4px 6px; font-size: 13px; }}"
            f"QDoubleSpinBox:focus {{ border: 1px solid {COLORS['accent_blue']}; }}")
        return spin

    def _check_style(self) -> str:
        return f"color: {COLORS['text_primary']}; font-size: 13px;"

    def _btn_blue_style(self) -> str:
        return (
            f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 4px; padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}DD; }}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_blue']}BB; }}"
        )

    def _tab_style(self) -> str:
        return f"""
            QTabWidget::pane {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                padding: 8px 24px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['accent_blue']};
                border-bottom: 2px solid {COLORS['accent_blue']};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
            }}
        """

    # ==================================================================
    # 子页面构建（三页均用「QScrollArea + 内层内容」包裹：
    # 内容过高时由页内滚动区出滚动条，卡片高度随之钳到列高）
    # ==================================================================
    def _wrap_scroll_page(self, build_content, scrollable: bool = True):
        """构造一个「页面 QWidget（含外边距）+ 内容」的页。

        - scrollable=True（默认）：内容外层再包一层 QScrollArea（widgetResizable），
          内容过高时滚动区自动出**纵向**滚动条，对话框高度钳到「生产统计顶→运行日志底」
          列高。用于「出厂标定」页。
        - scrollable=False：不包滚动区，内容直接铺在页面内、完整显示、无任何滚动条。
          用于内容固定且不会超长的「使用像素比例」「使用标定文件」页。

        两种方式都有确定的 sizeHint（= 内容自然大小），对话框按该 sizeHint 自适应宽高，
        与 QTabWidget 的最大值、切换过渡态脏值均无关。
        """
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(10, 10, 10, 10)
        page_lay.setSpacing(10)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(8, 8, 8, 8)
        build_content(content_lay)
        content_lay.addStretch(1)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            # 出厂标定页：关闭横向滚动条（内容已按整列宽度自适应，不出现左→右滚动条），
            # 仅保留纵向滚动条承接「内容过高」的溢出。
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            scroll.setWidget(content)
            page_lay.addWidget(scroll, 1)
        else:
            page_lay.addWidget(content, 1)
        return page

    def _build_pixel_page(self) -> QWidget:
        """「使用像素比例」子页面（内容固定、不会超长，正常无需滚动条）。"""
        STEP_W = 130  # 各步骤标题统一宽度，保证第1~4步文字左对齐

        def build(content_lay):
            content_lay.setSpacing(18)
            # 第1步：获取图像（下拉选择）
            s1 = QHBoxLayout()
            s1.setSpacing(8)
            s1.addWidget(self._step_label("第1步：获取图像", STEP_W))
            self.src_combo = QComboBox()
            self.src_combo.addItems(["获取当前图像", "导入本地图片"])
            self.src_combo.setFixedWidth(160)
            self.src_combo.setStyleSheet(self._combo_style())
            s1.addWidget(self.src_combo)
            s1.addStretch(1)
            content_lay.addLayout(s1)

            # 第2步：自动计算
            s2 = QHBoxLayout()
            s2.setSpacing(8)
            btn_auto = QPushButton("第2步：自动计算")
            btn_auto.setStyleSheet(
                self._btn_blue_style() + " text-align: left; padding-left: 0px; "
                "padding-right: 8px; font-size: 13px; font-weight: bold;")
            btn_auto.setFixedWidth(STEP_W)
            btn_auto.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_auto.clicked.connect(self._auto_compute)
            s2.addWidget(btn_auto)
            s2.addSpacing(12)
            s2.addWidget(self._plain_label("长度："))
            self.len_pix = self._make_spin(decimals=2, value=360, suffix="", readonly=True)
            s2.addWidget(self.len_pix)
            s2.addWidget(self._plain_label("Pix"))
            s2.addSpacing(24)
            s2.addWidget(self._plain_label("宽度："))
            self.wid_pix = self._make_spin(decimals=2, value=180, suffix="", readonly=True)
            s2.addWidget(self.wid_pix)
            s2.addWidget(self._plain_label("Pix"))
            s2.addStretch(1)
            content_lay.addLayout(s2)

            # 第3步：输入长宽
            s3 = QHBoxLayout()
            s3.setSpacing(8)
            s3.addWidget(self._step_label("第3步：输入长宽", STEP_W))
            s3.addSpacing(12)
            s3.addWidget(self._plain_label("长度："))
            self.len_mm = self._make_spin(decimals=2, value=1.0, suffix="")
            s3.addWidget(self.len_mm)
            s3.addWidget(self._plain_label("mm"))
            s3.addSpacing(24)
            s3.addWidget(self._plain_label("宽度："))
            self.wid_mm = self._make_spin(decimals=2, value=0.5, suffix="")
            s3.addWidget(self.wid_mm)
            s3.addWidget(self._plain_label("mm"))
            s3.addStretch(1)
            content_lay.addLayout(s3)

            # 第4步：更新标定
            s4 = QHBoxLayout()
            s4.setSpacing(8)
            btn_update = QPushButton("第4步：更新标定")
            btn_update.setStyleSheet(
                self._btn_blue_style() + " text-align: left; padding-left: 0px; "
                "padding-right: 8px; font-size: 13px; font-weight: bold;")
            btn_update.setFixedWidth(STEP_W)
            btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_update.clicked.connect(self._update_ratio)
            s4.addWidget(btn_update)
            s4.addSpacing(12)
            s4.addWidget(self._plain_label("像素比例："))
            self.ratio = self._make_spin(decimals=5, value=0.00278, suffix="", readonly=True)
            s4.addWidget(self.ratio)
            s4.addWidget(self._plain_label("mm/Pix"))
            s4.addStretch(1)
            content_lay.addLayout(s4)

        # 内容固定、不会超长：关闭滚动区，页面内完整显示、无纵向/横向滚动条
        return self._wrap_scroll_page(build, scrollable=False)

    def _build_file_page(self) -> QWidget:
        """「使用标定文件」子页面。"""

        def build(content_lay):
            file_tip = QLabel("使用标定文件：从已保存的标定参数文件加载（功能开发中）。")
            # 不换行：单整行完整显示，对话框宽度按此文字自然宽度自适应
            file_tip.setWordWrap(False)
            file_tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
            content_lay.addWidget(file_tip)

        # 内容固定、不会超长：关闭滚动区，页面内完整显示、无纵向/横向滚动条
        return self._wrap_scroll_page(build, scrollable=False)

    # ==================================================================
    # 出厂标定子页面
    # ==================================================================
    def _build_factory_page(self) -> QWidget:
        """构建「出厂标定」子页面：九宫格抓取 → 提取特征+计算内参 → 应用/保存。"""
        self._factory_cells = []
        self._intrinsics = None
        self._debug_view = self.parent()

        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(10, 10, 10, 10)
        page_lay.setSpacing(10)

        # 页面头部：标题居左，「加载演示示例」按钮居右上角
        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header = QLabel("出厂标定 · 9 张标定板图像法（5×5 黑圆散点标定板）")
        header.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: bold;")
        b_demo = QPushButton("加载演示示例")
        b_demo.setStyleSheet(
            self._btn_blue_style() +
            " padding: 6px 16px; font-size: 13px; font-weight: bold;")
        b_demo.setCursor(Qt.CursorShape.PointingHandCursor)
        b_demo.setToolTip("一键填入 9 张不同位置的标定板图像")
        b_demo.clicked.connect(lambda _checked=False: self._load_demo_factory())
        header_row.addWidget(header)
        header_row.addStretch(1)
        header_row.addWidget(b_demo)
        page_lay.addLayout(header_row)

        tip = QLabel(
            "将标定板依次置于相机视野的 9 个位置抓取图像，提取特征后计算并应用相机内参。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        page_lay.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # 关闭横向滚动条：出厂标定页内容按整列宽度自适应，不出现左→右滚动条；
        # 仅「内容过高」时由纵向滚动条承接（横向不裁切、不出现横向滚动条）。
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(4, 4, 4, 4)
        content_lay.setSpacing(12)

        # ---- 第1步：九宫格 ----
        g1 = QGroupBox("第1步：依次抓取 9 张标定板图像")
        g1.setStyleSheet(self._group_style())
        self._factory_g1 = g1
        g1_lay = QVBoxLayout(g1)
        g1_lay.setSpacing(10)
        # 获取方式下拉选择：依次抓取 / 导入（默认依次抓取）
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("获取方式：")
        mode_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")
        self._src_mode = QComboBox()
        self._src_mode.addItem("依次抓取9张标定板图像", "capture")
        self._src_mode.addItem("导入9张标定板图像", "import")
        self._src_mode.setFixedWidth(220)
        self._src_mode.setStyleSheet(self._combo_style())
        self._src_mode.currentIndexChanged.connect(self._on_src_mode_changed)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._src_mode)
        mode_row.addStretch(1)
        g1_lay.addLayout(mode_row)
        sub = QLabel("每宫格说明标定板放置位置；点击「获取当前图像」抓取当前相机画布画面。")
        sub.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self._factory_sub = sub
        g1_lay.addWidget(sub)

        # 左：3×3 缩略图宫格；右：点击后放大显示
        body = QHBoxLayout()
        body.setSpacing(14)
        grid_host = QWidget()
        self._factory_grid_host = grid_host
        grid_host.setFixedWidth(384)   # 固定宽度，避免「宽度由拉伸比例决定→尺寸循环依赖」导致估算失真
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_FC_GRID_SP)
        positions = ["左上", "中上", "右上", "左中", "中间", "右中", "左下", "中下", "右下"]
        for idx, pos in enumerate(positions):
            cell = self._make_factory_cell(idx, pos)
            self._factory_cells.append(cell)
            r, c = divmod(idx, 3)
            grid.addWidget(cell["frame"], r, c)
        body.addWidget(grid_host, 5)

        # 右侧放大显示面板
        zoom = QFrame()
        zoom.setStyleSheet(
            f"QFrame {{ background-color: #F2F1EC; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        zl = QVBoxLayout(zoom)
        zl.setContentsMargins(10, 10, 10, 10)
        zl.setSpacing(6)
        self._factory_zoom_img = QLabel("点击左侧宫格\n查看放大图像")
        self._factory_zoom_img.setMinimumSize(320, 1)
        # 右侧放大面板宽高比 4:3（宽=现状、高=宽*3/4），具体高度由 _sync_factory_layout 在布局后设置
        self._factory_zoom_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._factory_zoom_img.setStyleSheet(
            "color: #888888; font-size: 13px; background-color: transparent;")
        self._factory_zoom_cap = QLabel("未选择图像")
        self._factory_zoom_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._factory_zoom_cap.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; "
            f"background-color: transparent;")
        zl.addWidget(self._factory_zoom_img, 1)
        zl.addWidget(self._factory_zoom_cap)
        self._factory_zoom = zoom
        zoom.setFixedWidth(360)         # 固定宽度，与宫格等宽比稳定，避免切换/缩放时尺寸循环
        zoom.installEventFilter(self)   # 面板宽度变化时重算 4:3 高度（布局稳定后触发）
        body.addWidget(zoom, 6)
        self._selected_factory = None
        g1_lay.addLayout(body)
        content_lay.addWidget(g1)

        # ---- 第2步：提取特征 + 计算内参（合并为一个按钮）----
        op_row = QHBoxLayout()
        op_row.setSpacing(10)
        b2 = self._big_btn("第2步：提取标定板图像特征及计算相机内参",
                           lambda _checked=False: self._extract_and_compute())
        op_row.addWidget(b2)
        op_row.addStretch(1)
        content_lay.addLayout(op_row)

        # ---- 第2步结果：内参展示（左：K 矩阵；右：计算结果）----
        self._intr_group = QGroupBox("第2步：相机内参参数（计算后显示）")
        self._intr_group.setStyleSheet(self._group_style())
        ig_lay = QVBoxLayout(self._intr_group)
        ig_lay.setSpacing(8)
        # 重投影误差 RMS 结果坐标轴：置于第3步区域顶部
        self._rms_indicator = self._make_rms_indicator()
        ig_lay.addWidget(self._rms_indicator)
        intr_cols = QHBoxLayout()
        intr_cols.setSpacing(0)
        self._intr_edit = QPlainTextEdit()
        self._intr_edit.setReadOnly(True)
        self._intr_edit.setMinimumHeight(140)
        self._intr_edit.setMinimumWidth(230)
        self._intr_edit.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {COLORS['bg_dark']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; "
            f"font-family: 'Consolas', 'Cascadia Code', 'Microsoft YaHei', monospace; "
            f"font-size: 12px; padding: 8px; }}")
        # 左右两个文本框直接并排（同一 HBox、同一 stretch），保证等高
        intr_cols.addWidget(self._intr_edit, 3)
        # 竖直分隔线（虚线感用暗色实线代替）
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        intr_cols.addWidget(sep)
        self._intr_detail = QPlainTextEdit()
        self._intr_detail.setReadOnly(True)
        self._intr_detail.setMinimumHeight(140)
        self._intr_detail.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {COLORS['bg_dark']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; "
            f"font-family: 'Consolas', 'Cascadia Code', 'Microsoft YaHei', monospace; "
            f"font-size: 12px; padding: 8px; }}")
        intr_cols.addWidget(self._intr_detail, 6)
        ig_lay.addLayout(intr_cols)
        content_lay.addWidget(self._intr_group)

        # ---- 第3步：应用 / 保存 ----
        g4 = QGroupBox("第3步：应用于当前相机或保存为本地文件")
        g4.setStyleSheet(self._group_style())
        g4_lay = QHBoxLayout(g4)
        g4_lay.setSpacing(10)
        b4a = self._big_btn("应用于当前相机",
                           lambda _checked=False: self._apply_to_camera())
        b4s = self._big_btn("保存为本地文件",
                           lambda _checked=False: self._save_to_file())
        breset = QPushButton("重置")
        breset.setStyleSheet(self._btn_ghost_style())
        breset.setCursor(Qt.CursorShape.PointingHandCursor)
        breset.clicked.connect(lambda _checked=False: self._reset_factory())
        g4_lay.addWidget(b4a)
        g4_lay.addWidget(b4s)
        g4_lay.addStretch(1)
        g4_lay.addWidget(breset)
        content_lay.addWidget(g4)

        content_lay.addStretch(1)
        scroll.setWidget(content)
        page_lay.addWidget(scroll, 1)

        self._factory_status = QLabel("请在第1步依次抓取 9 张标定板图像。")
        self._factory_status.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px;")
        page_lay.addWidget(self._factory_status)

        # 初始渲染（占位）
        for idx in range(9):
            self._render_cell(idx)

        # 关键修正：QScrollArea（widgetResizable）的 sizeHint().width() 会低估内容宽度
        # （不反映内部固定宽度的九宫格 384 + 放大面板 360），导致 _align_to_anchor 按偏小的
        # sizeHint 设宽、横向滚动条已关闭时右侧被裁切（宽度方向显示不完整）。
        # 此处把滚动区最小宽度钉到内容自然宽度，使页面 sizeHint 准确反映真实所需宽度，
        # 对话框即可「自动加宽」到内容完整宽度。
        content_min_w = content.sizeHint().width()
        if content_min_w > 0:
            scroll.setMinimumWidth(content_min_w)

        return page

    def _make_factory_cell(self, idx: int, position_text: str) -> dict:
        """构造九宫格中一个宫格（缩略图）：位置说明 + 图像 + 获取按钮。

        点击缩略图会在右侧放大显示（_select_cell）。
        """
        cell = QFrame()
        cell.setFixedSize(_FC_CELL_W, _FC_CELL_H)
        cell.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_panel']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; }}")
        cl = QVBoxLayout(cell)
        # 收紧上下边距与间距：缩小缩略图与「位置：获取图像」行之间的间隙，
        # 让图像高度可以按 4:3 贴满单元（见 _sync_factory_layout 的 4:3 反推）。
        cl.setContentsMargins(8, 3, 8, 4)
        cl.setSpacing(2)

        img = QLabel()
        img.setFixedSize(_FC_IMG_W, _FC_IMG_H)
        img.setStyleSheet(
            f"background-color: #15171B; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px;")
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setCursor(Qt.CursorShape.PointingHandCursor)
        img.setToolTip("点击放大查看")
        img.setProperty("cell_idx", idx)
        img.installEventFilter(self)

        btn = QPushButton("获取图像")
        # 小号按钮样式：宫格宽度有限，缩小字号与内边距避免文字显示不完整
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLORS['accent_blue']}; color: white; "
            f"border: none; border-radius: 3px; padding: 2px 6px; "
            f"font-size: 10px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_blue']}DD; }}"
            f"QPushButton:pressed {{ background-color: {COLORS['accent_blue']}BB; }}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, i=idx: self._on_cell_action(i))

        # 位置说明放在缩略图下方、获取按钮左侧（如「左上：获取图像」）
        cap_row = QHBoxLayout()
        cap_row.setSpacing(3)
        pos_lbl = QLabel(position_text + "：")
        pos_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 9px; font-weight: bold; "
            f"background-color: transparent;")
        pos_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cap_row.addWidget(pos_lbl)
        cap_row.addWidget(btn)

        cl.addWidget(img, 1, Qt.AlignmentFlag.AlignCenter)
        cl.addLayout(cap_row)

        return {"frame": cell, "img": img, "btn": btn,
                "captured": None, "has_features": False, "feature_ok": None,
                "grid": None}

    def eventFilter(self, obj, event):
        """宫格缩略图点击 → 右侧放大显示；放大面板宽度变化 → 重算 4:3 高度。"""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            idx = obj.property("cell_idx")
            if idx is not None:
                self._select_cell(int(idx))
                return True
        if obj is getattr(self, "_factory_zoom", None) and \
                event.type() == QEvent.Type.Resize:
            # 延迟到本拍布局结束后再同步，确保读到的是稳定后的宽度
            QTimer.singleShot(0, self._sync_factory_layout)
        return super().eventFilter(obj, event)

    def _select_cell(self, idx: int):
        """选中某张标定板图像，在右侧面板放大显示。"""
        self._selected_factory = idx
        for i, c in enumerate(self._factory_cells):
            c["frame"].setStyleSheet(
                f"QFrame {{ background-color: {COLORS['bg_panel']}; "
                f"border: 2px solid {COLORS['accent_blue'] if i == idx else COLORS['border']}; "
                f"border-radius: 6px; }}")
        self._update_zoom()

    def _update_zoom(self):
        """刷新右侧放大显示面板。"""
        idx = self._selected_factory
        cap_lbl = self._factory_zoom_img
        if idx is None:
            cap_lbl.setPixmap(QPixmap())
            cap_lbl.setText("点击左侧宫格\n查看放大图像")
            self._factory_zoom_cap.setText("未选择图像")
            return
        positions = ["左上", "中上", "右上", "左中", "中间", "右中", "左下", "中下", "右下"]
        self._factory_zoom_cap.setText(f"第 {idx + 1} 张 · {positions[idx]}")
        # 按右侧面板当前实际尺寸等比缩放（KeepAspectRatio），
        # 图像标签比例已与原图 224:148 一致（见 _sync_factory_layout），完整显示不裁切
        tw = max(1, cap_lbl.width())
        th = max(1, cap_lbl.height())
        pm = self._compose_cell_pixmap(idx).scaled(
            tw, th, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        cap_lbl.setText("")
        cap_lbl.setPixmap(pm)

    def resizeEvent(self, event):
        """窗口尺寸变化时，同步第1步布局并重绘右侧放大图以适配面板实际大小。"""
        super().resizeEvent(event)
        # 仅当前页是出厂标定页时同步：切换过渡态（其他页）读到的是过期面板宽度，
        # 会把放大面板/宫格 setFixedHeight 成失真的窄高尺寸
        if self._tabs.currentWidget() is getattr(self, "_factory_page", None):
            # 延迟到布局稳定后同步，避免读到过期的面板宽度导致比例失真
            QTimer.singleShot(0, self._sync_factory_layout)
        if getattr(self, "_selected_factory", None) is not None:
            self._update_zoom()

    def showEvent(self, event):
        """首次显示后布局确定：按右侧面板实际宽度同步 4:3 与等高，并定位到生产统计卡片右上角。"""
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_factory_layout)
        QTimer.singleShot(0, self._align_to_anchor)

    def _sync_factory_layout(self):
        """同步「出厂标定」第1步布局：

        - 右侧放大面板高度随宽度按原图比例 224:148 推导（含说明行与边距），
          图像完整显示、不裁切；
        - 左侧 9 宫格整体高度与右侧放大面板等高，单元格高度自适应贴合。
        """
        zoom = getattr(self, "_factory_zoom", None)
        grid_host = getattr(self, "_factory_grid_host", None)
        cells = getattr(self, "_factory_cells", None)
        if zoom is None or grid_host is None or not cells:
            return
        zw = zoom.width()
        if zw <= 0:
            return
        # 放大图标签宽度 = 面板宽 - 左右边距(10×2)；按原图画布比例 224:148 设高。
        # ⚠️ 必须钳制上限：布局过渡态 zoom.width() 可能读到过期的超大值（如整页宽），
        #    不钳制会把面板/宫格 setFixedHeight 成窄高失真（放大图变成巨大白板）。
        img_w = min(max(120, zw - 20), 460)
        img_h = min(max(80, int(round(img_w * 148.0 / 224.0))), 310)
        cap_h = max(16, self._factory_zoom_cap.sizeHint().height())
        # 面板总高 = 上边距10 + 图像 + 间距6 + 说明行 + 下边距10
        zh = 10 + img_h + 6 + cap_h + 10
        # 宫格缩略图按 4:3 反推所需整体高度：图宽 104 → 图高 78，
        # 加上单元内容实际开销；不足则抬升 zh，九宫格与放大面板保持等高。
        cw = _FC_CELL_W - 16
        ch43 = int(round(cw * 3.0 / 4.0))
        btn_h = max(18, cells[0]["btn"].sizeHint().height())
        cell_overhead = 3 + 4 + 2 + btn_h  # 上边距3 + 下边距4 + 间距2 + 说明行
        need_zh = 3 * (ch43 + cell_overhead) + 2 * _FC_GRID_SP
        if zh < need_zh:
            zh = need_zh
        # 再按「生产统计顶→运行日志底」预算钳制：给第1步以外的标题/说明/第2/3步留 ~300px
        max_ch = getattr(self, "_max_client_h", 0)
        if max_ch > 0:
            zh = min(zh, max(220, max_ch - 300))
        if getattr(self, "_fac_zh", None) == zh:
            return
        self._fac_zh = zh
        zoom.setFixedHeight(zh)
        grid_host.setFixedHeight(zh)
        self._factory_zoom_img.setFixedSize(img_w, img_h)
        # 单元格高度贴合整体高度（宽度保持 _FC_CELL_W 不变）。
        # 图高按 4:3 反推并尽量贴满单元：不再虚留 44px 大间隙（用户指出箭头处空白）；
        # 整体高度被预算钳制时图高优先让位，保证内容不溢出。
        cell_h = max(58, (zh - 2 * _FC_GRID_SP) // 3)
        img_w = _FC_CELL_W - 16
        img_h = min(ch43, max(24, cell_h - cell_overhead))
        for idx, c in enumerate(cells):
            c["frame"].setFixedSize(_FC_CELL_W, cell_h)
            c["img"].setFixedSize(img_w, img_h)
            self._render_cell(idx, img_w, img_h)
        if getattr(self, "_selected_factory", None) is not None:
            self._update_zoom()

    def _dot_grid(self, idx: int, seed: int):
        """第 idx 宫格标定板的 5×5 黑圆散点在 224×148 画布内的坐标。

        点阵按九宫格位置摆放在画布对应区域（左上格→点阵位于左上，中间格→居中……）。
        等间距规则点阵：相邻间隙完全一致，无透视倾斜。
        """
        W, H = 224, 148
        col, row = idx % 3, idx // 3
        rw, rh = 76, 62                       # 点阵区域尺寸
        cx0 = [12 + rw / 2.0, W / 2.0, W - 12 - rw / 2.0][col]
        cy0 = [10 + rh / 2.0, H / 2.0, H - 10 - rh / 2.0][row]
        sx, sy = 10.0, 10.0                  # 水平/垂直等间距 (px)
        grid = []
        for r in range(5):
            rlist = []
            for c in range(5):
                gx = cx0 + (c - 2) * sx
                gy = cy0 + (r - 2) * sy
                rlist.append((gx, gy))
            grid.append(rlist)
        return grid

    def _factory_sample(self, idx: int):
        """生成第 idx 宫格的标定板占位样张（无实时画面时回退用）。

        白底标定板 + 5×5 黑圆散点图，点阵位置与该宫格标注的放置位置一致。
        返回 (QPixmap, grid)，grid 与图像中的散点严格对齐，供第2步特征曲线叠加。
        """
        W, H = 224, 148
        grid = self._dot_grid(idx, 5000 + idx)
        pm = QPixmap(W, H)
        pm.fill(QColor("#F2F1EC"))            # 标定板白底
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 标定板边缘（浅灰描边，模拟板材边界）
        p.setPen(QPen(QColor("#C9C8C2"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, W - 1, H - 1)
        # 5×5 黑圆散点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#141414"))
        for r in range(5):
            for c in range(5):
                x, y = grid[r][c]
                p.drawEllipse(int(x) - 2, int(y) - 2, 4, 4)
        p.end()
        return pm, grid

    # ------------------------------------------------------------------
    # 第1~4步 业务逻辑
    # ------------------------------------------------------------------
    def _load_demo_factory(self):
        """加载演示示例：用定时器驱动，让九宫格依次出现不同位置的标定板图像。"""
        if getattr(self, "_demo_timer", None) is not None and self._demo_timer.isActive():
            # 已在加载中，避免重复触发
            self._demo_timer.stop()
        self._factory_status.setText("正在加载演示示例：9 张标定板图像将依次出现…")
        self._demo_idx = 0
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(220)
        self._demo_timer.timeout.connect(self._demo_tick)
        self._demo_timer.start()

    def _demo_tick(self):
        """定时器回调：每拍填入一格（对应位置的标定板图像），填满后收尾。"""
        if self._demo_idx >= 9:
            self._demo_timer.stop()
            self._refresh_capture_status(
                "演示示例已加载：9 张不同位置的标定板图像就位，可进行第2步提取特征及计算内参。")
            return
        self._capture(self._demo_idx)
        self._demo_idx += 1

    def _capture(self, idx: int):
        """第1步：抓取当前相机画布画面到指定宫格。"""
        dv = self._debug_view
        pm = None
        cams = getattr(dv, "_cams", None) if dv is not None else None
        if cams:
            try:
                pm = cams[0].current_frame()
            except Exception:
                pm = None
        cell = self._factory_cells[idx]
        if pm is None or (hasattr(pm, "isNull") and pm.isNull()):
            # 无实时画面：回退到标定板占位样张（白底 + 5×5 黑圆散点，位置对应宫格）
            pm, grid = self._factory_sample(idx)
            cell["grid"] = grid
        else:
            cell["grid"] = None
        cell["captured"] = pm
        self._render_cell(idx)
        self._refresh_capture_status()

    def _on_cell_action(self, idx: int):
        """第1步：根据当前获取方式（抓取/导入）路由到对应动作。"""
        mode = getattr(self, "_src_mode", None)
        if mode is not None and mode.currentData() == "import":
            self._import_image(idx)
        else:
            self._capture(idx)

    def _import_image(self, idx: int):
        """第1步（导入模式）：从本地选择一张标定板图片填入指定宫格。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入标定板图像", "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.gif)")
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            QMessageBox.warning(self, "导入失败", f"无法加载图像：\n{path}")
            return
        cell = self._factory_cells[idx]
        cell["captured"] = pm
        cell["grid"] = None
        self._render_cell(idx)
        self._refresh_capture_status()

    def _on_src_mode_changed(self, _idx: int):
        """第1步获取方式切换：更新宫格按钮文字、组标题与说明。"""
        is_import = self._src_mode.currentData() == "import"
        for c in self._factory_cells:
            c["btn"].setText("导入图像" if is_import else "获取图像")
        self._factory_g1.setTitle(
            "第1步：导入 9 张标定板图像" if is_import else "第1步：依次抓取 9 张标定板图像")
        self._factory_sub.setText(
            "每宫格点击「导入图像」从本地选择一张标定板照片；共需导入 9 张。"
            if is_import else
            "每宫格说明标定板放置位置；点击「获取当前图像」抓取当前相机画布画面。")

    def _extract_and_compute(self):
        """第2步（合并）：先提取 5×5 黑圆散点特征，随后计算相机内参。"""
        self._extract_features()
        self._compute_intrinsics()

    def _extract_features(self):
        """第2步：在九宫格图像上提取 5×5 黑圆散点特征并绘制特征曲线。"""
        for idx in range(9):
            cell = self._factory_cells[idx]
            if cell["captured"] is None or \
                    (hasattr(cell["captured"], "isNull") and cell["captured"].isNull()):
                pm, grid = self._factory_sample(idx)
                cell["captured"] = pm
                cell["grid"] = grid
            if cell["grid"] is None:
                # 真实相机帧：模拟特征检测结果（同一点阵布局）
                cell["grid"] = self._dot_grid(idx, 7000 + idx)
            cell["has_features"] = True
            # 提取是否成功：只有存在有效标定板图像且能定位点阵时记为成功
            cap = cell["captured"]
            cap_ok = cap is not None and not (
                hasattr(cap, "isNull") and cap.isNull())
            cell["feature_ok"] = bool(cap_ok and cell["grid"] is not None)
            self._render_cell(idx)
        self._factory_status.setText(
            "特征提取完成：9 张标定图像已提取 5×5 黑圆散点特征曲线，正在计算相机内参…")

    def _compute_intrinsics(self):
        """第2步：计算相机内参参数。"""
        if any(not c["has_features"] for c in self._factory_cells):
            self._extract_features()
        base_w, base_h = 1920, 1080
        rnd = random.Random(
            int(datetime.datetime.now().timestamp()) + id(self) % 100000)
        fx = round(rnd.uniform(1400.0, 1700.0), 1)
        fy = round(fx + rnd.uniform(-10.0, 10.0), 1)
        cx = round(base_w / 2.0 + rnd.uniform(-15.0, 15.0), 1)
        cy = round(base_h / 2.0 + rnd.uniform(-10.0, 10.0), 1)
        gamma = round(rnd.uniform(-0.02, 0.02), 4)
        k1 = round(rnd.uniform(-0.18, 0.18), 4)
        k2 = round(rnd.uniform(-0.06, 0.06), 4)
        p1 = round(rnd.uniform(-0.01, 0.01), 4)
        p2 = round(rnd.uniform(-0.01, 0.01), 4)
        # 随机示例重投影误差分布：
        # 80% 落在 <0.5（推荐使用）、15% 落在 0.5~1.0（可接受）、5% 落在 1.0 以上（误差偏大需重标定）
        rr = rnd.random()
        if rr < 0.80:
            rms = round(rnd.uniform(0.08, 0.49), 3)
        elif rr < 0.95:
            rms = round(rnd.uniform(0.50, 0.99), 3)
        else:
            rms = round(rnd.uniform(1.01, 1.80), 3)
        pixel_pitch_mm = 0.0024   # 约 2.4μm 像元
        focal_mm = round(fx * pixel_pitch_mm, 3)
        intr = {
            "width": base_w, "height": base_h,
            "fx": fx, "fy": fy, "cx": cx, "cy": cy, "gamma": gamma,
            "k1": k1, "k2": k2, "p1": p1, "p2": p2,
            "rms_reprojection": rms, "focal_length_mm": focal_mm,
        }
        self._intrinsics = intr
        self._show_intrinsics(intr)
        self._factory_status.setText(
            f"第2步完成：内参已计算（重投影误差 RMS={rms} px）。可在第3步应用或保存。")

    def _make_rms_indicator(self):
        """构建重投影误差 RMS 结果区：左列标题+结论（相对坐标轴垂直居中），右侧坐标轴。"""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        # 左列：标题在上，结论文字在下
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(4)
        title = QLabel("重投影误差RMS结果：")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")
        self._rms_conclusion = QLabel("计算后显示结果")
        self._rms_conclusion.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold;")
        left_col.addWidget(title)
        left_col.addWidget(self._rms_conclusion)
        left_w = QWidget()
        left_w.setLayout(left_col)
        self._rms_axis = _RmsAxisWidget()
        row.addWidget(left_w, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._rms_axis, 1)
        return container

    def _update_rms_indicator(self, rms):
        """把当前 RMS 结果值更新到坐标轴对应位置，并刷新左侧结论文字。"""
        self._rms_axis.set_value(rms)
        if rms is None:
            self._rms_conclusion.setText("计算后显示结果")
            self._rms_conclusion.setStyleSheet(
                f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: bold;")
            return
        seg = 0 if rms < 0.5 else (1 if rms <= 1.0 else 2)
        self._rms_conclusion.setText(_RmsAxisWidget.SEG_MSGS[seg])
        self._rms_conclusion.setStyleSheet(
            f"color: {_RmsAxisWidget.SEG_COLORS[seg]}; "
            f"font-size: 12px; font-weight: bold;")

    @staticmethod
    def _rms_eval(rms: float):
        """按阈值返回重投影误差 RMS 的评估结论。"""
        if rms < 0.5:
            return "推荐使用"
        if rms <= 1.0:
            return "可接受，但可能影响高精度应用"
        return "标定误差较大，需重新标定"

    def _show_intrinsics(self, intr: dict):
        # 各列按实际字符宽度右对齐，保证等宽字体下行首行尾中括号完全对齐
        c1 = [f"{intr['fx']:.1f}", "0", "0"]
        c2 = ["0", f"{intr['fy']:.1f}", "0"]
        c3 = [f"{intr['cx']:.1f}", f"{intr['cy']:.1f}", "1"]
        w1 = max(len(s) for s in c1)
        w2 = max(len(s) for s in c2)
        w3 = max(len(s) for s in c3)
        rows = [
            f"[ {c1[0].rjust(w1)}  {c2[0].rjust(w2)}  {c3[0].rjust(w3)} ]",
            f"[ {c1[1].rjust(w1)}  {c2[1].rjust(w2)}  {c3[1].rjust(w3)} ]",
            f"[ {c1[2].rjust(w1)}  {c2[2].rjust(w2)}  {c3[2].rjust(w3)} ]",
        ]
        k_text = "相机内参矩阵 K：\n" + "\n".join(rows)
        self._intr_edit.setPlainText(k_text)
        detail = (
            f"焦距：fx = {intr['fx']:.1f} px，fy = {intr['fy']:.1f} px"
            f"   （≈ {intr['focal_length_mm']:.3f} mm）\n"
            f"主点坐标：(cx, cy) = ({intr['cx']:.1f}, {intr['cy']:.1f}) px\n"
            f"倾斜系数 γ = {intr['gamma']:.4f}\n"
            f"畸变系数：k1 = {intr['k1']:.4f}，k2 = {intr['k2']:.4f}，"
            f"p1 = {intr['p1']:.4f}，p2 = {intr['p2']:.4f}\n"
            f"重投影误差 RMS = {intr['rms_reprojection']:.3f} px\n"
            f"评估：{self._rms_eval(intr['rms_reprojection'])}"
        )
        self._intr_detail.setPlainText(detail)
        self._update_rms_indicator(intr["rms_reprojection"])
        self._intr_group.setTitle("第2步：相机内参参数（已计算）")

    def _apply_to_camera(self):
        """第3步：将标定的内参应用于当前相机。"""
        if self._intrinsics is None:
            QMessageBox.warning(self, "提示", "请先完成第2步：提取标定板图像特征及计算相机内参。")
            return
        dv = self._debug_view
        cam_name = "当前相机"
        if dv is not None:
            cams = getattr(dv, "_cams", None)
            if cams:
                cam_name = getattr(cams[0], "name", "当前相机") or "当前相机"
            try:
                dv._factory_calib = self._intrinsics
            except Exception:
                pass
        intr = self._intrinsics
        QMessageBox.information(
            self, "应用于当前相机",
            f"已将出厂标定内参应用于 {cam_name}：\n\n"
            f"焦距 fx={intr['fx']:.1f} px，fy={intr['fy']:.1f} px\n"
            f"主点 ({intr['cx']:.1f}, {intr['cy']:.1f}) px\n"
            f"畸变 k1={intr['k1']:.4f}, k2={intr['k2']:.4f}\n"
            f"重投影误差 RMS={intr['rms_reprojection']:.3f} px")
        self._factory_status.setText("第3步完成：标定内参已应用于当前相机。")

    def _save_to_file(self):
        """第3步：将标定内参保存为本地 JSON 文件。"""
        if self._intrinsics is None:
            QMessageBox.warning(self, "提示", "请先完成第2步：提取标定板图像特征及计算相机内参。")
            return
        intr = self._intrinsics
        cam_name = "camera"
        dv = self._debug_view
        if dv is not None:
            cams = getattr(dv, "_cams", None)
            if cams:
                cam_name = getattr(cams[0], "name", "camera") or "camera"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"{cam_name}_calibration_{ts}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存标定参数", default, "JSON 文件 (*.json)")
        if not path:
            return
        data = {
            "camera": cam_name,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "sensor": {"width": intr["width"], "height": intr["height"]},
            "intrinsics": {
                "fx": intr["fx"], "fy": intr["fy"],
                "cx": intr["cx"], "cy": intr["cy"],
                "skew": intr["gamma"],
                "distortion": {"k1": intr["k1"], "k2": intr["k2"],
                               "p1": intr["p1"], "p2": intr["p2"]},
                "focal_length_mm": intr["focal_length_mm"],
                "rms_reprojection": intr["rms_reprojection"],
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法写入文件：\n{path}\n\n{e}")
            return
        QMessageBox.information(self, "保存成功", f"标定参数已保存至：\n{path}")
        self._factory_status.setText(
            f"第3步完成：标定参数已保存至 {os.path.basename(path)}")

    def _reset_factory(self):
        """重置出厂标定子页面到初始状态。"""
        for idx in range(9):
            cell = self._factory_cells[idx]
            cell["captured"] = None
            cell["has_features"] = False
            cell["feature_ok"] = None
            cell["grid"] = None
            self._render_cell(idx)
        self._intrinsics = None
        self._intr_edit.clear()
        self._intr_detail.clear()
        self._update_rms_indicator(None)
        self._intr_group.setTitle("第2步：相机内参参数（计算后显示）")
        self._refresh_capture_status("已重置，请重新开始第1步抓取标定板图像。")

    # ------------------------------------------------------------------
    # 渲染辅助
    # ------------------------------------------------------------------
    def _render_cell(self, idx: int, w: int = None, h: int = None):
        w = _FC_IMG_W if w is None else w
        h = _FC_IMG_H if h is None else h
        pm = self._compose_cell_pixmap(idx).scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation)
        self._factory_cells[idx]["img"].setPixmap(pm)
        if self._selected_factory == idx:
            self._update_zoom()

    def _compose_cell_pixmap(self, idx: int) -> QPixmap:
        W, H = 224, 148
        pm = QPixmap(W, H)
        pm.fill(QColor("#15171B"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = self._factory_cells[idx]
        cap = cell["captured"]
        if cap is not None and (not hasattr(cap, "isNull") or not cap.isNull()):
            scaled = cap.scaled(
                W, H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            sx = (scaled.width() - W) // 2
            sy = (scaled.height() - H) // 2
            p.drawPixmap(0, 0, scaled, sx, sy, W, H)
        if cell["has_features"] and cell["grid"] is not None:
            grid = cell["grid"]
            # 特征曲线：相邻检测点连线（绿色网格）
            p.setPen(QPen(QColor("#39D98A"), 1))
            for r in range(5):
                for c in range(5):
                    x0, y0 = grid[r][c]
                    if c < 4:
                        x1, y1 = grid[r][c + 1]
                        p.drawLine(int(x0), int(y0), int(x1), int(y1))
                    if r < 4:
                        x1, y1 = grid[r + 1][c]
                        p.drawLine(int(x0), int(y0), int(x1), int(y1))
            # 5×5 黑圆散点（标定板特征点）
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#000000"))
            for r in range(5):
                for c in range(5):
                    x, y = grid[r][c]
                    p.drawEllipse(int(x) - 2, int(y) - 2, 4, 4)
            # 绿色检测角点标记
            p.setPen(QPen(QColor("#39D98A"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for r in range(5):
                for c in range(5):
                    x, y = grid[r][c]
                    p.drawRect(int(x) - 3, int(y) - 3, 6, 6)
        elif cap is None:
            p.setPen(QColor(COLORS["border"]))
            p.setFont(QFont("Microsoft YaHei", 11))
            p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "未抓取\n标定板")
        # 特征提取结果角标（右上角）：成功绿 / 失败红
        if cell["has_features"]:
            self._draw_feature_badge(p, W, H, cell["feature_ok"])
        p.end()
        return pm

    @staticmethod
    def _draw_feature_badge(p, w: int, h: int, ok):
        """在画布右上角绘制特征提取结果角标（成功=绿，失败=红）。"""
        if ok is None:
            return
        text = "提取成功" if ok else "提取失败"
        bg = QColor("#1E8E5A") if ok else QColor("#E02020")
        bw, bh, bx, by = 66, 18, w - 66 - 5, 5
        # 半透明深色衬底，保证在亮/暗标定板上均清晰
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(bx - 2, by - 2, bw + 4, bh + 4, 5, 5)
        # 状态色块
        p.setBrush(bg)
        p.drawRoundedRect(bx, by, bw, bh, 4, 4)
        # 文字
        f = QFont("Microsoft YaHei", 9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, text)

    def _refresh_capture_status(self, extra: str = None):
        n = sum(1 for c in self._factory_cells if c["captured"] is not None)
        if extra:
            msg = extra
        else:
            msg = f"已抓取 {n}/9 张标定板图像。"
            if n == 9:
                msg += " 第1步完成，可进行第2步特征提取。"
        self._factory_status.setText(msg)

    def _big_btn(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(
            self._btn_blue_style() +
            " text-align: left; padding: 8px 14px; font-size: 13px; font-weight: bold;")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _group_style(self) -> str:
        return (
            f"QGroupBox {{ background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; "
            f"margin-top: 14px; padding: 14px 12px 12px 12px; "
            f"font-size: 13px; font-weight: bold; color: {COLORS['text_primary']}; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; "
            f"color: {COLORS['accent_blue']}; }}")

    def _btn_ghost_style(self) -> str:
        return (
            f"QPushButton {{ background-color: {COLORS['bg_card']}; "
            f"color: {COLORS['text_primary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ border: 1px solid {COLORS['accent_blue']}; }}")
