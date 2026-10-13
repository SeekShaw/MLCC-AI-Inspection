from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QApplication, QScrollArea, QFileDialog, QMessageBox,
    QComboBox,
)
from PyQt6.QtCore import Qt, QSize, QEvent, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPixmap, QImage, QIcon
import uuid
import random

from styles import COLORS, register_restyle


class NavButton(QPushButton):
    """左侧导航按钮"""
    def __init__(self, icon_text, label, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS["text_secondary"]};
                border-radius: 8px;
                font-size: 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS["bg_panel"]};
                color: {COLORS["text_primary"]};
            }}
            QPushButton:checked {{
                background-color: {COLORS["accent_orange"]};
                color: white;
            }}
        """)
        self.setText(icon_text)
        self.setToolTip(label)


class SectionTitle(QLabel):
    """面板标题"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            color: {COLORS["text_primary"]};
            font-size: 14px;
            font-weight: bold;
            padding: 4px 0;
        """)


class Card(QFrame):
    """通用卡片容器"""
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self._title = title
        self._apply_style()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(8)
        if title:
            self.layout.addWidget(SectionTitle(title))
        register_restyle(self._restyle)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["bg_card"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
            }}
        """)

    def _restyle(self):
        self._apply_style()


class StatusBadge(QFrame):
    """设备状态条：标签 + 状态灯 + 说明（紧凑不拥挤）"""
    def __init__(self, label, status=True, desc="", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["bg_panel"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px;")
        layout.addWidget(lbl)

        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {'#0D822B' if status else '#C81435'}; font-size: 13px;")
        layout.addWidget(self.dot)

        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
            layout.addWidget(desc_lbl)

        layout.addStretch()


class StatusLight(QFrame):
    """门/多灯状态指示器"""
    def __init__(self, count=4, active=4, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for i in range(count):
            dot = QLabel("●")
            color = COLORS["accent_green"] if i < active else COLORS["accent_red"]
            dot.setStyleSheet(f"color: {color}; font-size: 12px;")
            layout.addWidget(dot)
        layout.addStretch()


class KpiGrid(QFrame):
    """KPI 表格（默认 4 列，可配置 cols）"""
    def __init__(self, items, cols=4, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_panel"]}; border-radius: 6px; }}
        """)
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        for i, (label, value, color) in enumerate(items):
            row, col = divmod(i, cols)
            cell = QFrame()
            cell.setStyleSheet(f"""
                QFrame {{ background-color: {COLORS["bg_card"]}; border-radius: 4px; }}
            """)
            v = QVBoxLayout(cell)
            v.setContentsMargins(4, 4, 4, 4)
            v.setSpacing(2)
            val = QLabel(value)
            val.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab = QLabel(label)
            lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px;")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(val)
            v.addWidget(lab)
            layout.addWidget(cell, row, col)


class DonutChart(QFrame):
    """环形图：良品 OK / NG1 / NG2 / RST"""
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data  # list of (label, value, color)
        # 中心良率文字：为 None 时按首段（OK）占比计算；否则显示外部传入的
        # 时段真实良品率，确保饼图中心数字随示例数据正确更新。
        self.center_value = None
        self.setMinimumSize(140, 140)
        self.setMaximumSize(200, 200)
        # 自身底色与挖空内圆保持一致，避免依赖父级背景色
        self._apply_style()
        register_restyle(self._restyle)

    def _apply_style(self):
        self.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; border-radius: 6px; }}")

    def _restyle(self):
        self._apply_style()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(v for _, v, _ in self.data)
        cx, cy = self.width() // 2, self.height() // 2
        R_out = min(cx, cy) - 3
        thickness = 30
        R_in = R_out - thickness
        if total <= 0:
            # 未启动 / 全空：绘制整圈 100% 绿色环（无任何不良），中心显示良品率
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#0D822B"))
            painter.drawPie(cx - R_out, cy - R_out, 2 * R_out, 2 * R_out, 0, 360 * 16)
            # 挖空中心
            painter.setBrush(QColor(COLORS["bg_card"]))
            painter.drawEllipse(cx - R_in, cy - R_in, 2 * R_in, 2 * R_in)
            # 中心文字：未启动显示 100.00%（全绿），清零等异常态显示传入值
            painter.setPen(QColor(COLORS["text_primary"]))
            font = QFont("Inter", 16, QFont.Weight.Bold)
            painter.setFont(font)
            text = self.center_value if self.center_value is not None else "100.00%"
            rect = painter.boundingRect(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            font2 = QFont("Microsoft YaHei", 10)
            painter.setFont(font2)
            painter.setPen(QColor(COLORS["text_secondary"]))
            sub_rect = rect.adjusted(0, 22, 0, 22)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, "良品率")
            return

        # 用 drawPie 逐段填充实心扇形（外径），再在中心挖一个同底色内圆形成环形。
        # 相比 QPainterPath 填充式扇区，drawPie 在扇区衔接处是干净的径向分割线，不会产生毛刺/尖角。
        start_qt = 90 * 16  # Qt 角度单位：1/16 度；0°=+x 轴，逆时针为正
        for label, value, color in self.data:
            if value <= 0:
                continue
            span = int((value / total) * 360 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPie(cx - R_out, cy - R_out, 2 * R_out, 2 * R_out,
                           start_qt, -span)  # 负号 = 顺时针，与下一帧衔接
            start_qt -= span

        # 挖空中心，形成环形（底色与控件一致）
        painter.setBrush(QColor(COLORS["bg_card"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - R_in, cy - R_in, 2 * R_in, 2 * R_in)

        # 中心文字（良品率）
        painter.setPen(QColor(COLORS["text_primary"]))
        font = QFont("Inter", 16, QFont.Weight.Bold)
        painter.setFont(font)
        if self.center_value is not None:
            text = self.center_value
        else:
            ok_pct = self.data[0][1] / total * 100
            text = f"{ok_pct:.1f}%"
        rect = painter.boundingRect(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        font2 = QFont("Microsoft YaHei", 10)
        painter.setFont(font2)
        painter.setPen(QColor(COLORS["text_secondary"]))
        sub_rect = rect.adjusted(0, 22, 0, 22)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, "良品率")


class LogView(QFrame):
    """运行日志面板：滚动显示最新报警 / 状态记录。

    可见区一次约显示 10 行；新记录追加到底部并自动滚动到最新，最早的记录被顶出
    可见区（被覆盖）；记录超过上限后丢弃最旧的，需要时可用右侧滚动条上翻查看历史。
    """
    _MAX_ROWS = 200  # 历史记录上限，超出后丢弃最旧一条，避免无限增长

    def __init__(self, logs, parent=None, show_header=True, detail_callback=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_card"]}; border-radius: 6px; }}
        """)
        self._logs = logs
        self._frozen = False  # 冻结标志：冻结时不再追加新记录，显示停留在当前状态
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 功能按钮：冻结（暂停刷新显示）/ 清除（清空全部日志）/ 导出（保存为文本文件），均有效。
        # 始终创建并作为属性暴露：show_header=True 时放入自身内部标题栏；
        # show_header=False（如生产运行界面「运行日志」面板）时由浮动面板标题栏接管，避免与面板标题重复。
        self._freeze_btn = QPushButton("冻结")
        self._freeze_btn.setFixedHeight(22)
        self._freeze_btn.setStyleSheet(self._log_btn_style())
        self._freeze_btn.clicked.connect(self._toggle_freeze)
        self._clear_btn = QPushButton("清除")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.setStyleSheet(self._log_btn_style())
        self._clear_btn.clicked.connect(self.clear)
        self._export_btn = QPushButton("导出")
        self._export_btn.setFixedHeight(22)
        self._export_btn.setStyleSheet(self._log_btn_style())
        self._export_btn.clicked.connect(self.export)
        if show_header:
            header = QHBoxLayout()
            header.setContentsMargins(10, 10, 10, 6)
            header.addWidget(SectionTitle("运行日志"))
            header.addStretch()
            if callable(detail_callback):
                # 「日志详情」：打开与左侧导航「日志管理」窗口内容一致的日志窗口
                # （调用方可传入触发回调，例如调试界面此处打开 LogManagerDialog）。
                self._detail_btn = QPushButton("日志详情")
                self._detail_btn.setFixedHeight(22)
                self._detail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                self._detail_btn.setStyleSheet(self._log_btn_style())
                self._detail_btn.setToolTip("查看完整运行日志（与「日志管理」窗口一致）")
                self._detail_btn.clicked.connect(detail_callback)
                header.addWidget(self._detail_btn)
            header.addWidget(self._freeze_btn)
            header.addWidget(self._clear_btn)
            header.addWidget(self._export_btn)
            layout.addLayout(header)

        # 滚动区：内容超出可见高度时自动出现上下滚动条
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._list = QWidget()
        self._list_lay = QVBoxLayout(self._list)
        self._list_lay.setContentsMargins(10, 4, 10, 10)
        self._list_lay.setSpacing(2)
        self._scroll.setWidget(self._list)
        layout.addWidget(self._scroll, 1)

        self._rows = []
        self._mirrors = []      # 其它 LogView 把本视图作为镜像源，共享同一份运行日志
        self._entries = []      # 运行日志完整记录（含初始样例），供镜像注册时回放
        for ts, msg, color in logs:
            self._append_row(ts, msg, color)
            self._entries.append((ts, msg, color))
        register_restyle(self._restyle)

    def _append_row(self, time, msg, color):
        """追加一行日志；超过上限时丢弃最旧的一条（被滚动区顶出、覆盖）。"""
        row = QLabel(f"[{time}] {msg}")
        row.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._list_lay.addWidget(row)
        self._rows.append((row, color))
        while len(self._rows) > self._MAX_ROWS:
            old, _ = self._rows.pop(0)
            self._list_lay.removeWidget(old)
            old.deleteLater()
        self._snap_rows()

    def resizeEvent(self, event):
        """面板尺寸变化时重新对齐行边界，避免最底一行被裁成半行。"""
        super().resizeEvent(event)
        self._snap_rows()

    def _snap_rows(self):
        """动态调整列表底部留白，使可见区恰好容纳整数行——消除「半行」截断。

        设单行高 row_h、行间距 s，行槽 slot = row_h + s；令底部留白
        bottom = (视口高 - row_h) mod slot，则滚动到底部时每行都与视口边界对齐，
        不会再出现某一行只显示一半（与历史条目数量无关）。
        """
        if not self._rows:
            return
        try:
            row_h = self._rows[0][0].sizeHint().height()
        except Exception:
            return
        slot = row_h + self._list_lay.spacing()
        vp_h = self._scroll.viewport().height()
        if row_h <= 0 or slot <= 0 or vp_h <= row_h:
            return
        m = self._list_lay.contentsMargins()
        bottom = (vp_h - row_h) % slot
        if bottom != m.bottom():
            self._list_lay.setContentsMargins(m.left(), m.top(), m.right(), bottom)

    def _restyle(self):
        self.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS["bg_card"]}; border-radius: 6px; }}
        """)
        for row, color in self._rows:
            row.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._snap_rows()

    def add(self, time, msg, color):
        """向运行日志追加一条记录，并自动滚动到最新（最旧记录被顶出可见区）。

        若本视图被其它界面注册为镜像源，会同步转发给所有镜像视图（如调试界面），
        保证运行日志在任意界面都能实时刷新显示。冻结态下停止记录与转发。
        """
        if getattr(self, "_frozen", False):
            return
        self._append_row(time, msg, color)
        self._entries.append((time, msg, color))
        for m in list(self._mirrors):
            m._push(time, msg, color)
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _push(self, time, msg, color):
        """内部转发：仅追加显示，不再二次转发；镜像视图各自独立判断是否冻结。"""
        if getattr(self, "_frozen", False):
            return
        self._append_row(time, msg, color)
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def register_mirror(self, other):
        """注册一个镜像视图：本视图后续的日志会同步显示到 other，并在注册时回放已有记录。

        幂等：重复注册同一视图不会重复追加。
        """
        if other is None or other is self or not isinstance(other, LogView):
            return
        if other in self._mirrors:
            return
        self._mirrors.append(other)
        for ts, msg, color in self._entries:
            other._push(ts, msg, color)

    def _toggle_freeze(self):
        """冻结 / 解冻切换：冻结时日志停止刷新停留在当前显示；解冻后恢复实时追加。"""
        self._frozen = not self._frozen
        if self._frozen:
            self._freeze_btn.setText("解冻")
            self._freeze_btn.setStyleSheet(self._log_btn_style(active=True))
        else:
            self._freeze_btn.setText("冻结")
            self._freeze_btn.setStyleSheet(self._log_btn_style(active=False))

    @staticmethod
    def _log_btn_style(active=False):
        if active:
            # 冻结中：按钮高亮为橙色，提示当前处于冻结态
            return (
                f"QPushButton {{ background-color: {COLORS['accent_orange']}; color: white; "
                f"border: 1px solid {COLORS['accent_orange']}; border-radius: 3px; "
                f"padding: 2px 10px; font-size: 11px; }}"
                f"QPushButton:hover {{ background-color: {COLORS['accent_orange']}; color: white; }}"
            )
        return (
            f"QPushButton {{ background-color: {COLORS['bg_panel']}; color: {COLORS['text_primary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px; "
            f"padding: 2px 10px; font-size: 11px; }}"
            f"QPushButton:hover {{ background-color: {COLORS['accent_orange']}; color: white; }}"
        )

    def clear(self):
        """清除运行日志全部记录（有效）；若为镜像源则同步清空所有镜像视图。"""
        for row, _ in self._rows:
            self._list_lay.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._entries = []
        for m in list(self._mirrors):
            m.clear()

    def export(self):
        """将运行日志导出为文本文件（有效）。"""
        if not self._rows:
            QMessageBox.information(self, "导出日志", "当前没有可导出的日志记录。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出运行日志", "运行日志.txt", "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for row, _ in self._rows:
                    f.write(row.text() + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")


def make_sample_frames(w, h, count=12, seed=0):
    """生成一组样张帧（每帧一张完整产品快照），供相机画布逐帧快速刷新。

    w / h 为显示区尺寸（每帧即一屏大小）。每帧画一个居中陶瓷片（MLCC）外形，
    位置/尺寸带随机扰动并偶发红圈 NG 标记，整组帧连续切换时像产线上快速经过的
    不同产品——即「一帧一帧快速在画布里更新显示」。
    """
    rnd = random.Random(seed)
    frames = []
    margin = max(8, w // 8)
    for _ in range(count):
        pm = QPixmap(w, h)
        pm.fill(QColor("#15171B"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 背景参考网格（模拟相机视野）
        p.setPen(QColor("#1E2127"))
        for gx in range(0, w, 24):
            p.drawLine(gx, 0, gx, h)
        for gy in range(0, h, 24):
            p.drawLine(0, gy, w, gy)
        # 居中产品（位置抖动，模拟不同产品经过）
        cw = int((w - 2 * margin) * rnd.uniform(0.45, 0.72))
        ch = int(h * rnd.uniform(0.42, 0.60))
        cx = (w - cw) // 2 + rnd.randint(-margin, margin)
        cy = (h - ch) // 2 + rnd.randint(-margin // 2, margin // 2)
        chip = QColor(rnd.randint(196, 224), rnd.randint(200, 226), rnd.randint(205, 230))
        p.setPen(QColor("#8A8F99"))
        p.setBrush(chip)
        p.drawRoundedRect(cx, cy, cw, ch, 6, 6)
        # 两端电极（深色）
        p.setBrush(QColor("#3A3E47"))
        p.setPen(Qt.PenStyle.NoPen)
        ew = max(4, cw // 8)
        p.drawRoundedRect(cx, cy, ew, ch, 3, 3)
        p.drawRoundedRect(cx + cw - ew, cy, ew, ch, 3, 3)
        # 偶发缺陷（红圈 NG 标记）
        if rnd.random() < 0.30:
            p.setPen(QPen(QColor("#C81435"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            dx = cx + rnd.randint(2, max(3, cw - 16))
            dy = cy + rnd.randint(2, max(3, ch - 16))
            p.drawEllipse(dx, dy, 12, 12)
        p.end()
        frames.append(pm)
    return frames


def _extract_channel(pm, mode):
    """把样张帧按通道模式转换：'src' 原样；'gray' 灰度；'r'/'g'/'b' 单通道（红/绿/蓝单色）。

    单通道模式用对应通道的亮度填充单色，使 R/G/B 三路画面明显区分，模拟真实通道分离效果。

    实现采用 QPainter 的 Multiply 合成（C++ 加速，约 0.6ms/帧），远快于逐像素 Python 循环
    （约 51ms/帧）。原先的逐像素循环在切换界面后对每帧做通道转换会堆积成明显的卡顿，
    改用合成后即便逐帧实时转换也几乎无感知，彻底消除切换开始的停顿感。
    """
    if mode in (None, "src"):
        return pm
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height()
    if mode == "gray":
        # 灰度：直接用 Qt 内置格式转换（C++ 加速），再转回 QPixmap 显示
        return QPixmap.fromImage(img.convertToFormat(QImage.Format.Format_Grayscale8))
    # 单通道：用 Multiply 合成把非目标通道清零（白底 × 原图 × 单色遮罩 = 仅保留该通道）
    color = {
        "r": QColor(255, 0, 0),
        "g": QColor(0, 255, 0),
        "b": QColor(0, 0, 255),
    }.get(mode, QColor(255, 255, 255))
    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(0xFFFFFFFF)  # 不透明白底，Multiply 基线为 1
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.drawImage(0, 0, img)              # 白底 × 原图 = 原图
    p.fillRect(0, 0, w, h, color)       # 原图 × 单色 = 仅保留该通道
    p.end()
    return QPixmap.fromImage(out)


class CameraScreen(QWidget):
    """相机画布显示区：未播放时显示提示；播放时逐帧快速切换样张帧。"""

    # 计算元素精确查找各项在画布上的示例叠加形状（归一化坐标 0..1，按名称一一对应）。
    # 每个 item 映射为一组基本图元："line"=直线（黄色实线），"rect"=轮廓（绿色虚线框）。
    # 「计算元素精确查找」列表行的眼睛按钮逐项控制这里的名称显隐。
    CANVAS_ITEM_SHAPES = {
        "产品外围左边直线查找":   [("line", (0.27, 0.16, 0.27, 0.84))],
        "产品外围右边直线查找":   [("line", (0.73, 0.16, 0.73, 0.84))],
        "产品外围上边直线查找":   [("line", (0.16, 0.27, 0.84, 0.27))],
        "产品外围下边直线查找":   [("line", (0.16, 0.73, 0.84, 0.73))],
        "产品外围左边轮廓查找":   [("rect", (0.10, 0.12, 0.34, 0.88))],
        "产品外围右边轮廓查找":   [("rect", (0.66, 0.12, 0.90, 0.88))],
        "产品外围上边轮廓查找":   [("rect", (0.10, 0.12, 0.90, 0.36))],
        "产品外围下边轮廓查找":   [("rect", (0.10, 0.64, 0.90, 0.88))],
        "左端头内侧直线查找":     [("line", (0.38, 0.30, 0.38, 0.70))],
        "右端头内侧直线查找":     [("line", (0.62, 0.30, 0.62, 0.70))],
        "左端头内侧轮廓查找":     [("rect", (0.20, 0.28, 0.44, 0.72))],
        "右端头内侧轮廓查找":     [("rect", (0.56, 0.28, 0.80, 0.72))],
        "左端头外围轮廓查找":     [("rect", (0.04, 0.24, 0.18, 0.76))],
        "右端头外围轮廓查找":     [("rect", (0.82, 0.24, 0.96, 0.76))],
        "字符连通区域查找":       [("rect", (0.40, 0.42, 0.60, 0.58))],
        "前后端面轮廓查找":       [("rect", (0.02, 0.30, 0.10, 0.70)),
                                   ("rect", (0.90, 0.30, 0.98, 0.70))],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hint = "实时画面模拟"
        self._frames = []
        self._idx = 0
        self._playing = False
        self._channel = "src"        # 显示通道：src / gray / r / g / b
        self._show_elements = False  # 是否叠加显示计算元素（总开关，画布右上角眼睛）
        self._item_visible = {}      # 计算元素逐项显隐：{名称: bool}，缺省为显示
        self._chan_cache = {}        # (帧id, 通道) -> 转换后 QPixmap，避免每帧重算
        self.setStyleSheet("background-color: #15171B; border-radius: 4px;")

    def set_frames(self, frames):
        self._frames = frames or []
        self._idx = 0
        self._chan_cache.clear()
        self.update()

    def set_frame_index(self, i):
        if self._frames:
            self._idx = i % len(self._frames)
            self.update()

    def advance_frame(self, step=1):
        if self._frames:
            self._idx = (self._idx + step) % len(self._frames)
            self.update()

    def set_playing(self, playing):
        self._playing = playing
        self.update()

    def set_channel(self, mode):
        """设置显示通道：src(源图)/gray(灰度)/r/g/b（单通道）。"""
        if mode not in ("src", "gray", "r", "g", "b"):
            mode = "src"
        if mode == self._channel:
            return
        self._channel = mode
        self.update()

    def set_elements_visible(self, visible):
        """显示 / 隐藏画布上的计算元素叠加（如外围轮廓、左/右直线）。"""
        visible = bool(visible)
        if visible == self._show_elements:
            return
        self._show_elements = visible
        self.update()

    def set_item_visible(self, name, visible):
        """设置单个计算元素（如「产品外围左边直线查找」）在画布上的显隐。"""
        self._item_visible[name] = bool(visible)
        self.update()

    def item_visible(self, name):
        """查询单个计算元素当前是否显示（未设置过默认显示）。"""
        return self._item_visible.get(name, True)

    def frame_index(self):
        """返回当前显示的帧序号（供外部同步多路相机画面使用）。"""
        return self._idx

    def current_frame(self):
        """返回当前显示的帧（QPixmap），无帧时返回 None。"""
        if self._frames:
            return self._frames[self._idx]
        return None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, QColor("#15171B"))
        if self._frames:
            # 有样张帧时始终绘制当前帧：播放中逐帧刷新，停止后冻结在最后一张
            pm = self._frames[self._idx]
            if self._channel != "src":
                key = (id(pm), self._channel)
                cached = self._chan_cache.get(key)
                if cached is None:
                    cached = _extract_channel(pm, self._channel)
                    if len(self._chan_cache) < 256:
                        self._chan_cache[key] = cached
                pm = cached
            p.drawPixmap(rect, pm)
            # 计算元素叠加（外围轮廓 + 左/右直线）
            if self._show_elements:
                self._draw_elements(p, rect)
        else:
            p.setPen(QColor(COLORS["border"]))
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._hint)

    def _draw_elements(self, p, rect):
        """在画布上叠加计算元素：按「计算元素精确查找」逐项显隐状态绘制。

        直线查找项画黄色实线，轮廓查找项画绿色虚线框；被眼睛按钮隐藏的项不绘制。
        """
        W, H = rect.width(), rect.height()
        for name, shapes in self.CANVAS_ITEM_SHAPES.items():
            if not self.item_visible(name):
                continue
            for kind, (u0, v0, u1, v1) in shapes:
                x0, y0, x1, y1 = u0 * W, v0 * H, u1 * W, v1 * H
                if kind == "line":
                    p.setPen(QPen(QColor("#FFC53D"), 2))
                    p.drawLine(int(x0), int(y0), int(x1), int(y1))
                else:
                    p.setPen(QPen(QColor("#39D98A"), 1, Qt.PenStyle.DashLine))
                    p.drawRect(int(min(x0, x1)), int(min(y0, y1)),
                               int(abs(x1 - x0)), int(abs(y1 - y0)))


class CameraPreview(QFrame):
    """相机预览占位卡片（固定尺寸，保持 4:3 观感）。

    w / h 为画布显示像素，由调用方按界面要求传入：
      - 生产界面每路相机：按面板高度动态计算，宽 = 高 × 1.333（4:3）
      - 调试界面主相机：  520 × 390
      - 调试界面 R/G/B：  168 × 126（三路含间隙总高 390）
    内置 CameraScreen 显示区：未播放时显示「实时画面模拟」提示；
    点击启动后由外部驱动 set_strip + set_offset 实现垂直滚动播放样张。
    """
    def __init__(self, name, w=360, h=270, parent=None, show_channel_control=True):
        super().__init__(parent)
        self.name = name
        self.setFixedSize(w, h)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color: #0D822B; font-size: 10px;")
        top.addWidget(self._dot)
        self._name = QLabel(name)
        top.addWidget(self._name)
        top.addStretch()
        self._res_label = QLabel(f"{w}×{h}")
        top.addWidget(self._res_label)
        layout.addLayout(top)
        self._title_row = top   # 标题行（点 + 名称 + 扩展区），供 add_title_button 在名称右侧插入按钮

        # 画布显示区：占满剩余高度，由外部驱动滚动播放
        self.screen = CameraScreen()
        # 监听画布自身尺寸变化，保证覆盖层（下拉/眼睛）始终贴合画布左上/中/右上
        self.screen.installEventFilter(self)
        layout.addWidget(self.screen, 1)
        self._elements_on = False
        if show_channel_control:
            self._build_channel_control()
            self._res_label.hide()   # 下拉占据卡片右上角，隐藏分辨率标签避免重叠
            self._position_control()
        self._apply_style()
        register_restyle(self._restyle)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["bg_panel"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 6px;
            }}
        """)
        self._name.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 12px; font-weight: bold;")
        self._res_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10px;")

    def _restyle(self):
        self._apply_style()

    def add_title_button(self, widget):
        """在卡片名称右侧（扩展区前）插入一个标题栏按钮，例如「拍照设置」。

        插入位置固定在点 ● 与名称之后、弹性占位之前，使按钮紧贴名称右侧显示。
        """
        self._title_row.insertWidget(2, widget)

    def set_canvas_size(self, w, h):
        """动态更新画布显示尺寸（保持 4:3 时由相机网格统一调用）。"""
        self.setFixedSize(w, h)
        self._res_label.setText(f"{w}×{h}")

    def set_frames(self, frames):
        """设置样张帧序列（点击启动后逐帧快速切换显示）。"""
        self.screen.set_frames(frames)

    def set_frame_index(self, i):
        """直接定位到指定帧。"""
        self.screen.set_frame_index(i)

    def advance_frame(self, step=1):
        """推进若干帧（定时器驱动逐帧刷新）。"""
        self.screen.advance_frame(step)

    def set_playing(self, playing):
        """切换播放 / 暂停状态。"""
        self.screen.set_playing(playing)

    def current_frame_index(self):
        """返回当前显示的帧序号（供 R/G/B 通道与主画布同步）。"""
        return self.screen.frame_index()

    def current_frame(self):
        """冻结抓取当前显示的相机帧（QPixmap），供教导等功能复用。"""
        return self.screen.current_frame()

    # ---- 画布右上角通道控制（下拉切换通道 + 眼睛按钮切换计算元素） ----
    CHAN_MAP = {"源图": "src", "灰度图": "gray", "R通道": "r", "G通道": "g", "B通道": "b"}

    def set_channel(self, mode):
        """直接设定显示通道（供 R/G/B 预览固定通道用，不显示下拉控件时使用）。"""
        self.screen.set_channel(mode)

    def _build_channel_control(self):
        # 覆盖层：通道下拉与显隐眼睛按钮均为相机卡片（用户所说的 400*300 / 210*158「画布」）
        # 的子控件，二者组成右上角控件组——眼睛在左、下拉在右、中间隔开距离。
        screen = self.screen

        # 通道下拉：固定在相机卡片右上角（调试 400*300 / 生产 210*158 的右上角）
        ctrl = QFrame(self)
        ctrl.setStyleSheet(
            "QFrame{background-color: rgba(20,22,26,0.72); border-radius:4px;}")
        hb = QHBoxLayout(ctrl)
        hb.setContentsMargins(1, 1, 1, 1)
        hb.setSpacing(4)

        combo = QComboBox()
        combo.addItems(["源图", "灰度图", "R通道", "G通道", "B通道"])
        # 下拉框高度与卡片「上表面」标题行等高（约 14px）：9px 文字可完整容纳于 12px 框高
        combo.setFixedHeight(12)
        # 收窄下拉框宽度：缩小字号 / 箭头 / 内边距，使框宽逼近原宽的 2/3，
        # 但仍以最长选项「灰度图」能完整显示为准（不裁切文字）。
        combo.setMinimumWidth(34)
        # 缩小下拉弹出窗体的行高，使整体弹窗高度更矮
        view = combo.view()
        view.setStyleSheet(
            "QListView{font-size:9px; background:#15171B; border:1px solid #2A2D34; outline:0;}"
            "QListView::item{height:16px; padding:0 4px;}")
        combo.setStyleSheet(
            "QComboBox{font-size:9px; color:#E6E6E6; padding:1px 2px;}"
            "QComboBox::drop-down{border:none; width:8px;}"
            "QComboBox QAbstractItemView{selection-background-color:#2A2D34;}")
        combo.setCurrentText("源图")
        combo.currentTextChanged.connect(self._on_channel_changed)
        self._chan_combo = combo
        hb.addWidget(combo)
        self._ctrl = ctrl

        # 计算元素显隐按钮：与通道下拉组成右上角控件组，置于下拉「左边」并隔开距离；
        # 按钮高度与下拉框保持一致（紧凑），与卡片上表面标题行观感统一
        eye = QPushButton(self)
        eye.setFixedSize(16, 16)
        eye.setCursor(Qt.CursorShape.PointingHandCursor)
        eye.setStyleSheet(
            "QPushButton{background-color: rgba(20,22,26,0.72); border:none; border-radius:4px;}")
        eye.setIcon(self._eye_icon(False))
        eye.setIconSize(QSize(12, 12))
        eye.setToolTip("显示 / 隐藏图像上的计算元素")
        eye.clicked.connect(self._toggle_elements)
        self._eye_btn = eye

    def _position_control(self):
        ctrl = getattr(self, "_ctrl", None)
        eye = getattr(self, "_eye_btn", None)
        if ctrl is None and eye is None:
            return
        margin = 6
        gap = 6
        card_w = self.width()
        # 通道下拉：固定在相机卡片（即 400*300 / 210*158「画布」）的右上角
        ctrl_x = card_w - margin
        if ctrl is not None:
            cw = ctrl.sizeHint().width()
            ch = ctrl.sizeHint().height()
            ctrl_x = card_w - cw - margin
            ctrl.setGeometry(ctrl_x, margin, cw, ch)
        # 显隐眼睛按钮：放在通道下拉的「左边」，中间隔开 gap 距离，二者组成右上角控件组
        if eye is not None:
            ew, eh = eye.width(), eye.height()
            eye_x = (ctrl_x - gap - ew) if ctrl is not None else (card_w - ew - margin)
            eye.setGeometry(max(margin, eye_x), margin, ew, eh)

    def _on_channel_changed(self, text):
        self.screen.set_channel(self.CHAN_MAP.get(text, "src"))

    def _toggle_elements(self):
        self._elements_on = not self._elements_on
        self.screen.set_elements_visible(self._elements_on)
        self._eye_btn.setIcon(self._eye_icon(self._elements_on))

    @staticmethod
    def _eye_icon(visible):
        pm = QPixmap(14, 14)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#E6E6E6"), 1.2)
        p.setPen(pen)
        p.drawEllipse(1, 4, 12, 5)          # 眼眶
        p.setBrush(QColor("#E6E6E6"))
        p.drawEllipse(5, 5, 4, 4)           # 瞳孔
        if not visible:
            p.setPen(QPen(QColor("#E6E6E6"), 1.2))
            p.drawLine(2, 2, 12, 12)        # 隐藏时画斜杠
        p.end()
        return QIcon(pm)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_control()

    def eventFilter(self, obj, event):
        if obj is self.screen and event.type() == QEvent.Type.Resize:
            self._position_control()
        return super().eventFilter(obj, event)


