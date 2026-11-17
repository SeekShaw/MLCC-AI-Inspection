"""产品尺寸参考窗口的电极结构示意图（矢量绘制，线条分明、文字清晰）。

用 QPainter 直接绘制示意图，取代位图：
- 线条使用高对比描边 + 抗锯齿，缩放不失真；
- 尺寸符号（BW / L2 / L / W / T / A / B / D）使用加粗橙色标注 + 深色描边，
  在暗色面板上清晰可读；
- 背景透明，融入窗口暗色主题。
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from styles import COLORS

_LINE = QColor("#F4F7FB")          # 主轮廓线：近白，分明
_LINE_DIM = QColor("#9FB3CF")       # 尺寸辅助线
_FILL = QColor(58, 66, 82, 210)     # 本体填充
_FILL_ELEC = QColor(126, 141, 165, 235)   # 电极填充
_FILL_TOP = QColor(44, 50, 62, 235)
_FILL_SIDE = QColor(34, 39, 49, 240)
_FILL_BODY = QColor(14, 16, 20, 245)      # 电阻黑色主体
_TEXT = QColor("#FFFFFF")           # 标题文字
_ACCENT = QColor(COLORS["accent_orange"])   # 尺寸符号强调色
_OUTLINE = QColor(10, 13, 20, 235)   # 文字描边色（保证任何底色上清晰）


class ElectrodeDiagram(QWidget):
    """电极结构示意图。kind: 'mlcc' | 'resistor' | 'inductor'"""

    def __init__(self, kind="mlcc", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # ---------- 通用绘制工具 ----------
    def _font(self, px=12, bold=True):
        f = QFont("Microsoft YaHei")
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def _arrow(self, p, q, color=_LINE_DIM, width=1.6, head=7.0):
        """带箭头的尺寸线（p→q）。"""
        pen = QPen(color)
        pen.setWidthF(width)
        self._p.setPen(pen)
        self._p.drawLine(p, q)
        for (a, b) in ((p, q), (q, p)):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            n = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            ux, uy = dx / n, dy / n
            px, py = -uy, ux
            self._p.drawLine(a, QPointF(a.x() + ux * head + px * head * 0.45,
                                        a.y() + uy * head + py * head * 0.45))
            self._p.drawLine(a, QPointF(a.x() + ux * head - px * head * 0.45,
                                        a.y() + uy * head - py * head * 0.45))

    def _dim_h(self, x1, x2, y, label, above=True, tick=6.0, px=12):
        """水平尺寸线（带端点标记）+ 居中标签。"""
        self._arrow(QPointF(x1, y), QPointF(x2, y))
        pen = QPen(_LINE_DIM)
        pen.setWidthF(1.2)
        self._p.setPen(pen)
        for x in (x1, x2):
            self._p.drawLine(QPointF(x, y - tick), QPointF(x, y + tick))
        self._label(label, (x1 + x2) / 2.0, y - 11 if above else y + 15, px=px)

    def _dim_v(self, x, y1, y2, label, right=True, tick=6.0, px=12):
        """垂直尺寸线 + 标签（标签置于线左侧或右侧）。"""
        self._arrow(QPointF(x, y1), QPointF(x, y2))
        pen = QPen(_LINE_DIM)
        pen.setWidthF(1.2)
        self._p.setPen(pen)
        for y in (y1, y2):
            self._p.drawLine(QPointF(x - tick, y), QPointF(x + tick, y))
        self._label(label, x + (16 if right else -16), (y1 + y2) / 2.0, px=px)

    def _label(self, text, x, y, color=_ACCENT, px=12, bold=True):
        """居中文字标注：加粗 + 深色描边，保证在暗色背景上清晰醒目。"""
        if not text:
            return
        f = self._font(px, bold)
        path = QPainterPath()
        path.addText(0, 0, f, text)
        if path.isEmpty():          # 运行环境无可用字体时退回普通文本
            self._p.setPen(QPen(color))
            self._p.setFont(f)
            self._p.drawText(QRectF(x - 60, y - 12, 120, 24),
                             int(Qt.AlignmentFlag.AlignCenter), text)
            return
        bb = path.boundingRect()
        path.translate(x - bb.center().x(), y - bb.center().y())
        stroke = QPen(_OUTLINE)
        stroke.setWidthF(3.0)
        stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._p.setPen(stroke)
        self._p.drawPath(path)
        self._p.setPen(QPen(color))
        self._p.fillPath(path, QBrush(color))

    def _poly(self, pts, fill=None, outline=_LINE, width=2.0):
        poly = QPolygonF([QPointF(*p) for p in pts])
        path = QPainterPath()
        path.addPolygon(poly)
        path.closeSubpath()
        if fill is not None:
            self._p.fillPath(path, QBrush(fill))
        pen = QPen(outline)
        pen.setWidthF(width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._p.setPen(pen)
        self._p.drawPath(path)

    def _line(self, p1, p2, color=_LINE, width=2.0):
        pen = QPen(color)
        pen.setWidthF(width)
        self._p.setPen(pen)
        self._p.drawLine(QPointF(*p1), QPointF(*p2))

    # ---------- 入口 ----------
    def paintEvent(self, _evt):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._p = p
        try:
            if self.kind == "mlcc":
                self._paint_mlcc()
            elif self.kind == "resistor":
                self._paint_resistor()
            else:
                self._paint_inductor()
        finally:
            p.end()

    # ---------- 立体盒（MLCC / 电感共用） ----------
    def _draw_box(self, cx, cy, bw, bh, dx, dy, el_ratio):
        """绘制立体长方体 + 两端电极带，返回关键几何点。"""
        el = bw * el_ratio
        # 顶面
        self._poly([(cx, cy), (cx + bw, cy), (cx + bw + dx, cy + dy), (cx + dx, cy + dy)],
                   fill=_FILL_TOP)
        # 右侧面
        self._poly([(cx + bw, cy), (cx + bw + dx, cy + dy),
                    (cx + bw + dx, cy + bh + dy), (cx + bw, cy + bh)], fill=_FILL_SIDE)
        # 正面
        self._poly([(cx, cy), (cx + bw, cy), (cx + bw, cy + bh), (cx, cy + bh)], fill=_FILL)
        # 正面两端电极带
        self._poly([(cx, cy), (cx + el, cy), (cx + el, cy + bh), (cx, cy + bh)],
                   fill=_FILL_ELEC)
        self._poly([(cx + bw - el, cy), (cx + bw, cy),
                    (cx + bw, cy + bh), (cx + bw - el, cy + bh)], fill=_FILL_ELEC)
        return el

    def _dim_width(self, cx, cy, bw, dx, dy, text="宽度 W"):
        """宽度 W：沿进深方向（顶面右侧棱）作平行尺寸线，标注在右上角外侧。"""
        p2 = QPointF(cx + bw, cy)                    # 前上右角
        b2 = QPointF(cx + bw + dx, cy + dy)          # 后上右角
        off = QPointF(30, -20)
        a = QPointF(p2.x() + off.x(), p2.y() + off.y())
        b = QPointF(b2.x() + off.x(), b2.y() + off.y())
        # 尺寸界线
        pen = QPen(_LINE_DIM)
        pen.setWidthF(1.2)
        self._p.setPen(pen)
        self._p.drawLine(p2, a)
        self._p.drawLine(b2, b)
        # 尺寸线（与棱平行）
        self._arrow(a, b)
        self._label(text, b.x() + 34, b.y() - 4)

    def _paint_mlcc(self):
        W = self.width()
        cy, bh = 50, 54
        bw = min(W * 0.40, 260)
        cx = max(96.0, W * 0.24)
        dx, dy = bw * 0.30, -bh * 0.40
        el = self._draw_box(cx, cy, bw, bh, dx, dy, 0.13)

        # —— 厚度 T（左侧竖直）
        self._dim_v(cx - 26, cy, cy + bh, "厚度 T", right=False)
        # —— 宽度 W（进深方向，右上外侧）
        self._dim_width(cx, cy, bw, dx, dy)
        # —— 长度 L（底部整段）
        self._dim_h(cx, cx + bw, cy + bh + 32, "长度 L")
        # —— 电极宽度 BW（底部左右两段）
        self._dim_h(cx, cx + el, cy + bh + 58, "BW")
        self._dim_h(cx + bw - el, cx + bw, cy + bh + 58, "BW")
        # —— 电极间距 L2（底部中段）
        self._dim_h(cx + el, cx + bw - el, cy + bh + 84, "电极间距 L2")

    def _paint_inductor(self):
        W = self.width()
        cy, bh = 50, 54
        bw = min(W * 0.40, 260)
        cx = max(96.0, W * 0.24)
        dx, dy = bw * 0.30, -bh * 0.40
        el = self._draw_box(cx, cy, bw, bh, dx, dy, 0.16)

        self._dim_v(cx - 26, cy, cy + bh, "厚度 T", right=False)
        self._dim_width(cx, cy, bw, dx, dy)
        self._dim_h(cx, cx + bw, cy + bh + 32, "长度 L")
        self._dim_h(cx, cx + el, cy + bh + 58, "电极宽度 D")
        self._dim_h(cx + bw - el, cx + bw, cy + bh + 58, "D")

    # ---------- 贴片电阻：Top / Side / Bottom 三视图 ----------
    def _paint_resistor(self):
        W = self.width()
        bw = min(W * 0.21, 150)
        bh = 48

        # ---- Top View：矩形 + 两端电极 + 黑色主体 + 丝印 ----
        x0, ty = 26.0, 34.0
        el = bw * 0.15
        self._poly([(x0, ty), (x0 + bw, ty), (x0 + bw, ty + bh), (x0, ty + bh)],
                   fill=QColor(40, 45, 55, 240))
        self._poly([(x0, ty), (x0 + el, ty), (x0 + el, ty + bh), (x0, ty + bh)],
                   fill=_FILL_ELEC)
        self._poly([(x0 + bw - el, ty), (x0 + bw, ty),
                    (x0 + bw, ty + bh), (x0 + bw - el, ty + bh)], fill=_FILL_ELEC)
        self._poly([(x0 + el, ty), (x0 + bw - el, ty),
                    (x0 + bw - el, ty + bh), (x0 + el, ty + bh)], fill=_FILL_BODY)
        self._label("103", x0 + bw / 2.0, ty + bh / 2.0, color=_TEXT, px=16)
        self._label("〈 Top View 〉", x0 + bw / 2.0, ty + bh + 18,
                    color=_TEXT, px=10, bold=False)
        self._dim_h(x0, x0 + el, ty + bh + 40, "A")
        self._dim_h(x0, x0 + bw, ty + bh + 64, "长度 L")
        self._dim_v(x0 + bw + 22, ty, ty + bh, "W")

        # ---- Side View：薄长条 + 顶层黑色主体带 ----
        x1, sy = W * 0.36, 100.0
        sw, sh = min(W * 0.19, 132), 22.0
        self._poly([(x1, sy), (x1 + sw, sy), (x1 + sw, sy + sh), (x1, sy + sh)],
                   fill=QColor(40, 45, 55, 240))
        self._poly([(x1 + sw * 0.16, sy), (x1 + sw * 0.80, sy),
                    (x1 + sw * 0.80, sy + sh * 0.42), (x1 + sw * 0.16, sy + sh * 0.42)],
                   fill=_FILL_BODY)
        self._label("〈 Side View 〉", x1 + sw * 0.42, sy - 16, color=_TEXT, px=10, bold=False)
        self._dim_h(x1 + sw * 0.78, x1 + sw, sy - 16, "A", above=False)
        self._dim_h(x1 + sw * 0.60, x1 + sw, sy + sh + 28, "B", above=False)
        self._dim_v(x1 + sw + 22, sy, sy + sh, "T")

        # ---- Bottom View：矩形 + 两端电极 ----
        x2, by = W * 0.66, 34.0
        el2 = bw * 0.18
        self._poly([(x2, by), (x2 + bw, by), (x2 + bw, by + bh), (x2, by + bh)],
                   fill=QColor(40, 45, 55, 240))
        self._poly([(x2, by), (x2 + el2, by), (x2 + el2, by + bh), (x2, by + bh)],
                   fill=_FILL_ELEC)
        self._poly([(x2 + bw - el2, by), (x2 + bw, by),
                    (x2 + bw, by + bh), (x2 + bw - el2, by + bh)], fill=_FILL_ELEC)
        self._label("〈 Bottom View 〉", x2 + bw / 2.0, by + bh + 18,
                    color=_TEXT, px=10, bold=False)
        self._dim_h(x2, x2 + el2, by + bh + 40, "B")
        self._dim_h(x2, x2 + bw, by + bh + 64, "长度 L")
