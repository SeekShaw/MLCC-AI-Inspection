"""检测流程设计子页面：左侧工具箱 + 右侧流程编辑画布。

被 DebugView 塞入「产品定位搜索设置」卡片标签页（与「产品目标搜索」同级、置于其左侧）。

卡片内嵌区域宽高受限（约 400×300），直接塞下「工具箱 + 画布」会很拥挤，本模块用
三个手段解决：
1. 工具箱可折叠（«/» 按钮）：折叠后画布独占整行宽度；
2. 画布可缩放（Ctrl+滚轮 / 工具栏 − 适应 ＋）＋ 自动布局：节点多时也能概览全流程；
3. 「放大编辑」弹出 1100×720 可最大化的非模态窗口：与内嵌页共享同一个
   FlowDocument 数据模型，两边节点/连线实时同步，大窗口里从容编辑。
"""
import json
import math
import os
import uuid

from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QObject, pyqtSignal, QEvent, QSize, QPoint, QTimer)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPainterPath, QPolygonF, QIcon, QPixmap,
    QCursor, QFontMetrics)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QDialog, QSizePolicy, QDoubleSpinBox, QProgressBar, QFrame,
    QCheckBox, QMenu, QLayout, QTabWidget, QComboBox, QFileDialog)

from styles import COLORS

# ---------------------------------------------------------------------------
# 工具箱数据：分类（数量）+ 每类算子名（未提供的按「分类名+序号」补齐）
# 注：图标一律用 QPainter 现绘矢量图 / CJK 文字，避免依赖 emoji 在 YaHei 下的字形。
# ---------------------------------------------------------------------------
TOOLBOX_CATEGORIES = [
    ("图像源", 2), ("图像预处理", 26), ("图像分割", 18),
    ("区域处理", 18), ("几何生成", 10), ("模板匹配", 9),
    ("测量", 17), ("灰度特征", 3), ("形状特征", 6),
    ("轮廓处理", 24), ("结果输出", 1), ("设备通讯", 11),
    ("流程逻辑", 8),
]

# 节点圆标 / 工具箱色块使用的分类色（与 _cat_color 一致）
_CAT_PALETTE = ["#4261FF", "#0D822B", "#FF8C1A", "#B37FEB", "#13C2C2"]


def _cat_color(cat):
    """分类对应的稳定色（用于节点圆标与工具箱色块）。"""
    return _CAT_PALETTE[sum(map(ord, cat)) % len(_CAT_PALETTE)]


# 节点圆标里显示的中文缩写（保证任意字体可见，且与分类一一对应）
CAT_BADGE = {
    "图像源": "源", "图像预处理": "预", "图像分割": "割", "区域处理": "区",
    "几何生成": "几", "模板匹配": "模", "测量": "测", "灰度特征": "灰",
    "形状特征": "形", "轮廓处理": "轮", "结果输出": "出",
    "设备通讯": "讯", "流程逻辑": "逻",
}


def _cat_badge(cat):
    return CAT_BADGE.get(cat, (cat[0] if cat else "?"))


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


def toolbox_items(cat, count):
    """返回某分类的算子名列表（优先真实名，不足则按序号补齐）。"""
    real = list(_REAL_ITEMS.get(cat, []))[:count]
    i = 1
    while len(real) < count:
        real.append(f"{cat}算子{i:02d}")
        i += 1
    return real


# ---------------------------------------------------------------------------
# 工具栏矢量图标：全部用 QPainter 现绘，不依赖任何字体字形
# ---------------------------------------------------------------------------
def _draw_glyph(p, kind, x, y, w, h):
    """在 (x,y,w,h) 盒子里绘制 kind 对应的矢量图标（线条统一由调用方设好）。"""
    mid = y + h / 2

    def _L(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _arrow_head(ax, ay, dx, dy, size=4.0):
        # 在 (ax,ay) 处画指向 (dx,dy) 方向的箭头（dx,dy 为单位方向）
        px, py = -dy, dx  # 垂直方向
        _L(ax, ay, ax - dx * size + px * size * 0.7, ay - dy * size + py * size * 0.7)
        _L(ax, ay, ax - dx * size - px * size * 0.7, ay - dy * size - py * size * 0.7)

    if kind == "undo":                       # 左箭头
        _L(x + w * 0.72, mid, x + w * 0.30, mid)
        _arrow_head(x + w * 0.30, mid, -1, 0)
    elif kind == "redo":                     # 右箭头
        _L(x + w * 0.28, mid, x + w * 0.70, mid)
        _arrow_head(x + w * 0.70, mid, 1, 0)
    elif kind in ("zoom_out", "zoom_in"):    # 放大镜 + (减/加)
        cx, cy, r = x + w * 0.40, y + h * 0.40, w * 0.24
        p.drawEllipse(QPointF(cx, cy), r, r)
        _L(cx + r * 0.7, cy + r * 0.7, x + w * 0.84, y + h * 0.84)
        if kind == "zoom_out":
            _L(cx - r * 0.6, cy, cx + r * 0.6, cy)
        else:
            _L(cx - r * 0.6, cy, cx + r * 0.6, cy)
            _L(cx, cy - r * 0.6, cx, cy + r * 0.6)
    elif kind == "fit":                      # 四角括号（适应视窗）
        t, a, b = 0.22, 0.13, 0.13
        # 左上
        _L(x + w * t, y + h * (t + b), x + w * t, y + h * t)
        _L(x + w * t, y + h * t, x + w * (t + a), y + h * t)
        # 右上
        _L(x + w * (1 - t), y + h * (t + b), x + w * (1 - t), y + h * t)
        _L(x + w * (1 - t), y + h * t, x + w * (1 - t - a), y + h * t)
        # 左下
        _L(x + w * t, y + h * (1 - t - b), x + w * t, y + h * (1 - t))
        _L(x + w * t, y + h * (1 - t), x + w * (t + a), y + h * (1 - t))
        # 右下
        _L(x + w * (1 - t), y + h * (1 - t - b), x + w * (1 - t), y + h * (1 - t))
        _L(x + w * (1 - t), y + h * (1 - t), x + w * (1 - t - a), y + h * (1 - t))
    elif kind == "layout":                   # 上下双箭头（自动布局）
        x1 = x + w * 0.35
        _L(x1, y + h * 0.76, x1, y + h * 0.26)
        _arrow_head(x1, y + h * 0.26, 0, -1)
        x2 = x + w * 0.65
        _L(x2, y + h * 0.24, x2, y + h * 0.74)
        _arrow_head(x2, y + h * 0.74, 0, 1)
    elif kind == "expand":                   # 方框 + 对角箭头（放大编辑）
        m = 0.22
        p.drawRect(QRectF(x + w * m, y + h * m, w * 0.56, h * 0.56))
        _L(x + w * 0.40, y + h * 0.60, x + w * 0.60, y + h * 0.40)
        _arrow_head(x + w * 0.60, y + h * 0.40, 0.7, -0.7)
    elif kind == "params":                   # 调节滑杆（算法参数）
        for i, fy in enumerate((0.28, 0.50, 0.72)):
            yy = y + h * fy
            _L(x + w * 0.14, yy, x + w * 0.86, yy)
            kx = x + w * (0.62 if i != 1 else 0.34)
            p.drawEllipse(QPointF(kx, yy), w * 0.09, h * 0.09)
    elif kind == "timing":                   # 时钟（算法耗时）
        cx, cy, r = x + w * 0.5, y + h * 0.5, w * 0.36
        p.drawEllipse(QPointF(cx, cy), r, r)
        _L(cx, cy, cx, cy - r * 0.62)
        _L(cx, cy, cx + r * 0.48, cy + r * 0.28)
    elif kind == "io":                       # 双向箭头（输入输出）
        yy1, yy2 = y + h * 0.32, y + h * 0.68
        _L(x + w * 0.12, yy1, x + w * 0.88, yy1)
        _arrow_head(x + w * 0.88, yy1, 1, 0)
        _L(x + w * 0.88, yy2, x + w * 0.12, yy2)
        _arrow_head(x + w * 0.12, yy2, -1, 0)
    elif kind == "default_set":              # 下箭头 + 底线（设为默认）
        cx = x + w * 0.5
        _L(cx, y + h * 0.18, cx, y + h * 0.60)
        _arrow_head(cx, y + h * 0.60, 0, 1)
        _L(x + w * 0.18, y + h * 0.82, x + w * 0.82, y + h * 0.82)
    elif kind == "restore":                  # 逆时针回环箭头（恢复至默认）
        cx, cy, r = x + w * 0.5, y + h * 0.5, w * 0.34
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, 270 * 16)
        _arrow_head(cx - r * 0.02, cy - r, -0.9, -0.4)
    elif kind == "factory":                  # 方箱 + 内部下箭头（恢复至出厂）
        p.drawRect(QRectF(x + w * 0.2, y + h * 0.2, w * 0.6, h * 0.6))
        cx = x + w * 0.5
        _L(cx, y + h * 0.32, cx, y + h * 0.62)
        _arrow_head(cx, y + h * 0.62, 0, 1)
    elif kind == "unit":                     # 直尺（单位设置）
        p.drawRect(QRectF(x + w * 0.12, y + h * 0.3, w * 0.76, h * 0.4))
        for fx in (0.3, 0.5, 0.7):
            _L(x + w * fx, y + h * 0.3, x + w * fx, y + h * 0.46)
    elif kind == "output":                   # 方箱 + 外向箭头（出料设置）
        p.drawPolyline(QPointF(x + w * 0.55, y + h * 0.2),
                       QPointF(x + w * 0.2, y + h * 0.2),
                       QPointF(x + w * 0.2, y + h * 0.8),
                       QPointF(x + w * 0.55, y + h * 0.8))
        _L(x + w * 0.42, y + h * 0.5, x + w * 0.86, y + h * 0.5)
        _arrow_head(x + w * 0.86, y + h * 0.5, 1, 0)
    elif kind == "sync":                     # 双循环箭头（全部同步）
        cx, cy, r = x + w * 0.5, y + h * 0.5, w * 0.34
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 30 * 16, 140 * 16)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 210 * 16, 140 * 16)
        _arrow_head(cx + r * 0.62, cy - r * 0.62, 0.8, 0.6)
        _arrow_head(cx - r * 0.62, cy + r * 0.62, -0.8, -0.6)
    # ---- 算法参数首页底部图标行（2026-10-21 需求） ----
    elif kind == "eye":                      # 眼睛（ROI / 结果 显示切换）
        cx, cy = x + w * 0.5, y + h * 0.5
        p.drawArc(QRectF(x + w * 0.08, y + h * 0.24, w * 0.84, h * 0.52),
                  0 * 16, 360 * 16)
        p.setBrush(Qt.BrushStyle.SolidPattern)
        p.drawEllipse(QPointF(cx, cy), w * 0.14, h * 0.14)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "chart":                    # 柱状图（结果显示切换）
        for i, (fx, fh) in enumerate(((0.24, 0.42), (0.5, 0.66),
                                      (0.76, 0.3))):
            _L(x + w * fx, y + h * 0.84, x + w * fx, y + h * (0.84 - fh))
    elif kind == "full_roi":                 # 虚线大框 + 内实线小框（使用全图）
        pen = p.pen()
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(QRectF(x + w * 0.1, y + h * 0.1, w * 0.8, h * 0.8))
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawRect(QRectF(x + w * 0.34, y + h * 0.34, w * 0.32, h * 0.32))
    elif kind == "roi_edit":                 # 框 + 笔（ROI 编辑）
        p.drawRect(QRectF(x + w * 0.12, y + h * 0.16, w * 0.6, h * 0.56))
        _L(x + w * 0.42, y + h * 0.82, x + w * 0.86, y + h * 0.28)
        _L(x + w * 0.42, y + h * 0.82, x + w * 0.48, y + h * 0.76)
    elif kind == "list_cfg":                 # 列表（算法输出配置）
        for fy in (0.22, 0.5, 0.78):
            p.drawEllipse(QPointF(x + w * 0.16, y + h * fy), 1.2, 1.2)
            _L(x + w * 0.34, y + h * fy, x + w * 0.88, y + h * fy)
    elif kind == "palette_cfg":              # 调色板（显示配置）
        p.drawEllipse(QRectF(x + w * 0.1, y + h * 0.1, w * 0.8, h * 0.8))
        for fx, fy in ((0.34, 0.36), (0.62, 0.3), (0.68, 0.6)):
            p.drawEllipse(QPointF(x + w * fx, y + h * fy), 1.3, 1.3)