# ===================== 可拖拽 / 可缩放浮动面板 =====================

class ResizeHandle(QFrame):
    """边缘 / 四角缩放手柄（独立子控件，自身处理鼠标拖拽）"""

    def __init__(self, panel, edge, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.edge = edge  # 'l' 'r' 't' 'b' 'tl' 'tr' 'bl' 'br'
        self._start = None
        cursor_map = {
            'l': Qt.CursorShape.SizeHorCursor, 'r': Qt.CursorShape.SizeHorCursor,
            't': Qt.CursorShape.SizeVerCursor, 'b': Qt.CursorShape.SizeVerCursor,
            'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursor_map[edge])
        self.setStyleSheet("QFrame{background:transparent;}")
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = (e.globalPosition().toPoint(), self.panel.geometry())
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._start:
            gp = e.globalPosition().toPoint()
            dx = gp.x() - self._start[0].x()
            dy = gp.y() - self._start[0].y()
            g = QRect(self._start[1])
            if 'l' in self.edge:
                g.setLeft(min(g.left() + dx, g.right() - self.panel.min_w))
            if 'r' in self.edge:
                g.setRight(max(g.right() + dx, g.left() + self.panel.min_w))
            if 't' in self.edge:
                g.setTop(min(g.top() + dy, g.bottom() - self.panel.min_h))
            if 'b' in self.edge:
                g.setBottom(max(g.bottom() + dy, g.top() + self.panel.min_h))
            self.panel.setGeometry(g)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._start = None
        super().mouseReleaseEvent(e)


class PanelHeader(QFrame):
    """面板标题栏：拖拽移动整个面板"""

    def __init__(self, panel, title):
        super().__init__(panel)
        self.panel = panel
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["bg_panel"]};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(6)
        self.dot = QLabel("⠿")
        h.addWidget(self.dot)
        self.title = QLabel(title)
        h.addWidget(self.title)
        h.addStretch()
        self._hlay = h
        self._start = None
        self._apply_style()

    def add_right(self, widget):
        """在标题栏右侧（占位拉伸之后）追加控件，如面板专属操作按钮。"""
        self._hlay.addWidget(widget)

    def add_after_title(self, widget):
        """在标题文字同一行插入控件，并使其在该行居中显示（标题与右端各留一个弹性拉伸）。"""
        self._hlay.insertStretch(2)
        self._hlay.insertWidget(3, widget)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS["bg_panel"]};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        self.dot.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold;")

    def _restyle(self):
        self._apply_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = (e.globalPosition().toPoint(), self.panel.geometry())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._start:
            gp = e.globalPosition().toPoint()
            dx = gp.x() - self._start[0].x()
            dy = gp.y() - self._start[0].y()
            g = self._start[1]
            parent = self.panel.parentWidget()
            max_x = (parent.width() - self.panel.width()) if parent else 10 ** 9
            max_y = (parent.height() - self.panel.height()) if parent else 10 ** 9
            self.panel.move(max(0, min(g.x() + dx, max_x)),
                            max(0, min(g.y() + dy, max_y)))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._start = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(e)


