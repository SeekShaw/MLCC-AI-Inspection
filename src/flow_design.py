"""检测流程设计子页面：左侧工具箱 + 右侧流程编辑画布。

被 DebugView 塞入「产品定位搜索设置」卡片标签页（与「产品目标搜索」同级、置于其左侧）。

卡片内嵌区域宽高受限（约 400×300），直接塞下「工具箱 + 画布」会很拥挤，本模块用
三个手段解决：
1. 工具箱可折叠（«/» 按钮）：折叠后画布独占整行宽度；
2. 画布可缩放（Ctrl+滚轮 / 工具栏 − 适应 ＋）＋ 自动布局：节点多时也能概览全流程；
3. 「⛶ 放大编辑」弹出 1100×720 可最大化的非模态窗口：与内嵌页共享同一个
   FlowDocument 数据模型，两边节点/连线实时同步，大窗口里从容编辑。
"""
import json
import math
import uuid

from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QObject, pyqtSignal, QEvent)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPainterPath, QPolygonF)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QDialog, QSizePolicy)

from styles import COLORS

# ---------------------------------------------------------------------------
# 工具箱数据：分类（图标, 数量）+ 每类算子名（未提供的按「分类名+序号」补齐）
# ---------------------------------------------------------------------------
TOOLBOX_CATEGORIES = [
    ("图像源", "📷", 2), ("图像预处理", "🎚", 26), ("图像分割", "✂", 18),
    ("区域处理", "▦", 18), ("几何生成", "◇", 10), ("模板匹配", "⧉", 9),
    ("测量", "📏", 17), ("灰度特征", "▥", 3), ("形状特征", "⬡", 6),
    ("轮廓处理", "◎", 24), ("结果输出", "🖥", 1), ("设备通讯", "🖧", 11),
    ("流程逻辑", "⋯", 8),
]

_REAL_ITEMS = {
    "图像源": ["读取图像", "读取视频流"],
    "图像预处理": ["高斯滤波", "中值滤波", "均值滤波", "对比度拉伸",
                    "直方图均衡", "仿射变换", "灰度化", "裁剪"],
    "图像分割": ["全局阈值", "自适应阈值", "颜色分割", "区域生长"],
    "区域处理": ["ROI裁剪", "形态学膨胀", "形态学腐蚀", "掩膜运算"],
    "几何生成": ["生成直线", "生成圆", "生成矩形", "生成旋转矩形"],
    "模板匹配": ["形状模板匹配", "灰度模板匹配"],
    "测量": ["卡尺工具", "距离测量", "角度测量", "圆拟合"],
    "灰度特征": ["灰度均值", "灰度方差"],
    "形状特征": ["面积", "周长", "圆度", "矩形度"],
    "轮廓处理": ["轮廓提取", "轮廓筛选", "轮廓拟合", "轮廓排序"],
    "结果输出": ["结果输出"],
    "设备通讯": ["串口发送", "TCP发送", "PLC写入"],
    "流程逻辑": ["条件分支", "循环执行", "并行分支", "延时等待"],
}

CAT_ICON = {name: icon for name, icon, _ in TOOLBOX_CATEGORIES}


def toolbox_items(cat, count):
    """返回某分类的算子名列表（优先真实名，不足则按序号补齐）。"""
    real = list(_REAL_ITEMS.get(cat, []))[:count]
    i = 1
    while len(real) < count:
        real.append(f"{cat}算子{i:02d}")
        i += 1
    return real