def _make_icon(kind, color="#4261FF"):
    """把矢量图标渲染成 QIcon（尺寸 16×16，离屏可绘）。"""
    sz = 16
    pm = QPixmap(sz, sz)
    pm.fill(Qt.GlobalColor.transparent)
    pp = QPainter(pm)
    pp.setRenderHint(QPainter.RenderHint.Antialiasing)
    pp.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    pp.setBrush(Qt.BrushStyle.NoBrush)
    _draw_glyph(pp, kind, 1, 1, sz - 2, sz - 2)
    pp.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# 数据模型：节点 + 连线 + 撤销/重做（快照）
# ---------------------------------------------------------------------------
class FlowDocument(QObject):
    """流程数据模型：nodes=[{id,name,cat,x,y,ms}]，edges=[{src,dst}]。

    所有改动发出 changed 信号——内嵌画布与「放大编辑」窗口共用同一实例，
    任何一端编辑，另一端实时刷新。
    """

    changed = pyqtSignal()
    # ⚠️ 2026-10-21 需求：全局选中变化（内嵌页/放大编辑窗任一处选中算子时
    # 发出）——缩略图条等「跟随当前选中算子」的 UI 据此在两个窗口同步显隐。
    sel_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = []
        self._edges = []
        self._undo_stack = []
        self._redo_stack = []
        # ⚠️ 2026-10-21 需求：选中算子记录在共享文档上——内嵌页与「放大编辑」
        # 窗共用同一实例，缩略图条等跟随同一「当前选中算子」，避免另一窗口残留。
        self.sel_nid = None
        # ⚠️ 2026-10-21 需求：「运行到当前节点」限制（算子右键菜单设置）。
        # 设置后，上1张/下1张等执行算法流程时只运行到此算子（含）即结束。
        self._run_until = None

    def set_ms(self, nid, ms):
        """更新算子示例耗时并刷新画布（流程执行时的性能展示位：✔ ms 徽标）。"""
        n = self.node(nid)
        if n is None:
            return
        n["ms"] = round(float(ms), 2)
        self.changed.emit()

    def set_run_until(self, nid):
        """设置/清除「运行到当前节点」限制（传 None 清除）。"""
        self._run_until = nid
        self.changed.emit()

    def run_until(self):
        return self._run_until

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

    def rename_node(self, nid, name):
        """重命名算子（入撤销栈；改名后画布/各浮窗随 changed 信号刷新）。

        ⚠️ 2026-10-21 需求：算法参数首页「工具名称」可自定义修改，
        改完所有显示旧名的地方一起同步。空名 / 同名直接忽略（返回 False）。
        """
        n = self.node(nid)
        if n is None:
            return False
        name = str(name).strip()
        if not name or name == n["name"]:
            return False
        self._push()
        n["name"] = name[:30]      # 与画布卡片省略上限同量级，防止超长
        self.changed.emit()
        return True

    def remove_edges_around(self, nid, incoming=False, outgoing=False):
        """删除与节点相连的连线：incoming=前置（上游→本节点），outgoing=后置。

        返回删除的条数；无可删连线时不入撤销栈（右键菜单里对应项
        已按有无连线禁用，这里兜底）。
        """
        if not nid:
            return 0
        hits = [e for e in self._edges
                if (incoming and e["dst"] == nid)
                or (outgoing and e["src"] == nid)]
        if not hits:
            return 0
        self._push()
        self._edges = [e for e in self._edges if e not in hits]
        self.changed.emit()
        return len(hits)

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

    # 选中节点变化：参数为节点 id（取消选中/点空白时为空串），供右侧
    # 「算法参数 / 算法耗时」浮窗实时跟随当前选中算子刷新内容。
    selection_changed = pyqtSignal(str)
    # 画布尺寸变化（右侧浮窗需夹取回可视范围）
    canvas_resized = pyqtSignal()

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

    def _zoom_at(self, sx, sy, factor):
        """以光标处为锚点缩放：锚点下的世界坐标保持不动（滚轮缩放用）。"""
        wx, wy = self._to_world(sx, sy)
        self._set_scale(self._scale * factor)
        nx, ny = self._to_world(sx, sy)      # 新缩放下同一屏幕点的世界坐标
        self._offset = QPointF(self._offset.x() + (nx - wx) * self._scale,
                               self._offset.y() + (ny - wy) * self._scale)
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
            if (px - wx) ** 2 + (py - wy) ** 2 <= 18 ** 2:
                return n
        return None

    def _at_output(self, n, wx, wy):
        px, py = self._output_port_w(n)
        return (px - wx) ** 2 + (py - wy) ** 2 <= 16 ** 2

    def _hit_output(self, wx, wy):
        for n in reversed(self._doc.nodes() if self._doc else []):
            if self._at_output(n, wx, wy):
                return n
        return None

    # ---- 鼠标 ----
    def mousePressEvent(self, event):
        if self._doc is None:
            return
        sx, sy = event.position().x(), event.position().y()
        wx, wy = self._to_world(sx, sy)
        # ⚠️ 2026-10-21 需求：左键=连线、右键=拖动算子（原先都用左键，
        # 按输出/输入圆点经常变成拖走算子，连线难操作）。右键命中算子：
        # 选中并开始拖动；松开时若几乎未移动则视为右键单击，弹算子菜单。
        if event.button() == Qt.MouseButton.RightButton:
            n = self._hit_node(wx, wy)
            if n is not None:
                self._select(n["id"])
                self._drag = ("node", n["id"], wx - n["x"], wy - n["y"],
                              False, True, wx, wy)
                self.setFocus()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # ⚠️ 端口判定必须先于节点体命中：端口圆心恰在节点矩形底/顶边上，
        # QRectF.contains 不含边界，先查节点体会漏掉正点圆心的情形
        # （实测正点圆心会掉进平移分支，连线无法起始）。
        src = self._hit_output(wx, wy)
        if src is not None:
            self._drag = ("link", src["id"])        # 从输出端起线 → 目标
            self._link_cur = QPointF(wx, wy)
            self.setFocus()
            self.update()
            return
        dst = self._hit_input(wx, wy)
        if dst is not None:
            self._drag = ("link_rev", dst["id"])    # 从输入端反向起线 → 来源
            self._link_cur = QPointF(wx, wy)
            self.setFocus()
            self.update()
            return
        n = self._hit_node(wx, wy)
        if n is not None:
            # 左键按在算子上：仅选中（位置拖动已让给右键），不启动平移
            self._select(n["id"])
            self.setFocus()
            return
        self._select(None)
        self._drag = ("pan", sx, sy, self._offset.x(), self._offset.y())

    def _select(self, nid):
        """设置当前选中算子（变化时发出 selection_changed，右侧浮窗随之刷新）。"""
        prev = self._selected
        self._selected = nid
        # 同步到共享文档（内嵌页 / 放大编辑窗共用），供缩略图条显隐等使用
        if self._doc is not None:
            self._doc.sel_nid = nid
            self._doc.sel_changed.emit(nid or "")
        self.update()
        if prev != nid:
            self.selection_changed.emit(nid or "")

    def _open_node_menu(self, gpos, nid):
        """右键菜单：删除该算子 / 删除前置（入）连线 / 删除后置（出）连线。"""
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background-color:{COLORS['bg_panel']}; "
            f"color:{COLORS['text_primary']}; border:1px solid {COLORS['border']}; "
            f"padding:4px;}}"
            f"QMenu::item{{padding:5px 18px; border-radius:3px;}}"
            f"QMenu::item:selected{{background-color:{COLORS['accent_blue']}; color:white;}}")
        edges = self._doc.edges() if self._doc is not None else []
        has_in = any(e["dst"] == nid for e in edges)
        has_out = any(e["src"] == nid for e in edges)
        # 2026-10-21 需求：选中算子后右键可单独删除其前/后置连线
        m_in = menu.addAction("删除前置节点连线")
        m_in.setEnabled(has_in)
        m_in.triggered.connect(
            lambda: self._remove_edges(nid, incoming=True, outgoing=False))
        m_out = menu.addAction("删除后置节点连线")
        m_out.setEnabled(has_out)
        m_out.triggered.connect(
            lambda: self._remove_edges(nid, incoming=False, outgoing=True))
        menu.addSeparator()
        # ⚠️ 2026-10-21 需求：「运行到当前节点」——设置后，上1张/下1张等
        # 执行算法流程时只运行到此算子（含）即结束；已设置时可取消。
        if self._doc is not None and self._doc.run_until() == nid:
            menu.addAction("取消运行到当前节点").triggered.connect(
                lambda: self._doc.set_run_until(None))
        else:
            menu.addAction("运行到当前节点").triggered.connect(
                lambda: self._doc.set_run_until(nid))
        menu.addAction("删除").triggered.connect(lambda: self._remove_node(nid))
        menu.exec(gpos)

    def _remove_edges(self, nid, incoming=False, outgoing=False):
        """删除算子的前/后置连线（右键菜单入口，文档层带撤销）。"""
        if self._doc is None or not nid:
            return
        self._doc.remove_edges_around(nid, incoming=incoming, outgoing=outgoing)

    def _remove_node(self, nid):
        """删除算子及其连线，并清空选中（Delete 键复用同一入口）。"""
        if self._doc is None or not nid:
            return
        self._doc.remove_node(nid)
        if self._selected == nid:
            self._select(None)

    def selected_node(self):
        """当前选中节点的数据 dict（含 name/cat/ms 等）；未选中返回 None。"""
        if self._doc is None or not self._selected:
            return None
        return self._doc.node(self._selected)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.canvas_resized.emit()

    def mouseMoveEvent(self, event):
        if self._drag is None or self._doc is None:
            return
        sx, sy = event.position().x(), event.position().y()
        kind = self._drag[0]
        if kind == "node":
            _, nid, gx, gy, pushed, _from_right, _wx0, _wy0 = self._drag
            if not pushed:
                self._doc.begin_move()          # 拖动开始压一次快照
                pushed = True
            self._drag = ("node", nid, gx, gy, pushed, _from_right, _wx0, _wy0)
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
        kind = self._drag[0]
        sx, sy = event.position().x(), event.position().y()
        wx, wy = self._to_world(sx, sy)
        if kind == "node":
            _, nid, _gx, _gy, _pushed, from_right, wx0, wy0 = self._drag
            if from_right and abs(wx - wx0) + abs(wy - wy0) < 3:
                # 右键几乎未拖动 → 视为单击：弹出算子菜单（删除算子/连线）
                self._open_node_menu(event.globalPosition().toPoint(), nid)
        elif kind == "link" and self._doc is not None:
            # 落点放宽：命中输入圆点或目标算子任意位置均可建立连线
            tgt = self._hit_input(wx, wy) or self._hit_node(wx, wy)
            if tgt is not None and tgt["id"] != self._drag[1]:
                self._doc.connect(self._drag[1], tgt["id"])
        elif kind == "link_rev" and self._doc is not None:
            src = self._hit_output(wx, wy) or self._hit_node(wx, wy)
            if src is not None and src["id"] != self._drag[1]:
                self._doc.connect(src["id"], self._drag[1])
        self._drag = None
        self._link_cur = None
        self.update()

    def wheelEvent(self, event):
        """滚轮：默认以光标为锚点缩放画布；Shift+滚轮保留平移。"""
        d = event.angleDelta()
        step = d.y() if d.y() != 0 else d.x()
        if step == 0:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._offset = QPointF(self._offset.x() + d.x() / 2,
                                   self._offset.y() + d.y() / 2)
            self.update()
        else:
            self._zoom_at(event.position().x(), event.position().y(),
                          1.12 if step > 0 else 1 / 1.12)
        event.accept()

    def keyPressEvent(self, event):
        if self._doc is None:
            return
        k = event.key()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected:
            self._remove_node(self._selected)
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
        self._draw_hints(p)     # 左下角半透明操作说明（不随世界坐标缩放）
        if self._doc is None:
            return
        for e in self._doc.edges():
            self._draw_edge(p, e)
        if self._drag is not None and self._drag[0] in ("link", "link_rev"):
            self._draw_temp_link(p)
        for n in self._doc.nodes():
            self._draw_node(p, n)

    # ⚠️ 2026-10-21 需求：左下角常驻操作说明，浅色 + 透明度（不喧宾夺主）
    HINT_LINES = (
        "画布流程放大：          鼠标滚轮向上",
        "画布流程缩小：          鼠标滚轮向下",
        "绘制节点连线：          鼠标左键单击选中起点，拖动且不松开至终点",
        "添加算子至画布流程：    选中算子并鼠标左键双击",
        "流程图拖拽调整位置：    画布中空白位置鼠标左键单击，拖动且不松开",
        "画布中算子位置调整：    点击选中该算子并按住鼠标右键，拖动且不松开",
    )

    def _draw_hints(self, p):
        """画布左下角绘制半透明浅色操作提示（设备坐标，不随缩放/平移变化）。"""
        f = QFont("Microsoft YaHei")
        f.setPixelSize(11)
        p.setFont(f)
        # 浅灰白 + 低 alpha（≈22%），叠在深底上即「隐约可见」
        p.setPen(QPen(QColor(208, 214, 226, 56)))
        lh = 16
        x = 10
        y = self.height() - len(self.HINT_LINES) * lh - 6
        for s in self.HINT_LINES:
            p.drawText(QPointF(x, y), s)
            y += lh

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
        return _cat_color(cat)

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
        node = self._doc.node(self._drag[1])
        if node is None:
            return
        if self._drag[0] == "link":
            s = self._to_screen(*self._output_port_w(node))
        else:   # link_rev：从本算子输入端反向拉到来源
            s = self._to_screen(*self._input_port_w(node))
        t = self._to_screen(self._link_cur.x(), self._link_cur.y())
        p.setPen(QPen(QColor("#4261FF"), 2, Qt.PenStyle.DashLine))
        p.drawLine(s, t)
        p.setBrush(QColor("#4261FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(t, 4, 4)

    def _draw_node(self, p, n):
        """按世界坐标绘制算子卡片（painter 统一 translate+scale）。

        ⚠️ 2026-10-21 需求：卡片内文字须随滚轮缩放自适应——此前几何按 s
        缩放而字体取 int(…*max(0.7, s)) 且钳 0.7 下限，缩小后字体不再变
        小、卡片继续变小，文字溢出重叠。改为在世界坐标系下绘制，文字与
        卡片等比连续缩放，任意缩放级别均贴合卡片。
        """
        p.save()
        p.translate(self._offset)
        p.scale(self._scale, self._scale)
        rect = QRectF(n["x"], n["y"], self.NODE_W, self.NODE_H)
        sel = self._selected == n["id"]
        # 卡片
        p.setPen(QPen(QColor("#4261FF" if sel else COLORS["border"]),
                      2 if sel else 1))
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.drawRoundedRect(rect, 8, 8)
        # 类别图标圆
        cc = QColor(self._cat_color(n["cat"]))
        d = 26.0
        p.setBrush(cc)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(rect.left() + 10, rect.center().y() - d / 2, d, d))
        p.setPen(QColor("#FFFFFF"))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(15)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(rect.left() + 10, rect.center().y() - d / 2, d, d),
                   Qt.AlignmentFlag.AlignCenter, _cat_badge(n["cat"]))
        # 标题 / 副标题：按可用像素宽省略号截断（替代固定字符数截断）
        tx = rect.left() + 10 + d + 8
        tw = rect.right() - tx - 8
        ft = QFont("Microsoft YaHei")
        ft.setPixelSize(16)
        ft.setBold(True)
        fmt = QFontMetrics(ft)
        p.setPen(QColor(COLORS["text_primary"]))
        p.setFont(ft)
        p.drawText(QRectF(tx, rect.top() + 8, tw, 18),
                   Qt.AlignmentFlag.AlignVCenter,
                   fmt.elidedText(n["name"], Qt.TextElideMode.ElideRight, int(tw)))
        fs = QFont("Microsoft YaHei")
        fs.setPixelSize(13)
        fms = QFontMetrics(fs)
        p.setPen(QColor(COLORS["text_secondary"]))
        p.setFont(fs)
        p.drawText(QRectF(tx, rect.top() + 30, tw, 16),
                   Qt.AlignmentFlag.AlignVCenter,
                   fms.elidedText(n["cat"], Qt.TextElideMode.ElideRight, int(tw)))
        # 耗时徽标（右上，示例）：绿色对勾（矢量绘制，不依赖字体）+ 数值
        p.setPen(QPen(QColor("#0D822B"), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cxp = rect.right() - 66
        cyp = rect.top() - 9
        p.drawLine(QPointF(cxp, cyp + 3), QPointF(cxp + 3, cyp + 6))
        p.drawLine(QPointF(cxp + 3, cyp + 6), QPointF(cxp + 8, cyp))
        fmz = QFont("Microsoft YaHei")
        fmz.setPixelSize(13)
        p.setPen(QColor("#0D822B"))
        p.setFont(fmz)
        p.drawText(QRectF(rect.right() - 54, rect.top() - 16, 54, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{n['ms']:.2f} ms")
        # 输入端（顶部圆环）/ 输出端（底部蓝点）——世界坐标，随卡片缩放
        ip = self._input_port_w(n)
        p.setPen(QPen(QColor("#8A9099"), 1.5))
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.drawEllipse(QPointF(ip[0], ip[1]), 4.5, 4.5)
        op = self._output_port_w(n)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4261FF"))
        p.drawEllipse(QPointF(op[0], op[1]), 5.5, 5.5)
        p.restore()


# ---------------------------------------------------------------------------
class _FoldArrowButton(QPushButton):
    """工具箱折叠/展开按钮：蓝底 + 白色方向箭头。

    ⚠️ 2026-10-21 需求：不用 «/» 字符（离屏/字体缺失时不可见，且方向感
    不强），改用 QPainter 现绘矢量箭头——左箭头=折叠，右箭头=展开。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir = "left"
        self.setFixedSize(22, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_direction(self, d):
        self._dir = "right" if d == "right" else "left"
        self.update()

    def direction(self):
        return self._dir

    def paintEvent(self, event):
        super().paintEvent(event)      # 先画 QSS 背景（蓝底），再画箭头
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        y = h / 2.0
        x1, x2 = w * 0.30, w * 0.72
        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if self._dir == "left":        # 向左：←
            p.drawLine(QPointF(x2, y), QPointF(x1, y))
            p.drawLine(QPointF(x1 + 3.4, y - 3.4), QPointF(x1, y))
            p.drawLine(QPointF(x1 + 3.4, y + 3.4), QPointF(x1, y))
        else:                          # 向右：→
            p.drawLine(QPointF(x1, y), QPointF(x2, y))
            p.drawLine(QPointF(x2 - 3.4, y - 3.4), QPointF(x2, y))
            p.drawLine(QPointF(x2 - 3.4, y + 3.4), QPointF(x2, y))
        p.end()


# 工具箱：搜索框 + 可折叠分类（双击算子添加到画布）
# ---------------------------------------------------------------------------
class FlowToolBox(QWidget):
    """流程算子工具箱：搜索过滤 + 分类折叠 + 双击添加 + 整栏折叠。"""

    add_requested = pyqtSignal(str, str)   # (分类, 算子名)
    collapsed_changed = pyqtSignal(bool)   # 整栏折叠状态变化（True=已折叠）

    ITEM_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 搜索行：搜索框 + 折叠按钮（按钮在搜索框右侧，收起后仅留此按钮）
        self._collapsed = False
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索算子")
        self._search.setFixedHeight(26)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refilter)
        search_row.addWidget(self._search, 1)
        # ⚠️ 2026-10-21 需求（第三次反馈）：«/» 字符方向感不强且部分环境字形
        # 缺失，改为蓝底白色矢量箭头按钮（左=折叠，右=展开）
        self._btn_fold = _FoldArrowButton()
        self._btn_fold.setToolTip("折叠算子工具箱")
        self._btn_fold.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['accent_blue']}; "
            f"border:1px solid {COLORS['accent_blue']}; "
            f"border-radius:3px;}}"
            f"QPushButton:hover{{background-color:#6B85FF; "
            f"border-color:#6B85FF;}}")
        self._btn_fold.clicked.connect(self._toggle_collapse)
        search_row.addWidget(self._btn_fold)
        v.addLayout(search_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")
        inner = QWidget()
        self._inner_lay = QVBoxLayout(inner)
        self._inner_lay.setContentsMargins(0, 0, 2, 0)
        self._inner_lay.setSpacing(2)
        self._section_rows = {}   # cat -> {header, count_lbl, items: [row, ...]}
        for cat, count in TOOLBOX_CATEGORIES:
            self._inner_lay.addWidget(self._build_section(cat, count))
        self._inner_lay.addStretch(1)
        self._scroll.setWidget(inner)
        v.addWidget(self._scroll, 1)

    def _toggle_collapse(self):
        """整栏折叠/展开：收起后仅留展开按钮窄条，画布吃满剩余宽度。

        ⚠️ 2026-10-21 需求：恢复工具箱折叠能力，按钮固定在搜索框右侧；
        收起时搜索框/分类列表一并隐藏，只保留 « / » 按钮本身。
        """
        self._collapsed = not self._collapsed
        self._btn_fold.set_direction("right" if self._collapsed else "left")
        self._btn_fold.setToolTip("展开算子工具箱" if self._collapsed
                                  else "折叠算子工具箱")
        self._search.setVisible(not self._collapsed)
        self._scroll.setVisible(not self._collapsed)
        self.collapsed_changed.emit(self._collapsed)

    def is_collapsed(self):
        return self._collapsed

    def _build_section(self, cat, count):
        # 分类整体容器：头部行 + 子项容器（子项随分类在树内向下展开）
        sec = QWidget()
        sv = QVBoxLayout(sec)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(2)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 2, 2, 2)
        hl.setSpacing(4)
        arrow = QLabel("▶")
        arrow.setFixedWidth(10)
        arrow.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:9px;")
        # 分类色块（与画布节点圆标同色，纯色块不依赖字体字形）
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(
            f"background-color:{_cat_color(cat)}; border-radius:2px;")
        name = QLabel(cat)
        name.setStyleSheet(f"color:{COLORS['text_primary']}; font-size:12px; font-weight:bold;")
        cnt = QLabel(f"{count} 项")
        cnt.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:10px;")
        # 子标签不拦截鼠标，点击整行都落在 head 上（由事件过滤器统一处理折叠）
        for child in (arrow, swatch, name, cnt):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl.addWidget(arrow)
        hl.addWidget(swatch)
        hl.addWidget(name)
        hl.addStretch(1)
        hl.addWidget(cnt)
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        head.installEventFilter(self)
        sv.addWidget(head)
        # 子项容器：⚠️ 2026-10-20 修复——此前子项行 QLabel 既没有 parent 也没有
        # 加入任何布局，点击分类 setVisible(True) 后被 Qt 当作顶层窗口，弹成
        # 一个个带系统标题栏的独立小窗。现统一放入随分类折叠的 body 容器。
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(1)
        rows = []
        for item in toolbox_items(cat, count):
            row = QLabel(f"    {item}")
            row.setFixedHeight(self.ITEM_H)
            row.setToolTip("双击添加到流程画布")
            row.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:11px;"
                f"background-color:transparent; border-radius:3px; padding-left:6px;")
            row.installEventFilter(self)
            bl.addWidget(row)
            rows.append(row)
        body.setVisible(False)
        sv.addWidget(body)
        self._section_rows[cat] = {"arrow": arrow, "rows": rows, "body": body,
                                   "count": count, "head": head,
                                   "open": False}
        return sec

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
        info["body"].setVisible(info["open"])
        for r in info["rows"]:
            r.setVisible(info["open"] and self._match(r, self._search.text()))

    @staticmethod
    def _row_text(r):
        return r.text().strip()

    def _match(self, row, text):
        return not text or text.lower() in self._row_text(row).lower()

    def _refilter(self, text):
        for cat, info in self._section_rows.items():
            open_now = info["open"] or bool(text)
            any_match = False
            for r in info["rows"]:
                m = self._match(r, text)
                r.setVisible(m and open_now)
                any_match = any_match or m
            info["head"].setVisible(any_match)
            info["body"].setVisible(open_now and any_match)
            if text:
                info["arrow"].setText("▼")
                info["open"] = True

    def categories(self):
        return [(name, count) for name, count in TOOLBOX_CATEGORIES]


# ---------------------------------------------------------------------------
# 子页面：工具箱 + 画布 + 工具栏（内嵌 / 大窗口两种宿主）
# ---------------------------------------------------------------------------
# 右侧「算法参数」子面板的示例参数模板：(名称, 默认值, 最小, 最大, 单位, 小数位)。
# 真实引擎接入时，把模板替换为按算子实际算法的参数表即可（UI 无需改动）。
SIDE_PARAM_TPL = {
    "图像源": [("曝光时间", 5000, 100, 1000000, "μs", 0),
               ("模拟增益", 6.0, 0.0, 24.0, "dB", 1)],
    "图像预处理": [("二值化阈值", 128, 0, 255, "", 0),
                  ("高斯核大小", 3, 1, 31, "px", 0)],
    "图像分割": [("分割阈值", 60, 0, 255, "", 0),
                ("最小面积", 200, 1, 100000, "px²", 0)],
    "区域处理": [("腐蚀核大小", 3, 1, 31, "px", 0),
                ("迭代次数", 1, 1, 20, "", 0)],
    "几何生成": [("采样点数", 64, 2, 1024, "", 0)],
    "模板匹配": [("匹配阈值", 70, 0, 100, "%", 0),
                ("匹配数量", 1, 1, 32, "", 0),
                ("搜索角度", 15.0, 0.0, 180.0, "°", 1)],
    "测量": [("卡尺数量", 8, 1, 64, "", 0),
             ("搜索长度", 40, 1, 500, "px", 0),
             ("边缘极性", 0, 0, 2, "（0=任意）", 0)],
    "灰度特征": [("ROI 缩放", 1.0, 0.1, 4.0, "x", 1)],
    "形状特征": [("最小面积", 100, 1, 100000, "px²", 0),
                ("最大面积", 50000, 1, 1000000, "px²", 0)],
    "轮廓处理": [("轮廓逼近精度", 1.5, 0.1, 10.0, "px", 1)],
    "结果输出": [("输出通道", 1, 1, 8, "", 0)],
    "设备通讯": [("超时时间", 200, 10, 5000, "ms", 0),
                ("重试次数", 3, 0, 20, "", 0)],
    "流程逻辑": [("循环次数", 1, 1, 100, "", 0)],
}
SIDE_PARAM_DEFAULT = [("执行使能", 1, 0, 1, "", 0),
                      ("超时时间", 200, 10, 5000, "ms", 0),
                      ("匹配阈值", 70, 0, 100, "%", 0)]

# 右侧「算法耗时」子面板的耗时分解模板：(阶段名, 占比)。总耗时取节点真实 ms 值。
SIDE_TIME_STAGES = [("图像采集", 0.20), ("预处理", 0.15),
                    ("核心计算", 0.50), ("结果输出", 0.15)]

# 浮窗：宽度 280；高度默认 = 上限 FLOAT_MAX_H，且不超出所在画布；
# 内容超出窗口高度时由滚动条翻页。
FLOAT_W = 280
FLOAT_MAX_H = 280      # 默认高度 = 上限（2026-10-21 需求：约 280px）
FLOAT_MIN_H = 120
# 浮窗内容区滚动条样式（两个浮窗共用）
FLOAT_SCROLL_CSS = (
    "QScrollArea{border:none; background:transparent;}"
    "QScrollBar:vertical{background:transparent; width:6px; margin:0;}"
    "QScrollBar::handle:vertical{background:%s; border-radius:3px; min-height:24px;}"
    "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
    "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
    % COLORS['border'])


def _float_y_range(panel):
    """浮窗可停留的 y 区间：完整落在画布内即可（不按上/下半区限制）。

    浮窗高度上限 FLOAT_MAX_H（280），在放大编辑窗口 / 内嵌卡片中都可能
    超过画布半高，故不再按半区限制，改为保证窗口完整可见；上/下半区的
    视觉分隔由分隔线与蓝窗底边对齐（_sync_divider）承担。
    """
    par = panel.parentWidget()
    if par is None:
        return 0, 0
    return 0, max(0, par.height() - panel.height())


class _FloatDragHandler(QObject):
    """浮窗标题栏拖拽处理器（独立 QObject 事件过滤器，Qt 标准做法）。

    ⚠️ 经验教训（2026-10-20）：事件过滤器内抛出任何异常（哪怕是枚举名
    笔误的 AttributeError）都会让 PyQt 对整个进程 qFatal（退出码
    0xC0000409、无 Python 回溯），表现为『构造界面时莫名硬崩溃』。
    过滤器内务必只做安全操作，或用 try/except 兜底。
    """

    def __init__(self, panel, on_move=None):
        super().__init__(panel)
        self._panel = panel
        self._on_move = on_move      # 拖动后的联动回调（如分隔线对齐）
        self._off = None

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonPress:
            gp = QCursor.pos()
            self._off = gp - self._panel.mapToGlobal(QPoint(0, 0))
            self._panel.raise_()
            return True
        if t == QEvent.Type.MouseButtonRelease:
            self._off = None
            return True
        if t == QEvent.Type.MouseMove and self._off is not None:
            par = self._panel.parentWidget()
            if par is not None:
                gp = QCursor.pos() - self._off - par.mapToGlobal(QPoint(0, 0))
                lo, hi = _float_y_range(self._panel)
                self._panel.move(
                    max(0, min(gp.x(), max(0, par.width() - self._panel.width()))),
                    max(lo, min(gp.y(), hi)))
                if self._on_move is not None:
                    # ⚠️ 过滤器内严禁让异常逃逸（qFatal 硬崩溃，见类注释）
                    try:
                        self._on_move(self._panel)
                    except Exception:
                        pass
            return True
        return False


class _ThumbLabel(QLabel):
    """图像源缩略图：可点选，点击回调 on_pick(idx)。"""

    def __init__(self, idx, on_pick):
        super().__init__()
        self._idx = idx
        self._on_pick = on_pick
        self.setFixedSize(96, 72)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, ev):
        self._on_pick(self._idx)


class FlowDesignPage(QWidget):
    """检测流程设计页（内嵌于卡片标签页，或被「放大编辑」大窗口承载）。"""

    def __init__(self, parent=None, document=None, run_log=None, embedded=True,
                 camera_names=None, current_camera=None, image_display_cb=None):
        super().__init__(parent)
        self._run_log = run_log
        # 物理相机列表（用于图像源算子的「相机列表」候选）与当前调试界面相机
        # （自动关联/绑定）。由宿主调试界面传入；独立运行时为空。
        self._camera_names = list(camera_names or [])
        self._current_camera = current_camera
        # ⚠️ 2026-10-21 需求：流程执行时把当前图片同步到调试界面相机画布的回调
        self._image_display_cb = image_display_cb
        self._embedded = embedded
        self._dlg = None
        self._side_mode = None    # 蓝窗当前模式：None / "params" / "timing"
        self.document = document or FlowDocument()
        self.document.changed.connect(self._on_doc_changed)
        # 文档变更 → 重新评估缩略图条（内嵌页与放大编辑窗同步跟随：
        # 虚拟相机+已加载图片即显示，与是否选中该算子无关）
        self.document.changed.connect(self._refresh_img_strip)
        # 全局选中变化 → 触发一次评估（同上）
        self.document.sel_changed.connect(self._on_global_sel_changed)
        self._build_ui()
        self._seed_demo()

    def minimumSizeHint(self):
        # 嵌入调试页 QTabWidget 时，不把自身最小尺寸传导给外层卡片：
        # 实测会把标签卡最小宽从 564 撑到 908，进而挤压左侧相机卡片区、
        # 改变整行卡片间距（用户反馈：卡片间隙不合理）。置 0 后卡片布局
        # 与各卡尺寸恢复到加入「检测流程设计」之前的样式；本页在窄卡片中
        # 的拥挤由可折叠工具箱 / 画布缩放 / 「放大编辑」大窗口消化。
        return QSize(0, 0)

    def sizeHint(self):
        return QSize(0, 0)

    # ---- UI ----
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(6)

        # 工具栏：提示语 + 视图操作
        bar = QHBoxLayout()
        bar.setSpacing(4)
        hint = QLabel("插入算子：双击左侧工具箱项；左键从算子输出/输入圆点拖出建立连线；"
                      "右键拖动算子位置，右键单击弹菜单（删除算子 / 前-后置连线）；"
                      "滚轮缩放画布（Shift+滚轮平移）")
        hint.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        bar.addWidget(hint)
        bar.addStretch(1)

        def _tbtn(kind, tip, cb, color="#4261FF"):
            b = QPushButton()
            b.setFixedSize(26, 24)
            b.setIcon(_make_icon(kind, color))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background-color:{COLORS['bg_panel']}; color:{COLORS['text_primary']}; "
                f"border:1px solid {COLORS['border']}; border-radius:4px;}}"
                f"QPushButton:hover{{background-color:{COLORS['border']};}}")
            b.clicked.connect(cb)
            bar.addWidget(b)
            return b

        self._btn_undo = _tbtn("undo", "撤销 (Ctrl+Z)", self.document.undo)
        self._btn_redo = _tbtn("redo", "重做 (Ctrl+Y)", self.document.redo)
        self._btn_zoom_out = _tbtn("zoom_out", "缩小", lambda: self.canvas.zoom_out())
        self._btn_fit = _tbtn("fit", "适应画布", lambda: self.canvas.fit())
        self._btn_zoom_in = _tbtn("zoom_in", "放大", lambda: self.canvas.zoom_in())
        self._btn_layout = _tbtn("layout", "自动布局", self._auto_layout)
        if self._embedded:
            self._btn_expand = _tbtn("expand", "放大编辑（弹出大窗口）",
                                     self._open_dialog, color="white")
            self._btn_expand.setStyleSheet(
                f"QPushButton{{background-color:{COLORS['accent_blue']}; color:white; "
                f"border:none; border-radius:4px;}}"
                f"QPushButton:hover{{background-color:#5570ff;}}")
        v.addLayout(bar)

        # 主体：工具箱（可折叠）+ 画布
        body = QHBoxLayout()
        body.setSpacing(6)
        self.toolbox = FlowToolBox()
        self.toolbox.add_requested.connect(self._on_tool_add)
        # 折叠联动：收起时整栏缩成 30px 窄条（仅展开按钮），展开时恢复
        self.toolbox.collapsed_changed.connect(self._on_toolbox_collapsed)
        self._toolbox_holder = QWidget()
        tv = QVBoxLayout(self._toolbox_holder)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.toolbox)
        # 2026-10-21 需求：工具箱整栏宽度自适应收窄一些（原 170 → 152，
        # 搜索框占满减去右侧折叠按钮）
        self._toolbox_holder.setFixedWidth(152)
        body.addWidget(self._toolbox_holder)

        self.canvas = FlowCanvas()
        self.canvas.set_document(self.document)
        body.addWidget(self.canvas, 1)
        # 选中节点变化时，若右侧浮窗已展开则实时刷新内容
        self.canvas.selection_changed.connect(self._on_selection_changed)
        # 画布尺寸变化时把浮窗夹取回可视范围
        self.canvas.canvas_resized.connect(self._clamp_float_panels)

        # 右侧浮窗（以画布为父控件，悬浮于画布之上，可并存）：
        # - 蓝窗：算法参数 / 算法耗时（两模式共用一窗，随竖向按钮切换）
        # - 黄窗：输入输出设置
        # 内容区由 _refresh_* 动态重建；窗口高度默认/上限 FLOAT_MAX_H
        # （不超出画布），内容超出时由滚动条翻页
        self._float_algo = self._make_float_panel("算法参数", "#4261FF",
                                                  self._close_side_panel,
                                                  side="top")
        self._side_body = self._make_float_body(self._float_algo)
        self._float_algo.setFixedSize(FLOAT_W, FLOAT_MAX_H)

        self._float_io = self._make_float_panel("输入输出设置", "#E8A33D",
                                                self._toggle_io_panel,
                                                side="bottom")
        self._io_body = self._make_float_body(self._float_io)
        self._float_io.setFixedSize(FLOAT_W, FLOAT_MAX_H)
        self._float_algo.hide()
        self._float_io.hide()

        # 最右侧竖向工具条（自上而下）：算法参数 / 算法耗时 ‖（分隔线）‖ 输入输出
        self._side_tools = QWidget()
        self._side_tools.setFixedWidth(40)
        self._st = QVBoxLayout(self._side_tools)
        self._st.setContentsMargins(2, 6, 2, 6)
        self._st.setSpacing(8)
        self._btn_params = self._make_side_btn("算法参数", "params")
        self._btn_params.clicked.connect(lambda: self._toggle_side_panel("params"))
        self._btn_timing = self._make_side_btn("算法耗时", "timing")
        self._btn_timing.clicked.connect(lambda: self._toggle_side_panel("timing"))
        self._st.addWidget(self._btn_params)
        self._st.addWidget(self._btn_timing)
        # 可变占位：把分隔线顶到上半区浮窗底边（见 _sync_divider），
        # 其后的按钮随之下移，故分割线以下工具位置自动跟随。
        self._divider_spacer = QWidget()
        self._divider_spacer.setFixedHeight(0)
        self._st.addWidget(self._divider_spacer)
        divider = QFrame()
        divider.setFixedHeight(2)
        divider.setStyleSheet(f"background-color:{COLORS['accent_orange']};")
        self._st.addWidget(divider)
        self._divider = divider
        self._btn_io = self._make_side_btn("输入输出", "io",
                                           checked_bg=COLORS['accent_orange'])
        self._btn_io.clicked.connect(self._toggle_io_panel)
        self._st.addWidget(self._btn_io)
        self._st.addStretch(1)
        body.addWidget(self._side_tools)
        v.addLayout(body, 1)

        # ⚠️ 2026-10-21 需求：图像源（虚拟相机）加载图片后的缩略图条——
        # 位于画布底部整行，仅当「选中图像源算子 + 图像源=虚拟相机 + 已加载
        # 图片」时出现；上方为 第1张/上1张/下1张/最后1张/执行所有 按钮，
        # 下方为图片缩略图（横向滚动，可点选当前图）。
        self._img_strip = self._make_img_strip()
        v.addWidget(self._img_strip)
        self._img_strip.hide()
        # 按当前文档状态初始化缩略图条（避免后开「放大编辑」窗时遗漏已有
        # 的虚拟相机+已加载图片状态）：虚拟相机且已加载即显示，与选中无关。
        self._refresh_img_strip()
        self._fitted = False

    # ---- 图像源缩略图条（虚拟相机加载图片后出现在画布底部） ----
    def _make_img_strip(self):
        w = QWidget()
        w.setStyleSheet(
            f"QWidget{{background-color:{COLORS['bg_panel']}; "
            f"border-top:1px solid {COLORS['border']};}}")
        h = QVBoxLayout(w)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(4)
        self._img_files = []   # 当前缩略图文件列表（同步自选中图像源节点）
        self._img_cur = 0      # 当前选中索引
        btns = QHBoxLayout()
        btns.setSpacing(4)

        def _btn(txt, cb):
            b = QPushButton(txt)
            b.setFixedHeight(22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background-color:{COLORS['bg_card']}; "
                f"color:{COLORS['text_primary']}; border:1px solid {COLORS['border']}; "
                f"border-radius:3px; font-size:11px; padding:0 8px;}}"
                f"QPushButton:hover{{background-color:{COLORS['border']};}}")
            b.clicked.connect(cb)
            btns.addWidget(b)

        _btn("第1张", lambda: self._img_nav("first"))
        _btn("上1张", lambda: self._img_nav("prev"))
        _btn("下1张", lambda: self._img_nav("next"))
        _btn("最后1张", lambda: self._img_nav("last"))
        _btn("执行所有", self._img_run_all)
        btns.addStretch(1)
        h.addLayout(btns)

        self._thumb_scroll = QScrollArea()
        self._thumb_scroll.setWidgetResizable(True)
        self._thumb_scroll.setFixedHeight(84)
        self._thumb_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._thumb_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thumb_scroll.setStyleSheet(
            f"QScrollArea{{border:1px solid {COLORS['border']}; "
            f"border-radius:4px; background-color:{COLORS['bg_dark']};}}")
        holder = QWidget()
        holder.setStyleSheet("background-color:transparent;")
        self._thumb_lay = QHBoxLayout(holder)
        self._thumb_lay.setContentsMargins(2, 2, 2, 2)
        self._thumb_lay.setSpacing(4)
        self._thumb_scroll.setWidget(holder)
        h.addWidget(self._thumb_scroll)
        return w

    def _on_global_sel_changed(self, _nid):
        """全局选中变化（任一窗口选中算子）：触发一次缩略图条评估。"""
        if getattr(self, "_img_strip", None) is not None:
            self._refresh_img_strip()

    def _refresh_img_strip(self):
        """⚠️ 2026-10-21 需求：缩略图条跟随文档中**图像源算子**的状态——
        只要该算子是「虚拟相机」且已加载图片，就一直显示；与当前是否选中
        该算子无关（切到其它算子/取消选中也不隐藏）。多图像源时取第一个
        虚拟相机且已加载的节点。

        通过文档 changed 信号驱动（加载图片/切换物理-虚拟均会走到），
        内嵌页与放大编辑窗保持同步；用文件集合签名避免执行流程时反复重建。"""
        if getattr(self, "_img_strip", None) is None:
            return
        files = []
        for n in self.document.nodes():
            if n.get("cat") == "图像源":
                st = n.get("img_src") or {}
                if st.get("type") == "虚拟相机":
                    files = list(st.get("files") or [])
                    if files:
                        break
        if files != self._img_files:
            self._img_files = files
            self._img_cur = 0 if not files else min(
                self._img_cur, len(files) - 1)
            self._rebuild_img_thumbs()
        self._img_strip.setVisible(bool(files))

    def _rebuild_img_thumbs(self):
        self._clear_layout(self._thumb_lay)
        for i, f in enumerate(self._img_files):
            lab = _ThumbLabel(i, self._img_pick)
            pm = QPixmap(f)
            if not pm.isNull():
                lab.setPixmap(pm.scaledToHeight(
                    72, Qt.TransformationMode.SmoothTransformation))
            else:
                lab.setText(os.path.basename(f))
            self._thumb_lay.addWidget(lab)
        self._thumb_lay.addStretch(1)
        self._highlight_thumbs()

    def _highlight_thumbs(self):
        for i in range(self._thumb_lay.count()):
            wdg = self._thumb_lay.itemAt(i).widget()
            if isinstance(wdg, _ThumbLabel):
                cur = (i == self._img_cur)
                wdg.setStyleSheet(
                    f"QLabel{{background-color:{COLORS['bg_card']}; "
                    f"border:{'2px solid #4261FF' if cur else '1px solid ' + COLORS['border']}; "
                    f"border-radius:3px; color:{COLORS['text_secondary']}; font-size:10px;}}")

    def _img_pick(self, idx):
        self._img_cur = idx
        self._highlight_thumbs()
        self._log(f"图像源：选中第 {idx + 1}/{len(self._img_files)} 张 - "
                  f"{os.path.basename(self._img_files[idx])}")

    def _img_nav(self, mode):
        if not self._img_files:
            return
        n = len(self._img_files)
        if mode == "first":
            self._img_cur = 0
        elif mode == "last":
            self._img_cur = n - 1
        elif mode == "prev":
            self._img_cur = (self._img_cur - 1) % n
        elif mode == "next":
            self._img_cur = (self._img_cur + 1) % n
        self._highlight_thumbs()
        # ⚠️ 2026-10-21 需求：上1张/下1张（含第1张/最后1张）切换即执行
        # 算法流程（从图像源起，受「运行到当前节点」限制），并同步相机画布
        self._exec_pipeline(self._img_files[self._img_cur])

    def _img_run_all(self):
        """执行所有：从缩略图第1张到最后一张逐张执行（每张刷新一次相机画布）。"""
        if not self._img_files:
            return
        self._run_all_idx = 0
        if getattr(self, "_run_all_timer", None) is None:
            self._run_all_timer = QTimer(self)
            self._run_all_timer.timeout.connect(self._run_all_step)
        self._run_all_timer.start(350)
        self._run_all_step()

    def _run_all_step(self):
        if getattr(self, "_run_all_idx", 0) >= len(self._img_files):
            self._run_all_timer.stop()
            self._log(f"图像源：执行所有完成（共 {len(self._img_files)} 张）")
            return
        i = self._run_all_idx
        self._img_cur = i
        self._highlight_thumbs()
        self._exec_pipeline(self._img_files[i])
        self._run_all_idx += 1

    def _exec_pipeline(self, img_path):
        """执行算法流程：从图像源算子起沿连线向下游依次执行；
        设了「运行到当前节点」则只运行到该算子（含）即结束。

        每个算子刷新示例耗时 → 画布 ✔ ms 徽标（性能展示位）实时更新；
        图片同步刷新到调试界面相机画布（主画布 + R/G/B 通道）。"""
        doc = self.document
        # ⚠️ 2026-10-21 需求：执行流程不依赖当前选中算子——找文档中
        # 「虚拟相机 + 已加载图片」的图像源节点作为流程起点。
        src = None
        for n in doc.nodes():
            if n.get("cat") == "图像源":
                st = n.get("img_src") or {}
                if st.get("type") == "虚拟相机" and st.get("files"):
                    src = n
                    break
        if src is None:
            return
        # 沿连线收集下游执行序列（按连线顺序，防环）
        order = [src["id"]]
        while True:
            nxts = [e["dst"] for e in doc.edges() if e["src"] == order[-1]
                    and e["dst"] not in order]
            if not nxts:
                break
            order.append(nxts[0])
        stop = doc.run_until()
        if stop in order:
            order = order[:order.index(stop) + 1]
        if img_path:
            self._log(f"执行流程：{os.path.basename(img_path)}"
                      + (f"（运行到：{doc.node(stop)['name']}）" if stop in order else ""))
        for i, nid in enumerate(order):
            nd = doc.node(nid)
            ms = round(1.5 + (sum(map(ord, nd["name"])) % 130) / 9.0
                       + len(order) * 0.37, 2)   # 示例耗时（随图片轮换变化）
            doc.set_ms(nid, ms)
            self._log(f"  {i + 1}. {nd['name']}：{ms:.2f} ms")
        # 图片同步到调试界面相机画布
        if self._image_display_cb is not None and img_path:
            self._image_display_cb(img_path)

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

    def _on_toolbox_collapsed(self, collapsed):
        """工具箱整栏折叠联动：收起缩成窄条（仅留展开按钮），展开恢复宽度。"""
        self._toolbox_holder.setFixedWidth(30 if collapsed else 152)


    def _auto_layout(self):
        self.document.auto_layout()
        self.canvas.fit()
        self._log("流程设计：已自动布局")

    def _on_doc_changed(self):
        self._btn_undo.setEnabled(self.document.can_undo())
        self._btn_redo.setEnabled(self.document.can_redo())
        # 算法耗时浮窗开启时，各算子 ms 变化（执行流程）需实时刷新列表
        if self._side_mode == "timing" and self._float_algo.isVisible():
            self._refresh_side_panel()

    # ---- 右侧竖向工具条与浮窗 ----
    def _make_side_btn(self, text, icon_kind, checked_bg=None):
        """竖向工具条按钮：图标 + 悬浮提示，可勾选表示浮窗展开态。"""
        cb = checked_bg or COLORS['accent_blue']
        b = QPushButton()
        b.setIcon(_make_icon(icon_kind, COLORS['text_secondary']))
        b.setIconSize(QSize(18, 18))
        b.setFixedSize(34, 34)
        b.setCheckable(True)
        b.setToolTip(f"{text}（点击在画布上展开 / 收起浮窗）")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['bg_panel']}; "
            f"color:{COLORS['text_secondary']}; border:1px solid {COLORS['border']}; "
            f"border-radius:4px;}}"
            f"QPushButton:hover{{color:{COLORS['text_primary']};}}"
            f"QPushButton:checked{{background-color:{cb}; "
            f"color:white; border-color:{cb};}}")
        return b

    def _make_float_panel(self, title, border_color, on_close, side="top"):
        """以画布为父控件的浮窗（悬浮于画布之上）：标题栏可拖动、右上可关闭。

        side="top" 归属分割线以上（画布上半区），"bottom" 归属分割线以下（下半区）。
        """
        panel = QFrame(self.canvas)
        panel.setObjectName("floatPanel")
        panel.setStyleSheet(
            f"QFrame#floatPanel{{background-color:{COLORS['bg_panel']}; "
            f"border:1px solid {border_color}; border-radius:6px;}}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(8)
        # 默认约束会把布局的最小尺寸反向设给浮窗，使内容变高时 setFixedHeight
        # 的上限失效（实测被撑回 200+）；这里解除该约束，超高内容交给滚动条。
        v.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        head = QHBoxLayout()
        head.setSpacing(6)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color:{COLORS['text_primary']}; font-size:12px; font-weight:bold; border:none;")
        title_lbl.setToolTip("按住标题可拖动浮窗")
        # 标题栏拖拽：独立 QObject 过滤器（勿用页面实例，见 _FloatDragHandler 注释）
        # 拖动全程联动：分隔线对齐蓝窗底边；蓝窗移动时黄窗跟随（见 _on_float_moved）
        drag = _FloatDragHandler(panel, on_move=self._on_float_moved)
        title_lbl.installEventFilter(drag)
        panel._drag_handler = drag     # 持有引用，防止被 GC
        close = QPushButton("×")
        close.setFixedSize(20, 20)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("收起浮窗")
        close.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['bg_card']}; color:{COLORS['text_secondary']}; "
            f"border:1px solid {COLORS['border']}; border-radius:4px; font-size:12px;}}"
            f"QPushButton:hover{{color:{COLORS['text_primary']};}}")
        close.clicked.connect(on_close)
        head.addWidget(title_lbl)
        head.addStretch(1)
        head.addWidget(close)
        v.addLayout(head)
        panel._title_lbl = title_lbl
        panel._border_color = border_color
        panel._side = side
        return panel

    def _make_float_body(self, panel):
        """浮窗内容区：套一层可滚动容器，内容超高时由滚动条翻页。

        返回内容布局（供 _refresh_* 动态重建内容）。
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        scroll.setStyleSheet(FLOAT_SCROLL_CSS)
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 2, 0)
        lay.setSpacing(6)
        scroll.setWidget(holder)
        panel.layout().addWidget(scroll, 1)
        panel._scroll = scroll
        panel._content_holder = holder
        return lay

    def _fit_float_height(self, panel):
        """浮窗高度：默认 = 上限 FLOAT_MAX_H，且不超出所在画布。

        内容不足时窗口保持该高度（内容顶对齐）；内容超出时由内容区
        滚动条翻页（widgetResizable 的 QScrollArea 自动撑开 + 滚动）。
        """
        par = panel.parentWidget()
        cap = FLOAT_MAX_H
        if par is not None:
            cap = min(cap, max(FLOAT_MIN_H, par.height() - 24))
        panel.setFixedHeight(cap)

    def _place_float(self, panel):
        """蓝窗贴顶；黄窗默认贴底，蓝窗同开时紧挨其下方（留 8px 间隙）。

        ⚠️ 2026-10-21 需求：两窗同开时间隙不能过大——黄窗顶边贴住分隔线
        （= 蓝窗底边）下方 8px；画布剩余高度放不下黄窗时退回贴底。
        """
        par = panel.parentWidget()
        m = 12
        lo, hi = _float_y_range(panel)
        x = max(0, par.width() - panel.width() - m)
        if panel._side == "bottom":
            y = max(lo, min(hi, par.height() - panel.height() - m))
            # 黄窗始终紧挨「分隔线」下方：蓝窗展开时分隔线=蓝窗底+6，
            # 仅黄窗展开时分隔线=基准位（顶部工具组下方）——两种情况下黄窗都
            # 贴在分隔线下方 8px（而非贴画布底部）。画布放不下时回退贴底。
            algo = getattr(self, "_float_algo", None)
            if (algo is not None and algo is not panel and algo.isVisible()
                    and par is algo.parentWidget()):
                ref = algo.y() + algo.height()
            else:
                ref = self._divider_canvas_y()
            below = ref + 8
            if below + panel.height() <= par.height():
                y = below
        else:
            y = lo + m
        panel.move(x, max(lo, min(y, hi)))
        panel.raise_()

    def _divider_canvas_y(self):
        """分隔线在画布坐标系中的 y（供黄窗紧贴其下方定位）。"""
        st = self._st
        base = (st.contentsMargins().top() + self._btn_params.height()
                + self._btn_timing.height() + st.spacing() * 3)
        local = base + self._divider_spacer.height()
        page_y = self._side_tools.mapTo(self, QPoint(0, local)).y()
        return page_y - self.canvas.mapTo(self, QPoint(0, 0)).y()

    def _on_float_moved(self, panel):
        """浮窗拖动/重定位联动：分隔线对齐蓝窗底边；蓝窗移动时黄窗跟随。

        ⚠️ 只在蓝窗移动时吸附黄窗——用户拖黄窗本身时不打断（否则黄窗
        无法被拖离蓝窗下方）。
        """
        self._sync_divider()
        io = getattr(self, "_float_io", None)
        if (panel is getattr(self, "_float_algo", None) and io is not None
                and io.isVisible()):
            self._place_float(io)

    def _clamp_float_panels(self):
        """画布尺寸变化：浮窗保留原位，但夹取回所属分区与画布范围内。"""
        for p in (self._float_algo, self._float_io):
            par = p.parentWidget()
            if p.isVisible() and par is not None:
                lo, hi = _float_y_range(p)
                p.move(max(0, min(p.x(), max(0, par.width() - p.width()))),
                       max(lo, min(p.y(), hi)))
        self._sync_divider()

    def _sync_divider(self):
        """分隔线高度位置自适应：与上半区（算法类）浮窗底边对齐。

        未展开算法类浮窗时回到默认位置；分隔线以下的工具按钮排在占位之后，
        会随分隔线一起下移。下半区（输入输出）浮窗不参与分隔线定位。

        ⚠️ 页面刚切显 / 弹窗首开时布局仍在收敛（工具栏高度未定），一次性
        计算会把错位值写死（实测分隔线停在距窗底 40+px 处）。故这里幂等：
        目标未变化直接返回；变化则写入并排一次事件循环后按最终几何复算，
        直到收敛，保证分隔线真正贴住浮窗底边。
        """
        st = self._st
        base = (st.contentsMargins().top() + self._btn_params.height()
                + self._btn_timing.height() + st.spacing() * 3)
        if self._float_algo.isVisible():
            bottom = self._float_algo.y() + self._float_algo.height()
            # ⚠️ QWidget.mapTo 的参数必须是本控件的「祖先」，传兄弟控件得到的是
            # 未定义值（实测偏差 40+px，分隔线因此被夹在极限位）。这里把画布与
            # 工具条各自映射到页面坐标系再作差，才是真正的相对偏移。
            bottom_abs = self.canvas.mapTo(self, QPoint(0, bottom)).y()
            tools_top = self._side_tools.mapTo(self, QPoint(0, 0)).y()
            target = bottom_abs - tools_top + 6
            # 保证下方按钮仍完整可见
            limit = (self._side_tools.height() - self._btn_io.height()
                     - st.spacing() * 2 - st.contentsMargins().bottom())
            target = max(base, min(target, max(base, limit)))
        else:
            target = base
        gap = max(0, target - base)
        if self._divider_spacer.height() == gap:
            return
        self._divider_spacer.setFixedHeight(gap)
        QTimer.singleShot(0, self._sync_divider)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_divider)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_divider()

    def _toggle_side_panel(self, mode):
        """算法参数 / 算法耗时（蓝窗）：同模式再点收起，另一模式切换内容。"""
        if self._side_mode == mode and self._float_algo.isVisible():
            self._close_side_panel()
            return
        self._side_mode = mode
        self._btn_params.setChecked(mode == "params")
        self._btn_timing.setChecked(mode == "timing")
        self._refresh_side_panel()
        self._float_algo.show()
        self._fit_float_height(self._float_algo)   # 高度 = FLOAT_MAX_H（不超画布）
        self._place_float(self._float_algo)
        self._sync_divider()
        if self._float_io.isVisible():
            self._place_float(self._float_io)      # 黄窗紧挨蓝窗下方

    def _close_side_panel(self):
        self._side_mode = None
        self._btn_params.setChecked(False)
        self._btn_timing.setChecked(False)
        self._float_algo.hide()
        self._sync_divider()
        if self._float_io.isVisible():
            # ⚠️ 2026-10-21 需求：收起蓝窗后黄窗要自适应回位（贴底），
            # 否则停留在「紧挨蓝窗」的半空位置
            self._place_float(self._float_io)

    def _toggle_io_panel(self):
        """输入输出设置（黄窗）：与蓝窗相互独立、可并存显示。"""
        if self._float_io.isVisible():
            self._btn_io.setChecked(False)
            self._float_io.hide()
            return
        self._refresh_io_panel()
        self._float_io.show()
        self._btn_io.setChecked(True)
        self._fit_float_height(self._float_io)     # 高度 = FLOAT_MAX_H（不超画布）
        self._place_float(self._float_io)

    def _on_selection_changed(self, _nid):
        """画布选中节点变化：已展开的浮窗实时跟随刷新（高度同步自适应）。"""
        self._refresh_img_strip()   # 缩略图条跟随选中图像源节点显隐
        if self._float_algo.isVisible():
            self._refresh_side_panel()
            self._fit_float_height(self._float_algo)
            self._place_float(self._float_algo)
            self._sync_divider()
        if self._float_io.isVisible():
            self._refresh_io_panel()
            self._fit_float_height(self._float_io)
            self._place_float(self._float_io)

    def _clear_layout(self, lay):
        """清空布局：递归处理子部件与子布局。

        ⚠️ 2026-10-20 修复：参数/耗时行是以 QHBoxLayout（addLayout）加入的，
        旧实现只 deleteLater 顶层 widget（其实一个都没有），子布局里的旧行
        被移出布局后仍留在面板上、保持原几何位置可见 → 与新内容叠加显示
        （即截图里『搜索长度』行插在耗时行中间的根因）。现递归清空并立即
        隐藏所有旧部件。
        """
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            sub = it.layout()
            if sub is not None:
                self._clear_layout(sub)

    def _side_row_label(self, text, color=None, bold=False, size=11):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            f"color:{color or COLORS['text_primary']}; font-size:{size}px; "
            f"{'font-weight:bold;' if bold else ''} border:none;")
        return lab

    def _refresh_side_panel(self):
        """按当前模式重建蓝窗（算法参数/算法耗时）内容。

        ⚠️ 2026-10-21 需求：算法耗时浮窗展示流程中**全部算子**的耗时，
        不依赖当前选中算子；选中某算子时其所在行高亮（不同底色/文字色）。
        仅「算法参数」模式需要选中算子（否则提示先选中）。"""
        self._clear_layout(self._side_body)
        is_params = (self._side_mode == "params")
        mode_name = "算法参数" if is_params else "算法耗时"
        if is_params:
            node = self.canvas.selected_node()
            if node is None:
                self._float_algo._title_lbl.setText(mode_name)
                self._side_body.addWidget(self._side_row_label(
                    "请先在画布中选中一个算子节点\n（单击节点边框，选中后呈蓝色描边）",
                    COLORS['text_secondary']))
                self._side_body.addStretch(1)
                return
            self._float_algo._title_lbl.setText(f"{mode_name} · {node['name']}")
            # 节点基本信息行
            info = self._side_row_label(
                f"算子：{node['name']}    分类：{node['cat']}",
                COLORS['text_secondary'])
            self._side_body.addWidget(info)
            # 分页 table：第 1 页基础设置，第 2 页该算子的具体算法参数
            self._side_body.addWidget(self._build_params_tabs(node), 1)
        else:
            # 算法耗时：流程中所有算子的耗时列表（不依赖选中）；选中行高亮
            self._float_algo._title_lbl.setText(mode_name)
            nodes = self.document.nodes()
            total = sum(float(n.get("ms", 0.0)) for n in nodes)
            big = self._side_row_label(f"流程总耗时  {total:.2f} ms",
                                       "#22A94E", bold=True, size=14)
            self._side_body.addWidget(big)
            self._side_body.addWidget(self._side_row_label(
                "各算子耗时（选中算子高亮）：", COLORS['text_secondary'], size=11))
            sel = getattr(self.document, "sel_nid", None)
            for n in nodes:
                self._side_body.addWidget(
                    self._make_node_time_row(n, n.get("id") == sel))
            tip = self._side_row_label(
                "耗时为设备运行该算子的统计示例值；接入真实引擎后按实测耗时展示。",
                COLORS['text_secondary'], size=10)
            self._side_body.addWidget(tip)
        self._side_body.addStretch(1)

    def _make_node_time_row(self, node, highlight):
        """算法耗时浮窗中的单个算子耗时行（带整行高亮容器）。

        highlight=True（当前选中算子）：整行浅蓝底色 + 名称/数值高亮色。"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)
        name = self._side_row_label(
            node["name"],
            COLORS['accent_blue'] if highlight else COLORS['text_primary'],
            size=11)
        ms = float(node.get("ms", 0.0))
        val = self._side_row_label(
            f"{ms:.2f} ms",
            "#22A94E" if highlight else COLORS['text_secondary'],
            size=11, bold=highlight)
        h.addWidget(name, 1)
        h.addWidget(val)
        if highlight:
            w.setStyleSheet(
                f"background-color:{COLORS['accent_blue']}22; "
                f"border-radius:3px; border:1px solid {COLORS['accent_blue']}55;")
        return w

    def _make_param_row(self, name, val, lo, hi, unit, dec):
        """参数行：名称 + 数值输入框（带单位），返回布局供加入面板。"""
        h = QHBoxLayout()
        h.setSpacing(6)
        lab = self._side_row_label(name)
        lab.setMinimumWidth(72)
        h.addWidget(lab)
        sp = QDoubleSpinBox()
        sp.setDecimals(dec)
        sp.setRange(float(lo), float(hi))
        sp.setValue(float(val))
        sp.setSuffix(f" {unit}" if unit else "")
        sp.setFixedHeight(22)
        sp.setStyleSheet(
            f"QDoubleSpinBox{{background-color:{COLORS['bg_card']}; "
            f"color:{COLORS['text_primary']}; border:1px solid {COLORS['border']}; "
            f"border-radius:3px; font-size:11px; padding:0 4px;}}"
            f"QDoubleSpinBox::up-button,QDoubleSpinBox::down-button{{width:14px;}}")
        h.addWidget(sp, 1)
        return h

    def _build_params_tabs(self, node):
        """算法参数（蓝窗）分页内容：第 1 页基础设置，第 2 页算法参数。

        ⚠️ 2026-10-21 需求：参考视觉工具窗——首页从上到下为「工具名称 /
        定位器 / 图片输入 / 执行条件」，选择项为流程中其它算子的输出
        （图像 / 坐标系 / 结论 OK-NG）；最底一行图标依次为：ROI 显示/隐藏、
        结果显示/隐藏、使用全图 ROI、ROI 编辑、算法输出配置、显示配置。
        每个算子首页结构一致；第 2 页为该算子的具体算法参数。
        """
        _combo_ss = (
            f"QComboBox{{background-color:{COLORS['bg_card']}; "
            f"color:{COLORS['text_primary']}; border:1px solid {COLORS['border']}; "
            f"border-radius:3px; font-size:11px; padding:0 4px;}}"
            f"QComboBox::drop-down{{border:none; width:16px;}}"
            f"QComboBox QAbstractItemView{{background-color:{COLORS['bg_card']}; "
            f"color:{COLORS['text_primary']}; selection-background-color:"
            f"{COLORS['accent_blue']};}}")
        _edit_ss = (
            f"QLineEdit{{background-color:{COLORS['bg_card']}; "
            f"color:{COLORS['text_primary']}; border:1px solid {COLORS['border']}; "
            f"border-radius:3px; font-size:11px; padding:0 4px;}}")
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {COLORS['border']}; "
            f"border-radius:4px; top:-1px;}}"
            f"QTabBar::tab{{background:transparent; "
            f"color:{COLORS['text_secondary']}; padding:5px 14px; font-size:12px;}}"
            f"QTabBar::tab:selected{{color:{COLORS['text_primary']}; "
            f"border-bottom:2px solid {COLORS['accent_blue']};}}")
        others = [n for n in self.document.nodes() if n["id"] != node["id"]]

        # ---- 第 1 页：基础设置（每个算子一致） ----
        pg1 = QWidget()
        f1 = QVBoxLayout(pg1)
        f1.setContentsMargins(8, 8, 8, 8)
        f1.setSpacing(7)
        name_ed = QLineEdit(node["name"])
        # ⚠️ 2026-10-21 需求：工具名称可自定义修改，改完画布卡片、蓝窗标题/
        # 信息行、页签名、黄窗及其它算子的选择项等所有显示旧名处一起同步
        name_ed.setFixedHeight(24)
        name_ed.setStyleSheet(_edit_ss)
        name_ed.setToolTip("可自定义修改工具名称（回车或点击别处生效），改名后所有显示处同步更新")

        def _on_name_edited():
            # ⚠️ 改名后“就地更新”标题/页签即可，禁止整窗重建——否则会
            # deleteLater 掉正在发 editingFinished 的 name_ed 自身，延迟销毁时
            # 该控件可能再发一次信号、读到旧文本把名字改回去（现象：没生效 /
            # 画布不更新 / 重新打开变回初始名）。
            sel = self.canvas.selected_node()
            if sel is None:
                return
            new = name_ed.text().strip()
            old = sel["name"]
            if not new or new == old:
                name_ed.setText(old)      # 空名/未变：回显原名
                return
            if self.document.rename_node(sel["id"], new):
                # 画布卡片 / 其它算子下拉随 changed 信号自动刷新
                self.canvas.update()
                # 蓝窗标题 + 第 1 页页签名就地更新（无需重建面板）
                self._float_algo._title_lbl.setText(f"算法参数 · {new}")
                tabs.setTabText(0, new)
                if self._float_io.isVisible():
                    self._refresh_io_panel()   # 黄窗引用的旧名同步

        name_ed.editingFinished.connect(_on_name_edited)
        name_ed.returnPressed.connect(_on_name_edited)
        f1.addLayout(self._params_form_row("工具名称", name_ed))

        is_image_src = (node["cat"] == "图像源")

        for label, first, suffix in (("定位器", "未指定", "坐标系"),
                                     ("图片输入", "未指定", "图像"),
                                     ("执行条件", "无条件", "结论")):
            if is_image_src and label == "图片输入":
                continue   # 图像源本身即图像来源，无「图片输入」
            cb = QComboBox()
            cb.setFixedHeight(24)
            cb.setStyleSheet(_combo_ss)
            cb.addItem(first)
            cb.addItems(f"{n['name']}：{suffix}" for n in others)
            f1.addLayout(self._params_form_row(label, cb))
        f1.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        for kind, tip, checkable in (
                ("eye", "显示/隐藏算法 ROI 框", True),
                ("chart", "显示/隐藏算法结果", True),
                ("full_roi", "使用全图 ROI", True),
                ("roi_edit", "编辑 ROI", False),
                ("list_cfg", "算法输出配置（选择算法输出内容）", False),
                ("palette_cfg", "显示配置（结果颜色/线宽）", False)):
            row.addWidget(self._params_icon_btn(kind, tip, checkable))
        row.addStretch(1)
        f1.addLayout(row)
        f1.addStretch(1)
        tabs.addTab(pg1, node["name"])

        # ---- 第 2 页：算法参数（每个算子不同） ----
        pg2 = QWidget()
        f2 = QVBoxLayout(pg2)
        f2.setContentsMargins(8, 8, 8, 8)
        f2.setSpacing(7)

        def _add_image_source_rows():
            # ⚠️ 2026-10-21 需求：图像源算子参数放「参数」页——
            # 1) 「图像源」下拉只有 物理相机 / 虚拟相机 两项；
            # 2) 选物理相机 → 「相机」行：自动选中当前工位绑定好的相机，
            #    未绑定则为空（不显示任何相机名）；
            # 3) 选虚拟相机 → 「图片源」行：旁边两个按钮 加载图片 / 加载文件夹，
            #    加载后缩略图出现在流程画布底部（仅虚拟相机+已加载时出现）。
            # 配置持久化到节点 img_src。
            src_cb = QComboBox()
            src_cb.setFixedHeight(24)
            src_cb.setStyleSheet(_combo_ss)
            src_cb.addItems(["物理相机", "虚拟相机"])
            src_cb.setCurrentText((node.get("img_src") or {}).get("type", "物理相机"))
            f2.addLayout(self._params_form_row("图像源", src_cb))

            dyn = QWidget()
            dyn_lay = QVBoxLayout(dyn)
            dyn_lay.setContentsMargins(0, 0, 0, 0)
            dyn_lay.setSpacing(7)
            f2.addWidget(dyn)

            cam_cb = None

            def _write():
                st = node.get("img_src") or {}
                node["img_src"] = {
                    "type": src_cb.currentText(),
                    "camera": cam_cb.currentText()
                              if (cam_cb is not None
                                  and src_cb.currentText() == "物理相机") else "",
                    # 已加载图片必须保留（切到物理相机再切回不清空）
                    "files": st.get("files") or [],
                }
                # 发出 changed：内嵌页与放大编辑窗的缩略图条同步评估
                # （虚拟相机+已加载图片即显示，与是否选中该算子无关）
                self.document.changed.emit()

            def _pick_camera():
                # 自动选中当前工位绑定好的相机；未绑定为空（索引 -1 显示空）
                bound = (node.get("img_src") or {}).get("camera", "")
                if bound:
                    cam_cb.setCurrentText(bound)
                else:
                    cam_cb.setCurrentIndex(-1)

            def _load_pics():
                files, _ = QFileDialog.getOpenFileNames(
                    self, "选择图片", "",
                    "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
                if not files:
                    return
                st = node.get("img_src") or {}
                node["img_src"] = {**st, "type": src_cb.currentText(),
                                   "camera": "", "files": list(files)}
                # 发出 changed：内嵌页与放大编辑窗的缩略图条同步评估
                # （虚拟相机+已加载图片即显示，与是否选中该算子无关）
                self.document.changed.emit()
                self._log(f"图像源：已加载 {len(files)} 张图片")

            def _load_dir():
                d = QFileDialog.getExistingDirectory(self, "选择图片文件夹", "")
                if not d:
                    return
                exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
                files = sorted(os.path.join(d, f) for f in os.listdir(d)
                               if os.path.splitext(f)[1].lower() in exts)
                if not files:
                    self._log("图像源：该文件夹中没有图片文件")
                    return
                st = node.get("img_src") or {}
                node["img_src"] = {**st, "type": src_cb.currentText(),
                                   "camera": "", "files": files}
                # 发出 changed：内嵌页与放大编辑窗的缩略图条同步评估
                # （虚拟相机+已加载图片即显示，与是否选中该算子无关）
                self.document.changed.emit()
                self._log(f"图像源：已从文件夹加载 {len(files)} 张图片")

            def _refresh_dyn():
                nonlocal cam_cb
                self._clear_layout(dyn_lay)
                if src_cb.currentText() == "虚拟相机":
                    holder = QWidget()
                    hh = QHBoxLayout(holder)
                    hh.setContentsMargins(0, 0, 0, 0)
                    hh.setSpacing(4)

                    def _btn(txt, cb):
                        b = QPushButton(txt)
                        b.setFixedHeight(24)
                        b.setCursor(Qt.CursorShape.PointingHandCursor)
                        b.setStyleSheet(_combo_ss)
                        b.clicked.connect(cb)
                        hh.addWidget(b)
                    _btn("加载图片", _load_pics)
                    _btn("加载文件夹", _load_dir)
                    hh.addStretch(1)
                    dyn_lay.addLayout(self._params_form_row("图片源", holder))
                else:
                    cam_cb = QComboBox()
                    cam_cb.setFixedHeight(24)
                    cam_cb.setStyleSheet(_combo_ss)
                    cam_cb.addItems(self._camera_names)
                    _pick_camera()
                    cam_cb.currentIndexChanged.connect(_write)
                    dyn_lay.addLayout(self._params_form_row("相机", cam_cb))
                _write()

            src_cb.currentIndexChanged.connect(_refresh_dyn)
            _refresh_dyn()

        if node["cat"] == "图像源":
            _add_image_source_rows()
        else:
            tpl = SIDE_PARAM_TPL.get(node["cat"], SIDE_PARAM_DEFAULT)
            for (name, val, lo, hi, unit, dec) in tpl:
                f2.addLayout(self._make_param_row(name, val, lo, hi, unit, dec))
            f2.addWidget(self._side_row_label(
                "以上为示例参数（演示）；接入真实算法后按该算子的实际参数展示。",
                COLORS['text_secondary'], size=10))
        f2.addStretch(1)
        tabs.addTab(pg2, "参数")
        return tabs

    def _params_form_row(self, label, w):
        """首页表单行：名称 + 输入控件，返回布局供加入面板。"""
        h = QHBoxLayout()
        h.setSpacing(6)
        lab = self._side_row_label(label)
        lab.setMinimumWidth(60)
        h.addWidget(lab)
        h.addWidget(w, 1)
        return h

    def _params_icon_btn(self, kind, tip, checkable):
        """首页底部小图标按钮（矢量图标，不依赖字体）。"""
        b = QPushButton()
        b.setIcon(_make_icon(kind, COLORS['text_secondary']))
        b.setIconSize(QSize(15, 15))
        b.setFixedSize(26, 24)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background-color:{COLORS['bg_card']}; "
            f"border:1px solid {COLORS['border']}; border-radius:3px;}}"
            f"QPushButton:hover{{border-color:{COLORS['accent_blue']};}}"
            f"QPushButton:checked{{background-color:{COLORS['accent_blue']};}}")
        return b

    def _make_time_row(self, stage, ms, ratio):
        """耗时行：阶段名 + 耗时 + 占比进度条，返回布局供加入面板。"""
        h = QHBoxLayout()
        h.setSpacing(6)
        lab = self._side_row_label(stage)
        lab.setMinimumWidth(56)
        h.addWidget(lab)
        val = self._side_row_label(f"{ms:.2f} ms", "#22A94E")
        val.setMinimumWidth(64)
        h.addWidget(val)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(ratio * 100)))
        bar.setFixedHeight(10)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar{{background-color:{COLORS['bg_card']}; "
            f"border:1px solid {COLORS['border']}; border-radius:4px;}}"
            f"QProgressBar::chunk{{background-color:{COLORS['accent_blue']}; "
            f"border-radius:4px;}}")
        h.addWidget(bar, 1)
        return h

    # ---- 黄窗：输入输出设置 ----
    def _refresh_io_panel(self):
        """重建黄窗内容：列出选中算子的输入（上游连线）与输出（下游连线）。"""
        self._clear_layout(self._io_body)
        node = self.canvas.selected_node()
        if node is None:
            self._io_body.addWidget(self._side_row_label(
                "请先在画布中选中一个算子节点\n（单击节点边框，选中后呈蓝色描边）",
                COLORS['text_secondary']))
            self._io_body.addStretch(1)
            return
        doc = self.canvas.document()
        name_of = {n["id"]: n["name"] for n in doc.nodes()}
        ups = [e["src"] for e in doc.edges() if e["dst"] == node["id"]]
        downs = [e["dst"] for e in doc.edges() if e["src"] == node["id"]]
        self._io_body.addWidget(self._side_row_label(
            f"算子：{node['name']}    分类：{node['cat']}",
            COLORS['text_secondary']))
        self._io_body.addWidget(self._side_row_label("输入", bold=True))
        if ups:
            for sid in ups:
                self._io_body.addLayout(
                    self._make_io_row("上游图像", name_of.get(sid, sid)))
        else:
            self._io_body.addWidget(self._side_row_label(
                "（暂无输入连线，可拖动上游节点底部输出端到本节点顶部输入端）",
                COLORS['text_secondary'], size=10))
        self._io_body.addWidget(self._side_row_label("输出", bold=True))
        if downs:
            for did in downs:
                self._io_body.addLayout(
                    self._make_io_row("结果输出", name_of.get(did, did)))
        else:
            self._io_body.addWidget(self._side_row_label(
                "（暂无输出连线，可拖动本节点底部输出端到下游节点顶部输入端）",
                COLORS['text_secondary'], size=10))
        tip = self._side_row_label(
            "「启用」开关控制该输入 / 输出是否参与运行（示例演示）；"
            "接入真实引擎后同步生效。",
            COLORS['text_secondary'], size=10)
        self._io_body.addWidget(tip)
        self._io_body.addStretch(1)

    def _make_io_row(self, role, peer):
        """输入/输出行：角色 + 对端算子名 + 启用开关，返回布局供加入面板。"""
        h = QHBoxLayout()
        h.setSpacing(6)
        lab = self._side_row_label(role)
        lab.setMinimumWidth(60)
        h.addWidget(lab)
        peer_lab = self._side_row_label(peer)
        h.addWidget(peer_lab, 1)
        chk = QCheckBox("启用")
        chk.setChecked(True)
        chk.setStyleSheet(
            f"QCheckBox{{color:{COLORS['text_primary']}; font-size:11px; spacing:4px; "
            f"border:none;}}"
            f"QCheckBox::indicator{{width:13px; height:13px; "
            f"border:1px solid {COLORS['border']}; border-radius:3px; "
            f"background-color:{COLORS['bg_card']};}}"
            f"QCheckBox::indicator:checked{{background-color:{COLORS['accent_blue']}; "
            f"border-color:{COLORS['accent_blue']};}}")
        h.addWidget(chk)
        return h

    def _open_dialog(self):
        """弹出「放大编辑」大窗口：共享同一数据模型，两边实时同步。"""
        if self._dlg is not None and self._dlg.isVisible():
            self._dlg.raise_()
            self._dlg.activateWindow()
            return
        self._dlg = FlowDesignDialog(self.document, self,
                                     camera_names=self._camera_names,
                                     current_camera=self._current_camera,
                                     image_display_cb=self._image_display_cb)
        self._dlg.show()
        # ⚠️ show() 时 Qt 才按「父窗口居中」落位并按布局最小尺寸改大小，
        # 会覆盖 show 前设置的几何——因此几何必须在 show 之后再应用；
        # 另排一次延迟应用：内页布局/画布 fit 可能在事件循环里迟到激活，
        # 把窗口尺寸又改掉（位置看似“没生效”的玄学来源）。
        self._apply_dialog_default_geo()
        QTimer.singleShot(60, self._apply_dialog_default_geo)
        self._dlg.raise_()
        self._dlg.activateWindow()

    def _apply_dialog_default_geo(self):
        """放大编辑窗默认大小与位置：覆盖内嵌页画布区域。

        ⚠️ 2026-10-21 需求（第四次反馈）：**顶缘对齐主窗顶部工具栏的下边缘**
        （MainWindow._header_frame 底缘——历经「画布顶/页面顶/Tab栏顶/
        Card顶」四轮微调后确认的最终基准：工具栏下边缘即内容区最顶端）。
        左缘对齐画布左缘、底缘 = 页面底缘。逐级回退：header → Card → Tab → 页。
        画布过小（页面未布局完）时按主窗比例右对齐兜底；均夹取回屏幕可用区域。
        """
        top = self.window()
        if top is None or not top.isVisible():
            return
        # 1) 首选：主窗顶部工具栏（header）下边缘
        hdr = getattr(top, "_header_frame", None)
        if hdr is not None and hdr.isVisible():
            top_ref, use_bottom = hdr, True
        else:
            # 2) 回退：承载本页的 QTabWidget 的父容器（Card）→ Tab → 本页
            ref = self.parentWidget()
            while ref is not None and not isinstance(ref, QTabWidget):
                ref = ref.parentWidget()
            if ref is not None:
                card = ref.parentWidget()
                ref = card if card is not None else ref
            top_ref = ref if ref is not None else self
            use_bottom = False
        if use_bottom:
            # ⚠️ 2026-10-21 需求（第六次反馈）：顶缘精确对齐顶部工具栏
            # （设备启动/停止所在的蓝色顶栏）的下边缘，不再上下微调。
            p_g_y = top_ref.mapToGlobal(top_ref.rect().bottomLeft()).y()
        else:
            p_g_y = top_ref.mapToGlobal(top_ref.rect().topLeft()).y()
        b_g = self.mapToGlobal(self.rect().bottomLeft()).y()
        c_g = self.canvas.mapToGlobal(self.canvas.rect().topLeft())
        g = QPoint(c_g.x(), p_g_y)   # 横向用画布左缘，顶缘按上方基准
        w = self.canvas.width()
        h = b_g - p_g_y              # 底缘保持页面底缘
        fallback = w < 700 or h < 500
        if fallback:
            # ⚠️ 2026-10-21 需求（第七次反馈）：画布嵌入区窄（<700）走兜底时——
            # 恢复「原来的宽度/高度」（0.58 / 0.86 主窗比例），并改为
            # **右上对齐**：右缘贴内容区右缘（基准容器右缘）、顶缘贴工具栏
            # 下缘。不再是左对齐，也不再无故变宽。
            w = max(900, int(top.width() * 0.58))
            h = max(600, int(top.height() * 0.86))
            tr = top_ref.mapToGlobal(top_ref.rect().topRight()).x()
            g = QPoint(tr - w - 8, p_g_y)
        # ⚠️ 2026-10-21 需求：放大编辑卡片高度顶部/底部分别向内收缩 10px
        # （顶缘下移 10、底缘上移 10，即总高收 20、上下各让出 10px）
        g.setY(g.y() + 10)
        h = max(1, h - 20)
        scr = self.screen()
        if scr is not None:
            av = scr.availableGeometry()
            w, h = min(w, av.width() - 24), min(h, av.height() - 24)
            g.setX(max(av.left(), min(g.x(), av.right() - w + 1)))
            g.setY(max(av.top(), min(g.y(), av.bottom() - h + 1)))
        self._dlg.resize(w, h)
        self._dlg.move(g)
        dbg = (f"放大编辑窗定位: 左上=({g.x()},{g.y()}) 尺寸={w}x{h} "
               f"顶缘基准y={p_g_y} 基准={('header下缘' if use_bottom else '回退容器顶')} "
               f"画布={self.canvas.width()}x{self.canvas.height()} "
               f"窗口={top.width()}x{top.height()} 兜底={fallback} "
               f"实际=({self._dlg.x()},{self._dlg.y()})")
        self._log(dbg)
        # 诊断落盘：%TEMP%\flow_align_diag.log（排查「改了不生效」类问题）
        try:
            import datetime
            import tempfile
            with open(os.path.join(tempfile.gettempdir(),
                                   "flow_align_diag.log"), "a",
                      encoding="utf-8") as f:
                f.write(datetime.datetime.now().strftime("%H:%M:%S ")
                        + dbg + "\n")
        except Exception:
            pass
        # 临时：把定位值显示到标题，截图即可见（排查后移除）
        self._dlg.setWindowTitle(
            f"检测流程设计 - 流程编辑器（放大编辑） [top={g.y()}/基准{p_g_y}]")

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

    def __init__(self, document, parent=None, camera_names=None, current_camera=None,
                 image_display_cb=None):
        super().__init__(parent)
        self.setWindowTitle("检测流程设计 - 流程编辑器（放大编辑）")
        self.resize(1100, 720)
        self.setModal(False)
        # 与主程序暗色弹窗一致
        self.setStyleSheet(f"QDialog{{background-color:{COLORS['bg_dark']};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(FlowDesignPage(document=document, embedded=False,
                                     camera_names=camera_names,
                                     current_camera=current_camera,
                                     image_display_cb=image_display_cb))