class FloatPanel(QFrame):
    """通用浮动面板：标题栏可拖拽，八向手柄可缩放，内容放 body 内。
    body 四周内缩 MARGIN 像素，使边缘手柄所在区域不被内容遮挡，缩放可靠生效。
    show_header=False 时不显示标题栏（连同其占用区域一并去掉），body 占满整块。"""

    MARGIN = 6

    def __init__(self, title, parent=None, min_w=200, min_h=120, show_header=True):
        super().__init__(parent)
        self.min_w = min_w
        self.min_h = min_h
        self._show_header = show_header
        self._oid = "fp_" + uuid.uuid4().hex[:8]
        self.setObjectName(self._oid)
        self.setMinimumSize(min_w, min_h)
        self._apply_style()
        self.header = PanelHeader(self, title) if show_header else None
        self.body = QWidget(self)
        self._apply_body_style()
        self._handles = {}
        for edge in ['l', 'r', 't', 'b', 'tl', 'tr', 'bl', 'br']:
            h = ResizeHandle(self, edge)
            self._handles[edge] = h
        self._layout_internal()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QFrame#{self._oid} {{
                background-color: {COLORS["bg_card"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
            }}
        """)

    def _apply_body_style(self):
        self.body.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border-radius: 8px;")

    def _restyle(self):
        self._apply_style()
        self._apply_body_style()
        if self.header is not None:
            self.header._restyle()

    def _layout_internal(self):
        w, h = self.width(), self.height()
        m = self.MARGIN
        if self.header:
            self.header.setGeometry(0, 0, w, 30)
            body_top = 30
        else:
            body_top = m
        # body 内缩 MARGIN，使四周手柄所在区域不被遮挡；无标题时从顶部 MARGIN 起算
        self.body.setGeometry(m, body_top, w - 2 * m, max(0, h - body_top - m))
        if w <= 0 or h <= 0:
            return
        H = self._handles
        H['l'].setGeometry(0, body_top, m, h - body_top)
        H['r'].setGeometry(w - m, body_top, m, h - body_top)
        H['t'].setGeometry(0, 0, w, m)
        H['b'].setGeometry(0, h - m, w, m)
        H['tl'].setGeometry(0, 0, m, body_top if self.header else m)
        H['tr'].setGeometry(w - m, 0, m, body_top if self.header else m)
        H['bl'].setGeometry(0, h - m, m, m)
        H['br'].setGeometry(w - m, h - m, m, m)
        for h_ in H.values():
            h_.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_internal()

    def set_body_layout(self, layout):
        # 兼容传入 QWidget（如 QScrollArea）：自动包一层布局
        if isinstance(layout, QWidget):
            lay = QVBoxLayout(self.body)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            lay.addWidget(layout)
        else:
            self.body.setLayout(layout)

    def set_header_actions(self, widgets):
        """将一组控件（如操作按钮）放到标题栏右侧。widgets 列表按顺序从左到右排列，
        整体位于标题栏右端（替换原「可拖拽 / 缩放」字眼位置）。"""
        if self.header is not None:
            for w in widgets:
                self.header.add_right(w)


class EditableValueLabel(QLabel):
    """KPI 数值：双击弹出编辑框修改。"""

    def __init__(self, text, color, lab_text, parent=None):
        super().__init__(text, parent)
        self._lab_text = lab_text
        self.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def mouseDoubleClickEvent(self, event):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "编辑数值", f"修改「{self._lab_text}」：", text=self.text())
        if ok and text:
            self.setText(text)
        super().mouseDoubleClickEvent(event)


class EditableKpiGrid(QFrame):
    """KPI 网格：数值支持双击编辑，列数可配置（默认 4 列 -> 2 行排布）。"""

    def __init__(self, items, cols=4, parent=None):
        super().__init__(parent)
        self._cols = cols
        self._cells = []
        self._apply_style()
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)
        self._build(items)
        register_restyle(self._restyle)

    def _apply_style(self):
        self.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_panel']}; border-radius: 6px; }}")

    def _restyle(self):
        self._apply_style()
        for val, lab, color in self._cells:
            val.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 9px;")

    def _build(self, items):
        while self.layout().count():
            it = self.layout().takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._cells = []
        for i, (label, value, color) in enumerate(items):
            row, col = divmod(i, self._cols)
            cell = QFrame()
            cell.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; border-radius: 4px; }}")
            v = QVBoxLayout(cell)
            v.setContentsMargins(3, 2, 3, 2)
            v.setSpacing(1)
            val = EditableValueLabel(value, color, label)
            lab = QLabel(label)
            lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 9px;")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            v.addWidget(val)
            v.addWidget(lab)
            self.layout().addWidget(cell, row, col)
            self._cells.append((val, lab, color))

    def set_values(self, items):
        """整体刷新 KPI 数值与颜色（用于统计清零 / 恢复示例）。"""
        for (val, lab, color), (label, value, color2) in zip(self._cells, items):
            val.setText(value)
            val.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            lab.setText(label)


class ToggleSwitch(QFrame):
    """iOS 风格开关按钮，点击切换 on/off 并发出 toggled 信号。"""

    toggled = pyqtSignal(bool)

    def __init__(self, on=True, parent=None, on_color=None):
        super().__init__(parent)
        self._on = on
        self._on_color = on_color or "#0D822B"
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame { background: transparent; }")

    def set_on(self, on):
        self._on = on
        self.update()

    def is_on(self):
        """返回开关当前是否处于开启状态（供外部读取）。"""
        return self._on

    def set_on_color(self, color):
        self._on_color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.height() // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._on_color if self._on else "#5F5F5F"))
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, r, r)
        p.setBrush(QColor("#FFFFFF"))
        kx = (self.width() - self.height() - 1) if self._on else 1
        p.drawEllipse(kx, 1, self.height() - 2, self.height() - 2)

    def mousePressEvent(self, event):
        self._on = not self._on
        self.update()
        self.toggled.emit(self._on)
        super().mousePressEvent(event)


class StateToggle(QFrame):
    """带文字状态说明的开关：名称 + 开关 + 「开启/关闭」文字。"""

    def __init__(self, name="定量生产", parent=None, name_w=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        nm = QLabel(name)
        if name_w is not None:
            nm.setFixedWidth(name_w)
        nm.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.sw = ToggleSwitch(False)
        self.st = QLabel("关闭")
        self.st.setStyleSheet("color: #C81435; font-size: 12px; font-weight: bold;")
        h.addWidget(nm)
        h.addWidget(self.sw)
        h.addWidget(self.st)
        self.sw.toggled.connect(self._sync)

    def _sync(self, on):
        self.st.setText("开启" if on else "关闭")
        self.st.setStyleSheet(
            f"color: {'#0D822B' if on else '#C81435'}; font-size: 12px; font-weight: bold;")

    def is_on(self):
        """返回开关当前是否处于开启状态（供外部读取）。"""
        return self.sw._on
