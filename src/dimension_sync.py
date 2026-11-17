"""产品尺寸跨窗口双向同步通道（新建产品向导第 3 步 ↔ 相机调试界面检测列表）。

同一组尺寸（元件长度 / 宽度 / 厚度，对应检测项 106 / 107 / 108）在两处都能编辑：

- **新建/编辑产品向导第 3 步**：标称值 + 下公差 + 上公差 → 自动算出规格下限/上限；
- **相机调试界面检测列表**：标称值 / 规格下限 / 规格上限。

任一侧修改后立即同步到另一侧：
- 调试界面改了标称值或规格上下限 → 向导回填标称值，并按「公差 = 规格 − 标称」反算上下公差；
- 向导改了标称值或公差 → 调试列表刷新对应检测项的标称值与规格上下限。

本模块只做「值的中转」，不含业务判定，界面层各自负责呈现。
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

# 三个尺寸维度的键（与 NewProductDialog.DIMENSIONS 的键一致）
DIM_KEYS = ("length", "width", "thickness")


class DimensionBridge(QObject):
    """尺寸同步桥：保存最新一组尺寸，并向订阅者广播变更。"""

    # 参数：(最新尺寸字典, 来源标识)
    #   尺寸字典：{维度键: {"nominal": 标称值, "lower": 规格下限, "upper": 规格上限}}
    #   来源标识："dialog"=向导发出 / "debug"=调试界面发出
    changed = pyqtSignal(dict, str)

    def __init__(self):
        super().__init__()
        self._values = {}
        self._context = ("", "")   # (产品类型, 产品型号)
        self._source = ""          # 最近一次发布来源

    # ---------- 发布 ----------
    def publish(self, records, source="", context=None):
        """发布一组尺寸。records: {维度键: {nominal, lower, upper}}。

        只更新 records 中出现的维度（其余维度保持不变）；仅在数值真正发生变化时
        广播（避免两侧互相回写时产生循环）。返回是否发生变化。
        """
        if not records:
            return False
        new = {k: dict(v) for k, v in self._values.items()}
        for key in DIM_KEYS:
            rec = records.get(key)
            if not rec:
                continue
            new[key] = {
                "nominal": str(rec.get("nominal", "")),
                "lower": str(rec.get("lower", "")),
                "upper": str(rec.get("upper", "")),
            }
        if new == self._values:
            return False
        self._values = new
        self._source = source
        if context is not None:
            self._context = (str(context[0]), str(context[1]))
        self.changed.emit({k: dict(v) for k, v in new.items()}, source)
        return True

    # ---------- 读取 ----------
    def snapshot(self):
        """返回当前最新的一组尺寸副本。"""
        return {k: dict(v) for k, v in self._values.items()}

    def get(self, key):
        """返回单个维度的最新值副本。"""
        return dict(self._values.get(key) or {})

    @property
    def context(self):
        """当前尺寸所属的 (产品类型, 产品型号)。"""
        return self._context

    @property
    def source(self):
        """最近一次发布的来源标识（"dialog" / "debug" / "app"）。"""
        return self._source


# 全局唯一同步桥（向导与调试界面共用）
BRIDGE = DimensionBridge()