def _elide(text, limit=13):
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# 数据模型：节点 + 连线 + 撤销/重做（快照）
# ---------------------------------------------------------------------------
class FlowDocument(QObject):
    """流程数据模型：nodes=[{id,name,cat,x,y,ms}]，edges=[{src,dst}]。

    所有改动发出 changed 信号——内嵌画布与「放大编辑」窗口共用同一实例，
    任何一端编辑，另一端实时刷新。
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = []
        self._edges = []
        self._undo_stack = []
        self._redo_stack = []

    # ---- 快照 ----
    def _snapshot(self):
        return json.dumps({"nodes": self._nodes, "edges": self._edges},
                          ensure_ascii=False)

    def _restore(self, snap):
        d = json.loads(snap)
        self._nodes = d["nodes"]
        self._edges = d["edges"]
        self.changed.emit()

    def _push(self):
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    # ---- 只读访问 ----
    def nodes(self):
        return list(self._nodes)

    def edges(self):
        return list(self._edges)

    def node_count(self):
        return len(self._nodes)

    def edge_count(self):
        return len(self._edges)

    def node(self, nid):
        return next((n for n in self._nodes if n["id"] == nid), None)

    # ---- 编辑 ----
    def add_node(self, name, cat, x=80.0, y=80.0):
        self._push()
        ms = round(3 + (sum(map(ord, name)) % 90) / 3.0, 2)  # 示例耗时
        n = {"id": uuid.uuid4().hex[:8], "name": name, "cat": cat,
             "x": float(x), "y": float(y), "ms": ms}
        self._nodes.append(n)
        self.changed.emit()
        return n["id"]

    def move_node(self, nid, x, y, push=False):
        n = self.node(nid)
        if n is None:
            return
        if push:
            self._push()
        n["x"], n["y"] = float(x), float(y)
        self.changed.emit()

    def begin_move(self):
        """节点拖动开始时压一次撤销快照（不移动，仅记录起点状态）。"""
        self._push()

    def remove_node(self, nid):
        self._push()
        self._nodes = [n for n in self._nodes if n["id"] != nid]
        self._edges = [e for e in self._edges
                       if e["src"] != nid and e["dst"] != nid]
        self.changed.emit()

    def connect(self, src, dst):
        """从 src 输出端连到 dst 输入端；自连/重复连线被拒绝。"""
        if src == dst or self.node(src) is None or self.node(dst) is None:
            return False
        if any(e["src"] == src and e["dst"] == dst for e in self._edges):
            return False
        self._push()
        self._edges.append({"src": src, "dst": dst})
        self.changed.emit()
        return True

    def can_undo(self):
        return bool(self._undo_stack)

    def can_redo(self):
        return bool(self._redo_stack)

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())

    def auto_layout(self):
        """自动布局：按当前顺序纵向排列（演示用简单顺序布局）。"""
        self._push()
        for i, n in enumerate(self._nodes):
            n["x"], n["y"] = 60.0, 30.0 + i * 100
        self.changed.emit()


# ---------------------------------------------------------------------------
# 流程画布：点阵背景 + 节点卡片 + 连线（拖动输出端→输入端建立连线）
# ---------------------------------------------------------------------------
class FlowCanvas(QWidget):
    """流程编辑画布（可缩放/平移，支持节点拖动、连线、Del 删除、Ctrl+Z 撤销）。"""

    NODE_W, NODE_H = 176, 62

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self._scale = 1.0
        self._offset = QPointF(30.0, 30.0)
        self._selected = None
        self._drag = None       # ("node", id, grab_dx, grab_dy, pushed) / ("pan",sx,sy,ox,oy) / ("link", src)
        self._link_cur = None   # 连线拖动中的鼠标世界坐标
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(220, 200)
        self.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px;")

    # ---- 数据绑定 ----
    def set_document(self, doc):
        self._doc = doc
        if doc is not None:
            doc.changed.connect(self._on_doc_changed)
        self.update()

    def _on_doc_changed(self):
        self.update()

    def document(self):
        return self._doc

    # ---- 坐标变换 ----
    def _to_screen(self, a, b=None):
        # 兼容两种调用：_to_screen(wx, wy) 或 _to_screen(某QPointF)
        if b is None:
            wx, wy = a.x(), a.y()
        else:
            wx, wy = a, b
        return QPointF(self._offset.x() + wx * self._scale,
                       self._offset.y() + wy * self._scale)

    def _to_world(self, sx, sy):
        return ((sx - self._offset.x()) / self._scale,
                (sy - self._offset.y()) / self._scale)

    def _node_rect_w(self, n):
        return QRectF(n["x"], n["y"], self.NODE_W, self.NODE_H)

    def _input_port_w(self, n):
        r = self._node_rect_w(n)
        return (r.center().x(), r.top())

    def _output_port_w(self, n):
        r = self._node_rect_w(n)
        return (r.center().x(), r.bottom())

    # ---- 缩放/视图 ----
    def zoom_in(self):
        self._set_scale(self._scale * 1.2)

    def zoom_out(self):
        self._set_scale(self._scale / 1.2)

    def _set_scale(self, s):
        self._scale = max(0.4, min(2.5, s))
        self.update()

    def fit(self):
        """「适应」：把全部节点缩放居中到可视区。"""
        if self._doc is None or not self._doc.node_count():
            self._scale, self._offset = 1.0, QPointF(30, 30)
            self.update()
            return
        xs = [n["x"] for n in self._doc.nodes()]
        ys = [n["y"] for n in self._doc.nodes()]
        x0, x1 = min(xs), max(xs) + self.NODE_W
        y0, y1 = min(ys), max(ys) + self.NODE_H
        pad = 24
        sw = max(1.0, self.width() - pad * 2)
        sh = max(1.0, self.height() - pad * 2)
        s = min(sw / (x1 - x0), sh / (y1 - y0), 1.6)
        self._scale = max(0.4, s)
        self._offset = QPointF(
            (self.width() - (x1 - x0) * self._scale) / 2 - x0 * self._scale,
            (self.height() - (y1 - y0) * self._scale) / 2 - y0 * self._scale)
        self.update()

    def center_world(self):
        """当前可视区中心的世界坐标（新增节点落点）。"""
        return self._to_world(self.width() / 2, self.height() / 2)

    # ---- 命中检测 ----
    def _hit_node(self, wx, wy):
        for n in reversed(self._doc.nodes() if self._doc else []):
            if self._node_rect_w(n).contains(wx, wy):
                return n
        return None

    def _hit_input(self, wx, wy):
        for n in reversed(self._doc.nodes() if self._doc else []):
            px, py = self._input_port_w(n)
            if (px - wx) ** 2 + (py - wy) ** 2 <= 14 ** 2:
                return n
        return None

    def _at_output(self, n, wx, wy):
        px, py = self._output_port_w(n)
        return (px - wx) ** 2 + (py - wy) ** 2 <= 10 ** 2

    # ---- 鼠标 ----
    def mousePressEvent(self, event):
        if self._doc is None or event.button() != Qt.MouseButton.LeftButton:
            return
        sx, sy = event.position().x(), event.position().y()
        wx, wy = self._to_world(sx, sy)
        n = self._hit_node(wx, wy)
        if n is not None and self._at_output(n, wx, wy):
            self._drag = ("link", n["id"])
            self._link_cur = QPointF(wx, wy)
            self.setFocus()
            self.update()
            return
        if n is not None:
            self._selected = n["id"]
            self._drag = ("node", n["id"], wx - n["x"], wy - n["y"], False)
            self.setFocus()
            self.update()
            return
        self._selected = None
        self._drag = ("pan", sx, sy, self._offset.x(), self._offset.y())
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None or self._doc is None:
            return
        sx, sy = event.position().x(), event.position().y()
        kind = self._drag[0]
        if kind == "node":
            _, nid, gx, gy, pushed = self._drag
            if not pushed:
                self._doc.begin_move()          # 拖动开始压一次快照
                pushed = True
            self._drag = ("node", nid, gx, gy, pushed)
            wx, wy = self._to_world(sx, sy)
            self._doc.move_node(nid, wx - gx, wy - gy)
        elif kind == "pan":
            _, sx0, sy0, ox, oy = self._drag
            self._offset = QPointF(ox + sx - sx0, oy + sy - sy0)
            self.update()
        elif kind == "link":
            wx, wy = self._to_world(sx, sy)
            self._link_cur = QPointF(wx, wy)
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        if self._drag[0] == "link" and self._doc is not None:
            sx, sy = event.position().x(), event.position().y()
            wx, wy = self._to_world(sx, sy)
            tgt = self._hit_input(wx, wy)
            if tgt is not None and tgt["id"] != self._drag[1]:
                self._doc.connect(self._drag[1], tgt["id"])
        self._drag = None
        self._link_cur = None
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._set_scale(self._scale * (1.12 if event.angleDelta().y() > 0
                                           else 1 / 1.12))
        else:
            d = event.angleDelta()
            self._offset = QPointF(self._offset.x() + d.x() / 2,
                                   self._offset.y() + d.y() / 2)
            self.update()

    def keyPressEvent(self, event):
        if self._doc is None:
            return
        k = event.key()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected:
            self._doc.remove_node(self._selected)
            self._selected = None
        elif k == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._doc.redo()
            else:
                self._doc.undo()
        elif k == Qt.Key.Key_Y and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._doc.redo()
        else:
            super().keyPressEvent(event)

    # ---- 绘制 ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(COLORS["bg_card"]))
        self._draw_grid(p)
        if self._doc is None:
            return
        for e in self._doc.edges():
            self._draw_edge(p, e)
        if self._drag is not None and self._drag[0] == "link":
            self._draw_temp_link(p)
        for n in self._doc.nodes():
            self._draw_node(p, n)

    def _draw_grid(self, p):
        """点阵背景（世界坐标 24px 间距，随缩放/平移移动）。"""
        step = 24 * self._scale
        if step < 8:
            step *= 4
        ox = self._offset.x() % step
        oy = self._offset.y() % step
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        x = ox
        while x < self.width():
            y = oy
            while y < self.height():
                p.drawPoint(int(x), int(y))
                y += step
            x += step

    def _cat_color(self, cat):
        palette = ["#4261FF", "#0D822B", "#FF8C1A", "#B37FEB", "#13C2C2"]
        return palette[sum(map(ord, cat)) % len(palette)]

    def _draw_edge(self, p, e):
        src, dst = self._doc.node(e["src"]), self._doc.node(e["dst"])
        if src is None or dst is None:
            return
        s = self._to_screen(*self._output_port_w(src))
        t = self._to_screen(*self._input_port_w(dst))
        path = QPainterPath(s)
        dy = (t.y() - s.y()) * 0.5
        # 第二控制点 = (t.x, t.y - dy)：末端切线方向即 (t - c2)
        c2x, c2y = t.x(), t.y() - dy
        path.cubicTo(s.x(), s.y() + dy, c2x, c2y, t.x(), t.y())
        p.setPen(QPen(QColor("#4261FF"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # 箭头（沿末端切线方向；Qt6 已移除 QPainterPath.angleAtPercent，这里手算切线角）
        dx, dy2 = t.x() - c2x, t.y() - c2y
        if dx == 0 and dy2 == 0:
            dx, dy2 = 0.0, 1.0
        ang = math.degrees(math.atan2(dy2, dx))
        p.setBrush(QColor("#4261FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.save()
        p.translate(t)
        p.rotate(-ang)
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(-7, -4), QPointF(-7, 4)]))
        p.restore()

    def _draw_temp_link(self, p):
        src = self._doc.node(self._drag[1])
        if src is None:
            return
        s = self._to_screen(*self._output_port_w(src))
        t = self._to_screen(self._link_cur.x(), self._link_cur.y())
        p.setPen(QPen(QColor("#4261FF"), 2, Qt.PenStyle.DashLine))
        p.drawLine(s, t)
        p.setBrush(QColor("#4261FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(t, 4, 4)

    def _draw_node(self, p, n):
        s = self._scale
        tl = self._to_screen(n["x"], n["y"])
        w, h = self.NODE_W * s, self.NODE_H * s
        rect = QRectF(tl.x(), tl.y(), w, h)
        sel = self._selected == n["id"]
        # 卡片
        p.setPen(QPen(QColor("#4261FF" if sel else COLORS["border"]),
                      2 if sel else 1))
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.drawRoundedRect(rect, 8, 8)
        # 类别图标圆
        cc = QColor(self._cat_color(n["cat"]))
        d = 26 * s
        p.setBrush(cc)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(rect.left() + 10 * s, rect.center().y() - d / 2, d, d))
        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Microsoft YaHei", int(11 * max(0.7, s))))
        p.drawText(QRectF(rect.left() + 10 * s, rect.center().y() - d / 2, d, d),
                   Qt.AlignmentFlag.AlignCenter, CAT_ICON.get(n["cat"], "▣"))
        # 标题 / 副标题
        tx = rect.left() + (10 + d + 8) * s
        p.setPen(QColor(COLORS["text_primary"]))
        p.setFont(QFont("Microsoft YaHei", int(12 * max(0.7, s)), QFont.Weight.Bold))
        p.drawText(QRectF(tx, rect.top() + 8 * s, rect.right() - tx - 8 * s, 18 * s),
                   Qt.AlignmentFlag.AlignVCenter, _elide(n["name"]))
        p.setPen(QColor(COLORS["text_secondary"]))
        p.setFont(QFont("Microsoft YaHei", int(10 * max(0.7, s))))
        p.drawText(QRectF(tx, rect.top() + 30 * s, rect.right() - tx - 8 * s, 16 * s),
                   Qt.AlignmentFlag.AlignVCenter, n["cat"])
        # 耗时徽标（右上，示例）
        p.setPen(QColor("#0D822B"))
        p.drawText(QRectF(rect.right() - 70 * s, rect.top() - 16 * s, 70 * s, 14 * s),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"✓ {n['ms']:.2f} ms")
        # 输入端（顶部圆环）/ 输出端（底部蓝点）
        ip = self._to_screen(*self._input_port_w(n))
        p.setPen(QPen(QColor("#8A9099"), 1.5))
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.drawEllipse(ip, 4.5, 4.5)
        op = self._to_screen(*self._output_port_w(n))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4261FF"))
        p.drawEllipse(op, 5.5, 5.5)


# ---------------------------------------------------------------------------
# 工具箱：搜索框 + 可折叠分类（双击算子添加到画布）
# ---------------------------------------------------------------------------
class FlowToolBox(QWidget):
    """流程算子工具箱：搜索过滤 + 分类折叠 + 双击添加。"""

    add_requested = pyqtSignal(str, str)   # (分类, 算子名)

    ITEM_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 搜索算子")
        self._search.setFixedHeight(26)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refilter)
        v.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")
        inner = QWidget()
        self._inner_lay = QVBoxLayout(inner)
        self._inner_lay.setContentsMargins(0, 0, 2, 0)
        self._inner_lay.setSpacing(2)
        self._section_rows = {}   # cat -> {header, count_lbl, items: [row, ...]}
        for cat, icon, count in TOOLBOX_CATEGORIES:
            self._inner_lay.addWidget(self._build_section(cat, icon, count))
        self._inner_lay.addStretch(1)
        self._scroll.setWidget(inner)
        v.addWidget(self._scroll, 1)

        foot = QHBoxLayout()
        wand = QPushButton("🪄")
        wand.setFixedSize(26, 24)
        wand.setToolTip("算子收藏（示例占位）")
        wand.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['bg_panel']}; color:{COLORS['text_primary']}; "
            f"border:1px solid {COLORS['border']}; border-radius:4px;}}"
            f"QPushButton:hover{{background-color:{COLORS['border']};}}")
        foot.addWidget(wand)
        foot.addStretch(1)
        v.addLayout(foot)

    def _build_section(self, cat, icon, count):
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 2, 2, 2)
        hl.setSpacing(4)
        arrow = QLabel("▶")
        arrow.setFixedWidth(10)
        arrow.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:9px;")
        name = QLabel(f"{icon} {cat}")
        name.setStyleSheet(f"color:{COLORS['text_primary']}; font-size:12px; font-weight:bold;")
        cnt = QLabel(f"{count} 项")
        cnt.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:10px;")
        # 子标签不拦截鼠标，点击整行都落在 head 上（由事件过滤器统一处理折叠）
        for child in (arrow, name, cnt):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl.addWidget(arrow)
        hl.addWidget(name)
        hl.addStretch(1)
        hl.addWidget(cnt)
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        head.installEventFilter(self)
        rows = []
        for item in toolbox_items(cat, count):
            row = QLabel(f"    {item}")
            row.setFixedHeight(self.ITEM_H)
            row.setToolTip("双击添加到流程画布")
            row.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:11px;"
                f"background-color:transparent; border-radius:3px; padding-left:6px;")
            row.setVisible(False)
            row.installEventFilter(self)
            rows.append(row)
        self._section_rows[cat] = {"arrow": arrow, "rows": rows,
                                   "count": count, "head": head,
                                   "open": False}
        return head

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            for cat, info in self._section_rows.items():
                if obj in info["rows"]:
                    self.add_requested.emit(cat, obj.text().strip())
                    return True
        elif event.type() == QEvent.Type.MouseButtonPress:
            for cat, info in self._section_rows.items():
                if obj is info["head"]:
                    self._toggle_section(cat)
                    return True
        return super().eventFilter(obj, event)

    def _toggle_section(self, cat):
        info = self._section_rows[cat]
        info["open"] = not info["open"]
        info["arrow"].setText("▼" if info["open"] else "▶")
        for r in info["rows"]:
            r.setVisible(info["open"] and self._match(r, self._search.text()))

    @staticmethod
    def _row_text(r):
        return r.text().strip()

    def _match(self, row, text):
        return not text or text.lower() in self._row_text(row).lower()

    def _refilter(self, text):
        for cat, info in self._section_rows.items():
            any_match = False
            for r in info["rows"]:
                m = self._match(r, text)
                r.setVisible(m and (info["open"] or bool(text)))
                any_match = any_match or m
            info["head"].setVisible(any_match)
            if text:
                info["arrow"].setText("▼")
                info["open"] = True

    def categories(self):
        return [(name, icon, count) for name, icon, count in TOOLBOX_CATEGORIES]


# ---------------------------------------------------------------------------
# 子页面：工具箱 + 画布 + 工具栏（内嵌 / 大窗口两种宿主）
# ---------------------------------------------------------------------------
class FlowDesignPage(QWidget):
    """检测流程设计页（内嵌于卡片标签页，或被「放大编辑」大窗口承载）。"""

    def __init__(self, parent=None, document=None, run_log=None, embedded=True):
        super().__init__(parent)
        self._run_log = run_log
        self._embedded = embedded
        self._dlg = None
        self.document = document or FlowDocument()
        self.document.changed.connect(self._on_doc_changed)
        self._build_ui()
        self._seed_demo()

    # ---- UI ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(6)

        # 工具栏：提示语 + 视图操作
        bar = QHBoxLayout()
        bar.setSpacing(4)
        hint = QLabel("插入算子：双击左侧工具箱项；拖动节点底部输出端到目标顶部输入端建立连线")
        hint.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        bar.addWidget(hint)
        bar.addStretch(1)

        def _tbtn(text, tip, cb):
            b = QPushButton(text)
            b.setFixedSize(26, 24)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background-color:{COLORS['bg_panel']}; color:{COLORS['text_primary']}; "
                f"border:1px solid {COLORS['border']}; border-radius:4px; font-size:12px;}}"
                f"QPushButton:hover{{background-color:{COLORS['border']};}}")
            b.clicked.connect(cb)
            bar.addWidget(b)
            return b

        self._btn_undo = _tbtn("↩", "撤销 (Ctrl+Z)", self.document.undo)
        self._btn_redo = _tbtn("↪", "重做 (Ctrl+Y)", self.document.redo)
        self._btn_zoom_out = _tbtn("−", "缩小", lambda: self.canvas.zoom_out())
        self._btn_fit = _tbtn("⊡", "适应画布", lambda: self.canvas.fit())
        self._btn_zoom_in = _tbtn("＋", "放大", lambda: self.canvas.zoom_in())
        self._btn_layout = _tbtn("⇅", "自动布局", self._auto_layout)
        if self._embedded:
            self._btn_expand = _tbtn("⛶", "放大编辑（弹出大窗口）", self._open_dialog)
            self._btn_expand.setStyleSheet(
                f"QPushButton{{background-color:{COLORS['accent_blue']}; color:white; "
                f"border:none; border-radius:4px; font-size:12px;}}"
                f"QPushButton:hover{{background-color:#5570ff;}}")
        v.addLayout(bar)

        # 主体：工具箱（可折叠）+ 画布
        body = QHBoxLayout()
        body.setSpacing(6)
        self.toolbox = FlowToolBox()
        self.toolbox.add_requested.connect(self._on_tool_add)
        self._toolbox_holder = QWidget()
        tv = QVBoxLayout(self._toolbox_holder)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.toolbox)
        self._toolbox_holder.setFixedWidth(170)
        body.addWidget(self._toolbox_holder)

        self._btn_collapse = QPushButton("«")
        self._btn_collapse.setFixedSize(18, 44)
        self._btn_collapse.setToolTip("折叠 / 展开工具箱")
        self._btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_collapse.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['bg_panel']}; color:{COLORS['text_secondary']}; "
            f"border:1px solid {COLORS['border']}; border-radius:4px;}}"
            f"QPushButton:hover{{color:{COLORS['text_primary']};}}")
        self._btn_collapse.clicked.connect(self.toggle_toolbox)
        body.addWidget(self._btn_collapse, 0, Qt.AlignmentFlag.AlignTop)

        self.canvas = FlowCanvas()
        self.canvas.set_document(self.document)
        body.addWidget(self.canvas, 1)
        v.addLayout(body, 1)

        self._fitted = False

    def _seed_demo(self):
        """首次创建时给一组示例流程（读取图像 → 二值化），与参考图一致。"""
        if self.document.node_count():
            return
        n1 = self.document.add_node("读取图像01", "图像源", 60, 30)
        n2 = self.document.add_node("二值化(OpenCv…", "图像预处理", 60, 150)
        self.document.connect(n1, n2)

    # ---- 行为 ----
    def _on_tool_add(self, cat, item):
        cx, cy = self.canvas.center_world()
        k = self.document.node_count() % 5
        nid = self.document.add_node(item, cat, cx - FlowCanvas.NODE_W / 2 + k * 18,
                                     cy - FlowCanvas.NODE_H / 2 + k * 14)
        self._log(f"流程设计：插入算子「{item}」（{cat}）")

    def _auto_layout(self):
        self.document.auto_layout()
        self.canvas.fit()
        self._log("流程设计：已自动布局")

    def _on_doc_changed(self):
        self._btn_undo.setEnabled(self.document.can_undo())
        self._btn_redo.setEnabled(self.document.can_redo())

    def toggle_toolbox(self):
        vis = not self._toolbox_holder.isVisible()
        self._toolbox_holder.setVisible(vis)
        self._btn_collapse.setText("«" if vis else "»")

    def _open_dialog(self):
        """弹出「放大编辑」大窗口：共享同一数据模型，两边实时同步。"""
        if self._dlg is not None and self._dlg.isVisible():
            self._dlg.raise_()
            self._dlg.activateWindow()
            return
        self._dlg = FlowDesignDialog(self.document, self)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    def _log(self, msg):
        if self._run_log is None:
            return
        try:
            from datetime import datetime
            self._run_log.add(datetime.now().strftime("%H:%M:%S"), msg, "#4261FF")
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self.canvas.fit()


class FlowDesignDialog(QDialog):
    """「放大编辑」非模态大窗口：与内嵌页共享 FlowDocument，实时同步。"""

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle("检测流程设计 - 流程编辑器（放大编辑）")
        self.resize(1100, 720)
        self.setModal(False)
        # 与主程序暗色弹窗一致
        self.setStyleSheet(f"QDialog{{background-color:{COLORS['bg_dark']};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(FlowDesignPage(document=document, embedded=False))
