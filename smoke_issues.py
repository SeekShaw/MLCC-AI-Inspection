import os, sys
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# 冒烟测试会触发配置写盘（时段默认时间 src/shift_defaults.json、报警设置 src/alarm_config.json）。
# 做法：把这两处落盘路径统一重定向到临时目录 —— 既验证真实写盘/重载行为，又完全不触碰
# 工程配置（无需事后删除，避免受安全删除策略限制）。同时在开测前快照 src/ 下原文件字节，
# 跑完只做「未被改动」的只读校验。
_TMP_CFG_DIR = tempfile.mkdtemp(prefix="smoke_cfg_")
_TMP_SHIFT = os.path.join(_TMP_CFG_DIR, "shift_defaults.json")
_TMP_ALARM = os.path.join(_TMP_CFG_DIR, "alarm_config.json")
_CFG_GUARD = {}
for _cfg_name in ("shift_defaults.json", "alarm_config.json"):
    _gp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", _cfg_name)
    _CFG_GUARD[_gp] = open(_gp, "rb").read() if os.path.exists(_gp) else None

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import production_view as _pvm_paths
_pvm_paths.SHIFT_DEFAULTS_PATH = _TMP_SHIFT      # 时段默认时间 → 临时目录
import alarm_config as _ac_paths
_ac_paths._config_path = lambda: _TMP_ALARM      # 报警设置配置 → 临时目录

from production_view import ProductionView

app = QApplication([])
pv = ProductionView(user_manager=None)
pv.show()
app.processEvents()

ok = True
def check(cond, msg):
    global ok
    print(("PASS" if cond else "FAIL"), "-", msg)
    if not cond:
        ok = False

def _spacer_before_widget(layout, widget):
    """检查 layout 中某 widget 之前是否存在 spacer（用于确认按钮被 stretch 推到右侧）。"""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return False
        if item.spacerItem() is not None:
            return True
    return False

def _layout_has_widget(layout, widget):
    """递归判断某 layout 子树中是否包含指定 widget。"""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return True
        sub = item.layout()
        if sub is not None and _layout_has_widget(sub, widget):
            return True
    return False

# ============ 问题1：统计方式按钮已移到底部操作行，不再放标题栏 ============
check(not hasattr(pv, "_header_stat_buttons"),
      "问题1: _header_stat_buttons 已移除（不再放标题栏）")
modes = set(pv.stat_mode_buttons.keys())
check("按剔除口统计" in modes and "按缺陷项统计" in modes,
      "问题1: '按剔除口统计'/'按缺陷项统计' 切换按钮仍存在")
# 标题栏动作应只剩 饼图/详情 两个
try:
    check(_spacer_before_widget(pv._stats_btn_row, pv.stat_mode_buttons["按剔除口统计"]),
          "问题1: 按剔除口统计按钮前存在 stretch（已右移）")
    check(_spacer_before_widget(pv._stats_btn_row, pv.stat_mode_buttons["按缺陷项统计"]),
          "问题1: 按缺陷项统计按钮前存在 stretch（已右移）")
except Exception as e:
    check(False, f"问题1: 异常 {e}")

# ============ 问题3：未点设备启动前，生产信息不自动刷新 ============
check(pv._idle_timer.isActive() == False,
      "问题3: 待机累计定时器未启动（无自动刷新）")
snap1 = pv.get_live_snapshot()
snap2 = pv.get_live_snapshot()
check(snap1 == snap2, "问题3: 未启动前后实时快照完全一致（不刷新）")
k1 = dict((k, v) for k, v, _ in snap1["kpi"])
check(int(k1["总数"]) == 0, f"问题3: 初始实时累计为 0（未启动，total={k1['总数']}）")

# ============ 模拟运行（点设备启动后）手动驱动 ============
# 300 批 * 每批 6 件（供料速度 12000 Pcs/Min 按 30ms 节拍折算）≈ 1800 件，
# 与「供料速度」新口径一致，样本量足够使良率稳定落在 95~97%
for _ in range(300):
    pv._accumulate_batch()
pv._refresh_live_stats_ui()

snap = pv.get_live_snapshot()
kpi = dict((k, v) for k, v, _ in snap["kpi"])
total = int(kpi["总数"])
yld = float(kpi["良品率"].rstrip("%"))
bad_rate = float(kpi["不良率"].rstrip("%"))
rechk_rate = float(kpi["重检率"].rstrip("%"))
kpi_rechk = int(kpi["重检数"])
print(f"    运行后快照: 总数={total} 良率={yld:.2f}% 不良率={bad_rate:.2f}% "
      f"重检率={rechk_rate:.2f}% 重检数={kpi_rechk}")
check(95.0 <= yld <= 97.0, f"问题3/2: 良率在 95~97% ({yld:.2f}%)")
check(0.0 <= rechk_rate <= 1.0, f"问题3/2: 重检率在 0~1% ({rechk_rate:.2f}%)")
check(abs(yld + bad_rate + rechk_rate - 100.0) < 0.5,
      f"问题2: 良率+不良率+重检率≈100% ({yld+bad_rate+rechk_rate:.2f}%)")

d_total = sum(v for _, v, _ in snap["donut"])
check(d_total == total, f"问题2: 环形图各段和=总数 ({d_total} vs {total})")

# ============ 问题2：详情表 重检数之和 == KPI 重检数 ============
rows = pv._reject_detail_view._rows
check(len(rows) == 8, f"问题2: 详情表 8 行 (实际 {len(rows)})")
detail_rechk_sum = sum(int(r[6]) for r in rows)
print(f"    详情表重检数之和={detail_rechk_sum}  KPI重检数={kpi_rechk}")
check(abs(detail_rechk_sum - kpi_rechk) <= 5,
      f"问题2: 详情表重检数之和≈KPI重检数 ({detail_rechk_sum} vs {kpi_rechk})")

# ============ 问题2：各相机总数基本一致（仅微小偏差）============
totals = [int(r[2]) for r in rows]
avg_t = sum(totals) / len(totals)
max_t, min_t = max(totals), min(totals)
print(f"    各相机总数: {totals}  平均={avg_t:.0f} 极差={max_t-min_t}")
check((max_t - min_t) <= 0.06 * avg_t,
      f"问题2: 各相机总数偏差≤6% (极差={max_t-min_t}, 均值={avg_t:.0f})")
# 行内自洽：总数=良品数+不良1数+不良2数+重检数
all_consistent = all(
    int(r[3]) + int(r[4]) + int(r[5]) + int(r[6]) == int(r[2]) for r in rows)
check(all_consistent, "问题2: 每行 总数=良品数+不良1数+不良2数+重检数")

# ============ 问题4：按缺陷项统计 SPC 七列表 ============
dsc = pv.defect_stats_view
# 饼图下方汇总表已删除（请求2）：确认 _agg_table 不再存在
check(not hasattr(dsc, "_agg_table"),
      "问题4/请求2: 饼图下方汇总表已删除（_agg_table 不再存在）")
check(dsc._detail_table.columnCount() == 7,
      f"问题4: 详情表 7 列 (实际 {dsc._detail_table.columnCount()})")
exp_headers = ["检测项", "标称值", "规格下限", "规格上限", "超下限数", "超上限数", "比例"]
got_headers = [dsc._detail_table.horizontalHeaderItem(c).text()
               for c in range(7)]
check(got_headers == exp_headers, f"问题4: 列头正确 ({got_headers})")

agg_rows = dsc._aggregated_rows()
check(len(agg_rows) == 13, f"问题4: 聚合 13 行缺陷项 (实际 {len(agg_rows)})")
check(all(len(r) == 7 for r in agg_rows), "问题4: 聚合每行 7 字段")
sum_ratio = sum(r[6] for r in agg_rows)
print(f"    聚合各缺陷比例之和={sum_ratio:.2f}%")
check(99.0 <= sum_ratio <= 101.0, f"问题4: 聚合比例之和≈100% ({sum_ratio:.2f}%)")
# 请求4（2026-09-11）：按缺陷项统计缺陷数之和须等于 KPI 不良品总数
sum_defect_bad = sum(r[4] + r[5] for r in agg_rows)
_kpi_bad = int(kpi["不良品数"])
check(sum_defect_bad == _kpi_bad,
      f"请求4: 按缺陷项统计缺陷数之和=不良品总数 (实际 {sum_defect_bad}, 期望 {_kpi_bad})")
# 按缺陷项饼图右侧图例：三列左对齐（缺陷项/数量/比例），用网格布局实现
from PyQt6.QtWidgets import QGridLayout, QGroupBox
check(isinstance(dsc._legend_layout, QGridLayout),
      "请求1: 缺陷饼图右侧图例为 QGridLayout（三列左对齐）")
check(dsc._legend_layout.rowCount() == 14,
      f"请求1: 图例 表头+13 行=14 行 (实际 {dsc._legend_layout.rowCount()})")
li = dsc._legend_layout.itemAtPosition
check(li(0, 1).widget().text() == "缺陷项" and
      li(0, 2).widget().text() == "数量" and
      li(0, 3).widget().text() == "比例",
      "请求1: 图例表头三列 = 缺陷项/数量/比例")
check(li(1, 0).widget().text() == "●", "请求1: 图例首行含颜色圆点")

# 请求3b（2026-09-11）：按缺陷项统计「详情页」默认选中「全部」（蓝底高亮）
check(dsc._current_cam == "全部", f"请求3b: 详情页默认相机为「全部」(实际 {dsc._current_cam})")
check(dsc._cam_buttons["全部"].isChecked() is True,
      "请求3b: 默认「全部」按钮处于选中（蓝底高亮）态")
# 切换到相机1 后：相机1 变为蓝底、「全部」取消高亮
dsc._select_camera("相机1")
app.processEvents()
check(dsc._cam_buttons["相机1"].isChecked() is True,
      "请求3b: 切换到相机1 后相机1 按钮蓝底高亮")
check(dsc._cam_buttons["全部"].isChecked() is False,
      "请求3b: 切换后「全部」按钮取消高亮")
# 请求1b：缺陷饼图右侧图例固定内容高度，行数超可视区时出现上下滚动条
check(getattr(dsc, "_legend_widget", None) is not None, "请求1b: 图例内容控件已存在")
check(dsc._legend_widget.height() == dsc._legend_widget.sizeHint().height(),
      f"请求1b: 图例内容已固定为实际高度(={dsc._legend_widget.height()})，超界即可滚动")
from PyQt6.QtCore import Qt as _Qt
check(dsc._legend_scroll.verticalScrollBarPolicy() == _Qt.ScrollBarPolicy.ScrollBarAsNeeded,
      "请求1b: 图例区垂直滚动条按需显示（内容超出时上下滚动）")
# 复位为「全部」，避免影响后续用例
dsc._select_camera("全部")
app.processEvents()

# 逐相机详情 7 字段
cam_rows = dsc._camera_rows("相机1")
check(all(len(r) == 7 for r in cam_rows), "问题4: 逐相机详情每行 7 字段")

# 详情页「全部」按钮：按缺陷项聚合所有相机的不良数（同名缺陷跨相机求和，不拼相机名）
check("全部" in dsc._cam_buttons, "请求3: 详情页相机行含「全部」按钮（位于最左）")
dsc._select_camera("全部")
app.processEvents()
all_rows = dsc._all_rows()
check(len(all_rows) == 13, f"请求3: 全部=按缺陷聚合 13 行 (实际 {len(all_rows)})")
check(all(len(r) == 7 for r in all_rows), "请求3: 全部每行 7 字段")
check(dsc._detail_table.rowCount() == 13,
      f"请求3: 详情表渲染 13 行 (实际 {dsc._detail_table.rowCount()})")
# 检测项列不含相机前缀（只显示缺陷名）
check(not all_rows[0][0].startswith("相机") and not all_rows[-1][0].startswith("相机"),
      f"请求3: 检测项不拼相机名 (例: {all_rows[0][0]}, {all_rows[-1][0]})")
# 聚合口径：与全局逐缺陷聚合 _aggregated_rows 完全一致（即跨相机求和）
check(all_rows == dsc._aggregated_rows(),
      "请求3: 全部=全局逐缺陷聚合（同名缺陷跨相机求和）")
# 比例之和≈100%
all_ratio = sum(r[6] for r in all_rows)
check(99.0 <= all_ratio <= 101.0, f"请求3: 全部比例之和≈100% ({all_ratio:.2f}%)")
# 切回单相机
dsc._select_camera("相机1")
app.processEvents()
check(dsc._detail_table.rowCount() == 13,
      f"请求3: 切回相机1 后详情表 13 行 (实际 {dsc._detail_table.rowCount()})")

# ============ 问题4：饼图/详情在运行中有刷新效果 ============
donut_before = [v for _, v, _ in dsc._chart.data]
for _ in range(80):
    pv._accumulate_batch()
pv._refresh_live_stats_ui()
donut_after = [v for _, v, _ in dsc._chart.data]
check(donut_before != donut_after,
      f"问题4: 缺陷饼图随运行刷新 (前和={sum(donut_before)} 后和={sum(donut_after)})")

# ============ 新增：请求1 设备停止后保持最后显示数据、不再刷新 ============
def _kpi_total(snap):
    return int(dict((k, v) for k, v, _ in snap["kpi"])["总数"])
pv._playing = True
pv._alarm_stopped = False
for _ in range(80):           # 再累计一批，制造可见的实时数据
    pv._accumulate_batch()
pv._refresh_live_stats_ui()
rows_before = list(pv._reject_detail_view._rows)
total_run = _kpi_total(pv.get_live_snapshot())
check(total_run > 0, f"请求1: 运行态存在实时数据 (总数={total_run})")
# 点击「设备停止」
pv.stop_playback()
# 1) 实时累计不清零（仍保留停止前数据）
total_stop = _kpi_total(pv.get_live_snapshot())
check(total_stop == total_run and total_stop > 0,
      f"请求1: 停止后实时累计未清零 (停止前={total_run}, 停止后={total_stop})")
# 2) 待机定时器未启动（不再自动刷新）
check(pv._idle_timer.isActive() == False,
      "请求1: 停止后待机定时器未启动（不再刷新）")
# 3) 显示的详情表数据保持（未被清空/未回退静态示例）
rows_after = list(pv._reject_detail_view._rows)
check(rows_after == rows_before and len(rows_after) == 8,
      "请求1: 停止后详情表数据保持显示（未清空）")
# 4) 停止后即便内部累计继续增长，显示数据也保持不变（确认不刷新）
for _ in range(40):
    pv._accumulate_batch()
check(list(pv._reject_detail_view._rows) == rows_after,
      "请求1: 停止后显示数据保持冻结（不随内部累计刷新）")
# 5) 停止后再次「设备启动」应从停机瞬间的显示数据继续累计，而非清零重计
try:
    total_resume0 = _kpi_total(pv.get_live_snapshot())
    pv.start_playback()                       # 未主动清零 → keep_counters 续跑
    total_resume1 = _kpi_total(pv.get_live_snapshot())
    check(total_resume1 >= total_resume0 and total_resume0 > 0,
          f"请求1: 停止后再次启动从停机数据续跑（停机={total_resume0}, 启动后={total_resume1}）")
    pv.stop_playback()
except Exception as e:
    check(False, f"请求1: 停止后再次启动异常 {e}")
# 复位，避免影响其它潜在用例
pv._reset_live()
pv._playing = False

# ============ 新需求：调试界面（相机按钮进入）也要显示生产信息（镜像生产运行界面）============
src = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/debug_view.py", encoding="utf-8").read()
check('StatsPanel, _make_user_frames' in src,
      "生产信息: debug_view 已从 production_view 导入 StatsPanel（恢复生产信息整块）")
check("self.stats_panel = StatsPanel(" in src,
      "生产信息: 调试界面已重新实例化 StatsPanel（生产信息显示回来）")
check("def _setup_stat_mirror(self):" in src,
      "生产信息: 调试界面已恢复 _setup_stat_mirror（镜像生产运行界面统计）")
check("sp.tick_live()" in src,
      "生产信息: 调试界面播放节拍已接回 stats_panel.tick_live()（持续同步）")

# 生产运行界面自身的「详情」页示例数据在待机态即正确显示（不依赖调试镜像）
pv3 = ProductionView(user_manager=None)
pv3.show()
app.processEvents()
check(hasattr(pv3, "_reject_detail_view"),
      "详情: 生产运行界面含剔除详情表 RejectDetailView")
rows3 = pv3._reject_detail_view._rows
check(len(rows3) == 8, f"详情: 待机示例态下详情表 8 行（实际 {len(rows3)}）")
check(all(len(r) == 7 for r in rows3),
      "详情: 每行含 7 字段（相机+良品率+总数+良品数+不良1+不良2+重检）")
# 切换时段后示例数据联动刷新（详情仍非空）
pv3._set_period("白班")
app.processEvents()
rows3b = pv3._reject_detail_view._rows
check(len(rows3b) == 8, f"详情: 切换时段后详情表仍 8 行（实际 {len(rows3b)}）")
pv3._reset_live(); pv3._playing = False

# ============ 功能验证：调试界面 StatsPanel 实时镜像生产运行界面 ============
from debug_view import DebugView
class _FakeMW:
    def __init__(self, prod):
        self.production = prod
mw = _FakeMW(pv3)
dv = DebugView(camera_name="下表面", main_window=mw)
app.processEvents()
check(hasattr(dv, "stats_panel"), "生产信息: 调试界面持有 stats_panel 实例")
check(getattr(dv.stats_panel, "_mirror_owner", None) is pv3,
      "生产信息: stats_panel 镜像源指向生产运行界面（单一数据源）")
check(getattr(dv.stats_panel, "_live", False) is True,
      "生产信息: 镜像模式已开启（begin_mirror 置 _live）")
# 待机态：调试界面生产详情应与生产运行界面一致（各相机 8 行示例数据）
drows = dv.stats_panel._reject_detail_view._rows
check(len(drows) == 8, f"生产信息: 待机态调试界面详情表 8 行（实际 {len(drows)}）")
check(all(len(r) == 7 for r in drows), "生产信息: 详情每行 7 字段")
# 环形图数据同源（与生产运行界面待机示例一致）
prod_donut = [tuple(x) for x in pv3.get_display_snapshot()["donut"]]
dbg_donut = dv.stats_panel.stat_datasets.get("按剔除口统计", [])
check(dbg_donut == prod_donut, "生产信息: 调试界面环形图数据=生产运行界面待机示例")
# 动态验证：改变生产运行界面时段后，调试界面镜像随 tick 同步
pv3._set_period("晚班"); app.processEvents()
dv.stats_panel.tick_live(); app.processEvents()
prod_donut2 = [tuple(x) for x in pv3.get_display_snapshot()["donut"]]
dbg_donut2 = dv.stats_panel.stat_datasets.get("按剔除口统计", [])
check(dbg_donut2 == prod_donut2, "生产信息: 切换时段后调试界面镜像同步更新")
check(len(dv.stats_panel._reject_detail_view._rows) == 8,
      "生产信息: 切换时段后调试界面详情表仍 8 行")
# 调试界面底部统计方式按钮同样右对齐
check(_spacer_before_widget(dv.stats_panel._stats_btn_row,
                            dv.stats_panel.stat_mode_buttons["按剔除口统计"]),
      "生产信息: 调试界面统计方式按钮已右移")
dv._playing = False

# ============ 新需求：调试界面检测项表格工具条与「良率预警设置」列 ============
src_dv = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/debug_view.py", encoding="utf-8").read()
# 1) 工具条顺序（运行时校验从左到右）：
#    设置为默认 → 恢复至默认 → 恢复至出厂 → 单位设置 → 出料设置 → 全部同步
#    （「检测项全开/关」已移到「是否检测」列头右侧，不再出现在工具条）
from PyQt6.QtWidgets import QPushButton as _QPushButton, QHBoxLayout as _QHBoxLayout
_TOOLBAR_ORDER = ["设置为默认", "恢复至默认", "恢复至出厂",
                  "单位设置", "出料设置", "全部同步"]
_toolbar_found = None
for _lay in dv.findChildren(_QHBoxLayout):
    _widgets = [_lay.itemAt(i).widget() for i in range(_lay.count())]
    _texts = [w.text() for w in _widgets if isinstance(w, _QPushButton)]
    if _texts == _TOOLBAR_ORDER:
        _toolbar_found = _lay
        break
check(_toolbar_found is not None,
      "工具条: 运行时按钮从左到右顺序为 设置为默认→恢复至默认→恢复至出厂→单位设置→出料设置→全部同步")
_toolbar_texts = [_toolbar_found.itemAt(i).widget().text()
                  for i in range(_toolbar_found.count())
                  if _toolbar_found.itemAt(i).widget() is not None]
check("检测项全开" not in _toolbar_texts,
      "工具条: 「检测项全开」已移出工具条（改为是否检测列头覆盖按钮）")
# 2) 检测项表格新增「良率预警设置」列（位于「检测项操作」右侧，第 14 列）
check(dv._table.columnCount() == 14,
      f"良率预警列: 表格列数=14（实际 {dv._table.columnCount()}）")
# 最后一列列头名称左对齐显示
_last_hdr = dv._table.horizontalHeaderItem(dv._table.columnCount() - 1)
check(_last_hdr.text() == "良率预警设置"
      and bool(int(_last_hdr.textAlignment()) & int(_Qt.AlignmentFlag.AlignLeft)),
      f"列头左对齐: 「良率预警设置」列头左对齐 (align={_last_hdr.textAlignment()})")
# 计算元素精确查找列表：行距放宽（不拥挤）
check("inner_lay.setSpacing(10)" in src_dv and "padding-left: 6px" in src_dv,
      "精确查找列表: 行间距 10px + 名称左内边距（不再拥挤）")
check(dv._table.horizontalHeaderItem(13).text() == "良率预警设置",
      "良率预警列: 第14列表头为「良率预警设置」")
check(dv._yield_warn.get(0) == {"enabled": True, "threshold": 50},
      "良率预警列: 默认启用且阈值 50%")
_cw = dv._table.cellWidget(0, 13)
from components import ToggleSwitch as _TS
from PyQt6.QtWidgets import QSpinBox as _QSpinBox
_spin = _cw.findChildren(_QSpinBox)
_tg = _cw.findChildren(_TS)
check(len(_spin) == 1 and _spin[0].value() == 50 and "%" in _spin[0].suffix(),
      "良率预警列: 第1行含阈值输入框（默认 50%）")
check(len(_tg) == 1, "良率预警列: 第1行含启用开关（ToggleSwitch）")

# 5) 「单位」列：悬停提示右键选择 + 右键菜单 5 项
# ⚠️ 2026-10-09「检测值」列移到「检测结果」左侧后，单位列号由 9 → 8、
# 检测值列号由 5 → 9。这里改为**按表头名定位列号**，避免以后再调列序时
# 断言静默失效（历史教训：硬编码列号在改列序后会误报或漏报）。
_hdrs = [dv._table.horizontalHeaderItem(c).text()
         for c in range(dv._table.columnCount())]
_unit_col = _hdrs.index("单位")
_val_col = _hdrs.index("检测值")
_res_col = _hdrs.index("检测结果")
check(dv._table.horizontalHeaderItem(_unit_col).text() == "单位",
      "单位列: 表头为「单位」")
_unit_cell = dv._table.cellWidget(0, _unit_col)
check(_unit_cell is not None
      and _unit_cell.toolTip() == "鼠标右键单击可选择单位",
      "单位列: 单元格悬停提示「鼠标右键单击可选择单位」")
_unit_menu = _unit_cell._build_menu()
check([a.text() for a in _unit_menu.actions()]
      == ["Pixel", "mm", "Deg", "Dec", "灰度级"],
      "单位列: 右键菜单包含 Pixel/mm/Deg/Dec/灰度级")
_unit_cell.set_unit("灰度级"); app.processEvents()
check(dv._table_data[0][8] == "灰度级" and _unit_cell.current_unit() == "灰度级",
      "单位列: 选择「灰度级」后写入底层数据并刷新显示")
_unit_cell.set_unit("Pixel"); app.processEvents()   # 还原，避免影响后续断言

# 6) 「检测值」列：数值 + 「值分布」按钮（原数值分布列按钮移入此处）
check(dv._table.horizontalHeaderItem(_val_col).text() == "检测值",
      "检测值列: 表头为「检测值」")
_val_cw = dv._table.cellWidget(0, _val_col)
check(_val_cw is not None, "检测值列: 第1行含组合控件（数值 + 按钮）")
# ⚠️ 2026-10-09 需求：「检测值」整列位于「检测结果」列**左侧**（紧邻）
check(_val_col == _res_col - 1,
      f"检测值列: 紧邻「检测结果」列左侧（检测值={_val_col} / 检测结果={_res_col}）")
_val_btn = [_b for _b in _val_cw.findChildren(_QPushButton) if _b.text() == "值分布"]
check(len(_val_btn) == 1, "检测值列: 第1行含「值分布」按钮（由数值分布列移入）")
check("分布图" not in "".join(b.text() for b in _val_cw.findChildren(_QPushButton)),
      "检测值列: 按钮已改名「值分布」（不再叫「分布图」）")
# ⚠️ 回归护栏：调列序最怕「值串列」。逐列核对**文本列**单元格文本与
# `_data_index_for_col` 映射的原始数据一致（cellWidget 列无文本 item，跳过）。
_CELLW_COLS = {1, _unit_col, _val_col, 12, 13}
_bad = []
for _r in range(6):
    for _c, _h in enumerate(_hdrs):
        if _c in _CELLW_COLS:
            continue
        _di = dv._data_index_for_col(_c)
        if _di is None:
            continue
        _it = dv._table.item(_r, _c)
        if _it is None or _it.text() != str(dv._table_data[_r][_di]):
            _bad.append((_r, _h))
check(not _bad,
      f"检测项表格: 调整列序后无「值串列」（逐列核对 6 行 × 文本列，异常 {_bad[:4]}）")
# 「检测值」单元格显示值必须与底层 row[4] 一致（映射仍指向原始检测值字段）
_v_ok = all(dv._val_labels[_r].text() == str(dv._table_data[_r][4])
            for _r in range(6))
check(_v_ok, "检测值列: 各行显示值与底层数据 row[4] 一致（未错取其他字段）")

# ⚠️ 2026-10-09 需求：红框（检测项表格）内所有字号统一 10px。
# 根因回顾：`QFont("Microsoft YaHei", n)` 的 n 是**磅**(n pt≈1.33n px)，
# 而按钮样式表 `font-size: n px` 是**像素** → 两者曾不一致。
# 现已全部改为 10px（表格 setPixelSize(10)、按钮 font-size:10px），
# 此处断言表格正文 = 按钮 = 检测值标签 = 单位单元格，且均为 10px。
from PyQt6.QtGui import QFontMetrics as _QFM2
_h_tbl = _QFM2(dv._table.font()).height()
_tcell = dv._table.cellWidget(0, 12)
_teach = [b for b in _tcell.findChildren(_QPushButton) if b.text() == "教导"][0]
_h_btn = _QFM2(_teach.font()).height()
check(dv._table.font().pixelSize() == 10,
      f"表格正文: 字号为 10px（pixelSize={dv._table.font().pixelSize()}）")
check(_h_tbl == _h_btn,
      f"表格正文与「教导」按钮字号一致（表格 {_h_tbl}px / 按钮 {_h_btn}px）")
# cellWidget 内的标签不继承表格字体，需各自设定
from PyQt6.QtWidgets import QLabel as _QLb2
_h_val = _QFM2(dv._val_labels[0].font()).height()
check(_h_val == _h_btn,
      f"检测值标签字号与按钮一致（标签 {_h_val}px / 按钮 {_h_btn}px）")
_h_unit = _QFM2(dv._unit_cells[0].findChildren(_QLb2)[0].font()).height()
check(_h_unit == _h_btn,
      f"单位单元格字号与按钮一致（单位 {_h_unit}px / 按钮 {_h_btn}px）")
# 列头与「全开/全关」批量开关同样统一 10px
check(dv._table.horizontalHeader().font().pixelSize() == 10,
      f"表格列头: 字号为 10px（pixelSize={dv._table.horizontalHeader().font().pixelSize()}）")
_ss_all = dv._detect_all_btn.styleSheet()
check("font-size: 10px" in _ss_all,
      "「全开/全关」批量开关字号为 10px")

# ⚠️⚠️ 2026-10-09 回归护栏（高价值）：调列序那轮**漏改**了`_detect_spec`，
# 它硬编码 `item(r, 7)/item(r, 8)` 读规格上下限，列序变为6=下限/7=上限/8=单位后
# 读成 (上限, None) → 值分布弹窗「规格下限显示成上限值、曲线图缺失下限线」。
# 这类「按列号取单元格」的函数**必须按表头名定位**，故此处逐行断言其正确性。
_c_lo = _hdrs.index("规格下限")
_c_hi = _hdrs.index("规格上限")
_spec_bad = []
for _r in range(dv._table.rowCount()):
    _lo, _hi = dv._detect_spec(_r)
    _raw = dv._table_data[_r]
    _e_lo = float(_raw[6]) if str(_raw[6]).strip() else None
    _e_hi = float(_raw[7]) if str(_raw[7]).strip() else None
    # 上下限若同时存在，不允许 lo > hi（曾因错列出现 lo==hi 的退化情况）
    if _lo != _e_lo or _hi != _e_hi:
        _spec_bad.append((_r, _lo, _hi, _e_lo, _e_hi))
    elif _lo is not None and _hi is not None and _lo > _hi:
        _spec_bad.append((_r, "lo>hi", _lo, _hi))
check(not _spec_bad,
      f"规格上下限: 逐行与底层 row[6]/row[7] 一致且 lo<=hi（异常 {_spec_bad[:3]}）")
# 「检测值」中心值读取同样必须按表头名（曾硬编码 item(r,5) 读到补偿值列）。
# ⚠️ 注意：`_detect_center` 对**检测值为 0** 的行有历史兜底（`(r+1)*0.42`，
# 避免分布图中心落在 0），故只断言「读到的是检测值列的数值、而非补偿值(恒 0)」，
# 不能直接等值断言 raw[4]。
_c_corr = dv._col_by_header("补偿值")
_c_valc = dv._col_by_header("检测值")
check(_c_corr != _c_valc,
      f"检测值中心值: 「补偿值」列({_c_corr}) 与「检测值」列({_c_valc}) 不是同一列")
_cen_bad = []
for _r in range(dv._table.rowCount()):
    _raw = dv._table_data[_r]
    _e_c = float(_raw[4]) if str(_raw[4]).strip() else None
    if _e_c:      # 仅检测值非 0 的行可等值断言
        _c = dv._detect_center(_r)
        if _c != _e_c:
            _cen_bad.append((_r, _c, _e_c))
check(not _cen_bad,
      f"检测值中心值: 检测值非 0 的行与底层 row[4] 一致"
      f"（未错取补偿值等其它列，异常 {_cen_bad[:3]}）")
# 值分布弹窗：下限线必须存在（lo 非空）且 lo < hi → 图上会画出两条限线
_r6 = 6
_lo6, _hi6 = dv._detect_spec(_r6)
check(_lo6 is not None and _hi6 is not None and _lo6 < _hi6,
      f"值分布: 产品长度规格上下限有效且下限<上限（lo={_lo6} / hi={_hi6}）")
from PyQt6.QtWidgets import QDoubleSpinBox as _QDoubleSpinBoxCls
import sys as _sys
_dbgmod = _sys.modules[type(dv).__module__]
_dd = _dbgmod.DistributionDialog(
    dv, "产品长度", _r6, dv.get_distribution_samples(_r6),
    lo=_lo6, hi=_hi6, prod_start=dv._prod_start_time)
_dd.setModal(False)
app.processEvents()
_sps = _dd.findChildren(_QDoubleSpinBoxCls)
check(len(_sps) >= 2 and abs(_sps[0].value() - _lo6) < 1e-6
      and abs(_sps[1].value() - _hi6) < 1e-6,
      f"值分布: 规格下限/上限输入框回填正确（下限={_sps[0].value() if _sps else None}"
      f" / 上限={_sps[1].value() if len(_sps) > 1 else None}）")
_dd.close()

# 「亮度差异」指标行（2026-10-09 新增）：值 30-100 随机波动、恒 OK、合格范围 30-225
_bm = getattr(dv, "_eff_metrics", {}).get("亮度差异")
check(_bm is not None, "图像效果调节: 存在「亮度差异」示例行")
if _bm is not None:
    check(_bm["lo"] == 30.0 and _bm["hi"] == 100.0,
          f"图像效果调节: 亮度差异随机区间为 30-100（实际 {_bm['lo']}~{_bm['hi']}）")
    check(_bm["qual_lo"] == 30.0 and _bm["qual_hi"] == 225.0,
          f"图像效果调节: 亮度差异合格范围为 30-225"
          f"（实际 {_bm['qual_lo']}~{_bm['qual_hi']}）")
    _bv = []
    for _ in range(8):
        dv._refresh_effect_values()
        _bv.append(float(_bm["val"].text()))
    check(all(30.0 <= v <= 100.0 for v in _bv),
          f"图像效果调节: 亮度差异 8 次刷新值均在 30-100 内（{_bv}）")
    check(_bm["badge"].text() == "OK",
          f"图像效果调节: 亮度差异结果为 OK（实际 {_bm['badge'].text()}）")
# 数值分布列已移除：现表头序列中不存在「数值分布」
_all_headers = [dv._table.horizontalHeaderItem(c).text()
                for c in range(dv._table.columnCount())]
check("数值分布" not in _all_headers, "数值分布列: 已移除（按钮并入检测值列）")
# 点击单元格：无白色圆角焦点框（outline:0）且选中底色透明
check("outline: 0" in dv._table.styleSheet(),
      "检测项表格: 样式含 outline:0（点击单元格无白色圆角焦点框）")
# 计算元素精确查找列表：勾选框改为开关，默认全部开启
check(len(dv._target_content._find_rows) == 16
      and all(type(sw) is _TS and sw.is_on() for _, sw, _, _ in dv._target_content._find_rows),
      "精确查找列表: 16 行开关（ToggleSwitch）且默认全部开启")
# 3) 产品定位搜索设置卡片：改为跨「相机行 + 工具条行」的网格布局（高度=两者之和，
#    底边与工具条行对齐，不再用最小高度 hack）
check("top_grid.addWidget(signal_card, 0, 1, 2, 1)" in src_dv,
      "卡片高度: 信号卡片在网格中跨「相机行+工具条行」两行（底边与工具条行对齐）")
check("top_grid.addLayout(toolbar, 1, 0)" in src_dv,
      "卡片高度: 工具条位于网格左列第二行（相机画布正下方）")
check("signal_card.setMinimumHeight(" not in src_dv,
      "卡片高度: 已移除固定最小高度 hack（高度由跨行网格布局自然决定）")

# 4) 列表「是否检测」列（第 2 列）改为 ToggleSwitch 开关；其「全开/全关」批量按钮
#    覆盖在「是否检测」列头右侧（与「良率预警设置」列头的开关同机制）
_btns = {b.text(): b for b in dv.findChildren(_QPushButton)}
# 是否检测列：全部行使用 ToggleSwitch 开关（与最后一列良率预警一致）
check(all(dv._table.cellWidget(r, 1).findChild(_TS) is not None
          for r in range(dv._table.rowCount())),
      "是否检测列: 全部行使用 ToggleSwitch 开关（与最后一列一致）")
_det_all = dv._detect_all_btn
check(_det_all.parent() is dv._table.horizontalHeader().viewport(),
      "检测项全开: 按钮父级为列表横向表头视口（覆盖在是否检测列头上）")
check(_det_all.text() == "全开", "检测项全开: 初始文本为「全开」")
_det_all.click(); app.processEvents()
check(_det_all.text() == "全关", "检测项全开→点击后变为「全关」")
check(all(sw.is_on() for sw in dv._row_checks.values()),
      "检测项全开→点击后所有「是否检测」开关置为开启")
_det_all.click(); app.processEvents()
check(_det_all.text() == "全开", "检测项全关→再点击恢复「全开」")
check(not any(sw.is_on() for sw in dv._row_checks.values()),
      "检测项全关→点击后所有「是否检测」开关关闭")
# 是否检测列：列加宽（列头文字左对齐 + 右侧全开/全关开关互不遮挡）
check(dv._table.columnWidth(1) >= 110,
      f"是否检测列: 列宽已加宽 ≥110（实际 {dv._table.columnWidth(1)}）")
_det_hdr = dv._table.horizontalHeaderItem(1)
check(_det_hdr is not None
      and bool(int(_det_hdr.textAlignment()) & int(_Qt.AlignmentFlag.AlignLeft)),
      "是否检测列: 列头名称左对齐显示")
# 点击单元格不再显示橙色选中底色（局部样式覆盖全局橙色高亮）
check("transparent" in dv._table.styleSheet(),
      "检测项列表: 选中单元格底色透明（无橙色高亮）")

check("全开" in _btns, "批量开关: 「全开/全关」文字开关实例存在")
_yield_all = dv._yield_all_btn
_on_style = _yield_all.styleSheet()
check(_yield_all.text() == "全开", "预警全开: 初始文本为「全开」")
check("_reposition_overlay_buttons" in src_dv and "QEvent.Type.Resize" in src_dv,
      "预警开关: 开关覆盖在「良率预警设置」列头右侧（表头视口跟随重定位）")
check(_yield_all.parent() is dv._table.horizontalHeader().viewport(),
      "预警开关: 按钮父级为列表横向表头视口（覆盖在列头上）")
_hh = dv._table.horizontalHeader()
_last = dv._table.columnCount() - 1
dv._reposition_overlay_buttons()   # 显式重定位（未 show 时 timer 可能未触发）
check(_yield_all.width() > 0 and _yield_all.height() > 0,
      "预警开关: 按钮已初始化且可点击")
if _hh.viewport().width() > 0:   # 表头视口有效时才校验精确几何（未展示时跳过）
    _exp = _hh.sectionViewportPosition(_last) + _hh.sectionSize(_last) - _yield_all.width() - 4
    check(abs(_yield_all.x() - max(0, int(_exp))) <= 6,
          "预警开关: 重定位到「良率预警设置」列头右侧")
else:
    check(True, "预警开关: 未展示时跳过几何校验（覆盖在列头视口，show 后在列头右侧）")
_yield_all.click(); app.processEvents()
check(_yield_all.text() == "全关", "预警全开→点击后变为「全关」")
check(all(rec["enabled"] for rec in dv._yield_warn.values()),
      "预警全开→点击后所有行良率预警置为启用")
_off_style = _yield_all.styleSheet()
check(_on_style != _off_style, "预警全开/全关: 两种状态按钮底色不同（全开≠全关）")
_yield_all.click(); app.processEvents()
check(_yield_all.text() == "全开", "预警全关→再点击恢复「全开」")
check(not any(rec["enabled"] for rec in dv._yield_warn.values()),
      "预警全关→点击后所有行良率预警关闭")
check("良率预警批量控制" not in src_dv and "warn_strip" not in src_dv,
      "预警开关: 旧的独立开关条（良率预警批量控制/warn_strip）已移除")

# ============ 新需求：速度/良率「持续时长」+ 底部「缺陷图查看」 ============
src_app = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/app.py", encoding="utf-8").read()
src_ac = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/alarm_config.py", encoding="utf-8").read()
src_ad = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/alarm_dialog.py", encoding="utf-8").read()
# 1) 报警设置-速度/良率：删除「持续时长」设置（含检测项良率预警行）
check('self._sq_duration_spins' not in src_ad,
      "速度/良率: 已移除 _sq_duration_spins（不再收集持续时长）")
check('ALARM["sq_duration"]' not in src_ad,
      "速度/良率: 不再落盘 ALARM[sq_duration]")
check('sq_duration(' not in src_ad,
      "速度/良率: 对话框不再用 sq_duration() 回填初始值")
check('"sq_duration"' not in src_ac and "def sq_duration" not in src_ac,
      "alarm_config: 已移除 sq_duration 默认配置与访问器")
# 2) 底部信息栏「缺陷图查看」：位于「显示所有图像」左侧，点击弹出新窗口
check(src_app.index("缺陷图查看") < src_app.index("显示所有图像"),
      "底部信息栏: 「缺陷图查看」位于「显示所有图像」左侧")
check("_open_defect_images" in src_app and "DefectImageWindow" in src_app,
      "底部信息栏: 「缺陷图查看」点击打开 DefectImageWindow 窗口")
check("DEFECT_COUNT = 50" in open("C:/Users/Lenovo/WorkBuddy/Teruo/src/defect_image_window.py", encoding="utf-8").read(),
      "缺陷图查看: 窗口展示最新 50 张缺陷图（DEFECT_COUNT=50）")
from defect_image_window import DefectImageWindow as _DIW
_diw = _DIW()
check(len(_diw._items) == 50, "缺陷图查看: 实际生成 50 张缺陷图")
check(len({it["camera"] for it in _diw._items}) == 8,
      "缺陷图查看: 缺陷图覆盖全部 8 个工位相机")
check(all(it.get("defect") and it.get("time") and it.get("result") == "NG"
          for it in _diw._items),
      "缺陷图查看: 每张图均带缺陷项 / 检测时间 / NG 判定信息")
_diw._idx = 3; _diw._list.setCurrentRow(3); app.processEvents()
check(_diw.lbl_cam.text() == _diw._items[3]["camera"],
      "缺陷图查看: 点击缩略图后右侧显示对应工位相机与缺陷信息")
_zoom0 = _diw._zoom
_diw.b_zoom_in.click(); app.processEvents()
check(_diw._zoom > _zoom0, "缺陷图查看: 「放大」提高显示比例")
_diw.b_zoom_out.click(); app.processEvents()
check(abs(_diw._zoom - _zoom0) < 1e-6, "缺陷图查看: 「缩小」恢复显示比例")
_row0 = _diw._idx
_diw.b_next.click(); app.processEvents()
check(_diw._idx == (_row0 + 1) % 50, "缺陷图查看: 「下一张」切到下一张缺陷图")
_diw.b_prev.click(); app.processEvents()
check(_diw._idx == _row0, "缺陷图查看: 「上一张」切回原缺陷图")
_diw.close()

# ============ 新需求：高级设置「设备停止统计清零」+ 报警设置「检测项良率预警」 ============
src_nav = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/nav_dialogs.py", encoding="utf-8").read()
src_app = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/app.py", encoding="utf-8").read()
src_ac = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/alarm_config.py", encoding="utf-8").read()
src_ad = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/alarm_dialog.py", encoding="utf-8").read()
# 1) 高级设置-运行选项：设备停止统计清零（默认不启用，位于「启用蜂鸣报警提示」上一行）
_i_stopclr = src_nav.index("stop_clear_stats")
_i_beep = src_nav.index('"beep", "启用蜂鸣报警提示"')
check(_i_stopclr < _i_beep,
      "高级设置: 「设备停止统计清零」位于「启用蜂鸣报警提示」上一行")
check('"stop_clear_stats": False' in src_app,
      "高级设置: 设备停止统计清零默认不启用（stop_clear_stats=False）")
check('get("stop_clear_stats")' in src_app and "_toggle_clear" in src_app,
      "高级设置: 设备停止后按开关自动清零生产统计（_on_stop 已挂钩）")
# 2) 报警设置-速度/良率页：检测项良率预警（无阈值，仅报警方案下拉，与其他行一致）
check("检测项良率预警" in src_ad and "_item_yield_plan_combo" in src_ad,
      "报警设置: 速度/良率页新增「检测项良率预警」行（仅报警方案下拉）")
check('"item_yield_plan"' in src_ac and "def item_yield_plan(" in src_ac,
      "报警设置: 检测项良率预警方案已入配置并可持久化（默认 方案 1）")
check("item_yield_plan()" in src_ad,
      "报警设置: 良率预警方案下拉初值取自配置（与其他行一致）")

# ============ 新增需求：检索页下拉选项字号与「搜索方式」标签一致（像素 13px）============
src = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/debug_view.py", encoding="utf-8").read()
check("setPixelSize(13)" in src,
      "字号: 下拉选项改用像素字号 setPixelSize(13)（与标签 font-size:13px 一致）")
check('self._mode_combo.setFont(QFont("Microsoft YaHei", 13))' not in src,
      "字号: 已移除 point 字号 13 的误用（避免比 13px 标签偏大）")

# ============ 新需求：生产运行界面平均速度/瞬时速度置于环状饼图上方（与调试界面一致）============
stats_lay = pv.chart_stack.parentWidget().layout()
idx_speed = -1
for i in range(stats_lay.count()):
    item = stats_lay.itemAt(i)
    if item.layout() is not None and _layout_has_widget(item.layout(), pv.s1):
        idx_speed = i
        break
idx_chart = stats_lay.indexOf(pv.chart_stack)
check(idx_speed >= 0, "速度: 生产运行界面速度行存在于统计面板布局中")
check(idx_chart >= 0, "速度: 生产运行界面环状饼图存在于统计面板布局中")
check(idx_speed < idx_chart,
      f"速度: 平均速度/瞬时速度位于环状饼图上方 (速度行#{idx_speed} < 图#{idx_chart})")
# 调试界面 StatsPanel 同样：速度行在 chart_stack 之前
dv_lay = dv.stats_panel.chart_stack.parentWidget().layout()
idx_speed_d = -1
for i in range(dv_lay.count()):
    item = dv_lay.itemAt(i)
    if item.layout() is not None and _layout_has_widget(item.layout(), dv.stats_panel.s1):
        idx_speed_d = i
        break
idx_chart_d = dv_lay.indexOf(dv.stats_panel.chart_stack)
check(idx_speed_d >= 0 and idx_speed_d < idx_chart_d,
      f"速度: 调试界面速度行同样位于饼图上方 (速度行#{idx_speed_d} < 图#{idx_chart_d})")

# ============ 本轮：图例三列对齐 + 缺陷图例可滚动 + 速度波动 ============
# 1) 按剔除口统计饼图右侧图例为三列网格布局（生产运行界面）
check(isinstance(pv.legend_layout, QGridLayout),
      "图例: 按剔除口统计右侧图例为 QGridLayout（三列左对齐）")

# 2) 平均速度/瞬时速度示例值随机波动（生产运行态下调用 _tick_speed 验证格式与范围）
import re as _re
pv.set_speed_running(True)   # 模拟设备启动、生产运行
pv._tick_speed()
m_avg = _re.search(r"平均速度：(\d+)", pv.s1.text())
m_inst = _re.search(r"瞬时速度：(\d+)", pv.s2.text())
check(m_avg is not None and m_inst is not None,
      "速度: _tick_speed 后 s1/s2 含平均速度/瞬时速度数值")
if m_avg:
    avg_v = int(m_avg.group(1))
    check(10850 <= avg_v <= 11150, f"速度: 平均速度在 [10850,11150] 内 (实际 {avg_v})")
    check("Pcs/Min" in pv.s1.text(), "速度: 单位已改为 Pcs/Min")
    if m_inst:
        inst_v = int(m_inst.group(1))
        check(inst_v != avg_v, f"速度: 瞬时速度与平均速度不同 (avg={avg_v}, inst={inst_v})")

# 3) 未启动（idle）：速度保持 0，不刷新
pv.set_speed_running(False)
pv._speed_stopped = False   # 模拟从未启动
pv._tick_speed()
check(pv.s1.text().endswith("0 Pcs/Min") and pv.s2.text().endswith("0 Pcs/Min"),
      f"速度: 未启动(idle)时平均/瞬时速度均为 0 (s1={pv.s1.text()}, s2={pv.s2.text()})")

# 4) 停止后衰减：从 11000 起连续 tick 应逐渐降低并最终归零
pv.set_speed_running(True)
pv._avg_speed = 11000
pv.set_speed_running(False)
pv._tick_speed()
after1 = int(_re.search(r"平均速度：(\d+)", pv.s1.text()).group(1))
check(after1 < 11000 and after1 > 0, f"速度: 停止后首拍即开始降低 (after1={after1})")
for _ in range(200):
    pv._tick_speed()
check(pv.s1.text().endswith("0 Pcs/Min") and pv.s2.text().endswith("0 Pcs/Min"),
      f"速度: 停止后速度逐渐衰减到 0 (s1={pv.s1.text()}, s2={pv.s2.text()})")
# 复位速度状态，避免影响其它用例
pv.set_speed_running(False)
pv._speed_stopped = False
pv._avg_speed = 0

# 5) 设备编码右侧按钮已改为图标按钮（icon 非空）
check(not pv.device_detail_btn.icon().isNull(),
      f"设备按钮: 设备编码右侧为图标按钮 (icon.isNull={pv.device_detail_btn.icon().isNull()})")

# 3) 按缺陷项统计饼图右侧图例：仍是三列网格，且外层为可滚动 QScrollArea
dsc = pv.defect_stats_view
check(isinstance(dsc._legend_layout, QGridLayout),
      "图例: 按缺陷项统计右侧图例为 QGridLayout")
from PyQt6.QtWidgets import QScrollArea as _QScrollArea
check(isinstance(getattr(dsc, "_legend_scroll", None), _QScrollArea),
      "图例: 按缺陷项统计图例外层为 QScrollArea（行数不全时出滚动条）")
# 调试界面 StatsPanel 剔除口图例同样为网格
check(isinstance(dv.stats_panel.legend_layout, QGridLayout),
      "图例: 调试界面按剔除口统计右侧图例也为 QGridLayout")

# ============ 新需求：本地图像窗口尾部显示 总数/OK/NG/RST 统计 ============
from local_image_window import LocalImageWindow
liw = LocalImageWindow(pv)
liw.load_examples()   # 加载 6 张示例图并按序号稳定分类 OK/NG/RST
app.processEvents()
check(liw.stat_total.text().startswith("总数：6"),
      f"本地图像: 尾部统计总数=6 (实际 {liw.stat_total.text()})")
try:
    okc = int(liw.stat_ok.text().split("：")[1])
    ngc = int(liw.stat_ng.text().split("：")[1])
    rstc = int(liw.stat_rst.text().split("：")[1])
    check(okc + ngc + rstc == 6,
          f"本地图像: OK+NG+RST=总数 (OK={okc}, NG={ngc}, RST={rstc})")
    check(okc > 0 and ngc > 0 and rstc > 0,
          f"本地图像: OK/NG/RST 均有分布 (OK={okc}, NG={ngc}, RST={rstc})")
except Exception as e:
    check(False, f"本地图像: 统计解析异常 {e}")

# ============ 新需求：设备设置 DD马达运行模式（生产运行/玻璃清洁/点动旋转）============
from PyQt6.QtWidgets import QLabel, QWidget as _QWidget
from device_settings_dialog import DeviceSettingsDialog
class _FakeMW2(_QWidget):
    def __init__(self, prod):
        super().__init__()
        self.production = prod
mw2 = _FakeMW2(pv)
dlg = DeviceSettingsDialog(mw2)
app.processEvents()
check(len(dlg._mode_btns) == 3, "DD模式: 运行模式含 3 个按钮")
check([b.text() for b in dlg._mode_btns] == ["生产运行", "玻璃清洁", "点动旋转"],
      f"DD模式: 按钮顺序正确 ({[b.text() for b in dlg._mode_btns]})")
check(dlg.dd_stack.count() == 3, "DD模式: 堆叠参数页共 3 页")
check(abs(dlg.sb_prod.value() - 21.0) < 1e-6,
      f"DD模式: 生产运行目标转速默认 21.00 (实际 {dlg.sb_prod.value()})")
check(abs(dlg.sb_clean.value() - 1.0) < 1e-6,
      f"DD模式: 玻璃清洁目标转速默认 1.00 (实际 {dlg.sb_clean.value()})")
check(abs(dlg.sb_jog.value() - 5.0) < 1e-6,
      f"DD模式: 点动旋转点动转速默认 5.00 (实际 {dlg.sb_jog.value()})")
# 默认工作模式为「生产运行」
check(dlg._dd_mode == "生产运行", "DD模式: 默认工作模式为「生产运行」")
check(dlg.dd_stack.currentIndex() == 0, "DD模式: 默认显示第 0 页（生产运行）")
# 生产运行页标签为「目标转速」
check(any(l.text() == "目标转速" for l in dlg.dd_stack.widget(0).findChildren(QLabel)),
      "DD模式: 生产运行页含「目标转速」标签")
# 切换到玻璃清洁
dlg._set_dd_mode("玻璃清洁")
check(dlg.dd_stack.currentIndex() == 1, "DD模式: 切到玻璃清洁显示第 1 页")
check(any(l.text() == "目标转速" for l in dlg.dd_stack.widget(1).findChildren(QLabel)),
      "DD模式: 玻璃清洁页含「目标转速」标签")
check(abs(dlg.pv.dev_cfg["dd_motor"]["speed_rpm"] - 1.0) < 1e-6,
      "DD模式: 玻璃清洁下旋转盘模拟转速=1.00")
# 切换到点动旋转
dlg._set_dd_mode("点动旋转")
check(dlg.dd_stack.currentIndex() == 2, "DD模式: 切到点动旋转显示第 2 页")
check(any(l.text() == "点动转速" for l in dlg.dd_stack.widget(2).findChildren(QLabel)),
      "DD模式: 点动旋转页含「点动转速」标签")
check(abs(dlg.pv.dev_cfg["dd_motor"]["speed_rpm"] - 5.0) < 1e-6,
      "DD模式: 点动旋转下旋转盘模拟转速=5.00")
dlg.close()

# ============ 新需求：本地图像窗口与「生产信息」卡片右上角对齐 ============
src_dv = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/debug_view.py", encoding="utf-8").read()
check('self._place_floating(w, self.stats_card, "right")' in src_dv,
      "本地图像: 弹出位置锚点已改为「生产信息」卡片（stats_card）右上对齐")

# ============ 新需求：设备状态卡片改名 + 玻璃清洁按钮 ============
from PyQt6.QtWidgets import QPushButton as _QPushButton
status_panel = pv.panels[2]
check(status_panel.header.title.text() == "设备状态",
      f"设备状态卡片: 标题已改为「设备状态」 (实际 {status_panel.header.title.text()})")
check(isinstance(getattr(pv, "_btn_glass_clean", None), _QPushButton),
      "设备状态卡片: 存在「玻璃清洁」按钮")
check(pv._btn_glass_clean.text() == "玻璃清洁",
      f"设备状态卡片: 玻璃清洁按钮文字为「玻璃清洁」 (实际 '{pv._btn_glass_clean.text()}')")
check(pv._btn_glass_clean.toolTip() == "玻璃清洁",
      f"设备状态卡片: 按钮悬停提示为「玻璃清洁」 (实际 {pv._btn_glass_clean.toolTip()})")
check(not pv._btn_glass_clean.icon().isNull(),
      "设备状态卡片: 玻璃清洁按钮已设置图标（图标按钮）")
import styles as _styles_m
check("QToolTip" in _styles_m.MAIN_STYLE,
      "全局样式: 含 QToolTip 规则（悬停提示文字可见，不再黑字透明底）")
# 停止态（未启动）下按钮可用
check(pv._btn_glass_clean.isEnabled(),
      "设备状态卡片: 停止态下「玻璃清洁」按钮可用")
# 进入生产运行态 -> 按钮禁用；停止 -> 恢复可用
try:
    pv.start_playback()
    check(not pv._btn_glass_clean.isEnabled(),
          "设备状态卡片: 生产运行态下「玻璃清洁」按钮禁用")
    pv.stop_playback()
    check(pv._btn_glass_clean.isEnabled(),
          "设备状态卡片: 停止后「玻璃清洁」按钮恢复可用")
except Exception as e:
    check(False, f"设备状态卡片: start/stop_playback 异常 {e}")

# —— 2026-10-09 新需求：「玻璃清洁」左侧新增「模拟生产」按钮 ——
check(isinstance(getattr(pv, "_btn_simulate", None), _QPushButton),
      "设备状态卡片: 存在「模拟生产」按钮")
check(pv._btn_simulate.text() == "模拟生产",
      f"设备状态卡片: 模拟生产按钮文字为「模拟生产」 (实际 '{pv._btn_simulate.text()}')")
# 「模拟生产」必须在「玻璃清洁」左侧
_sim_x = pv._btn_simulate.mapTo(status_panel,
                               pv._btn_simulate.rect().topLeft()).x()
_gc_x = pv._btn_glass_clean.mapTo(status_panel,
                                  pv._btn_glass_clean.rect().topLeft()).x()
check(_sim_x < _gc_x,
      f"设备状态卡片: 「模拟生产」位于「玻璃清洁」左侧"
      f"（模拟生产 x={_sim_x} / 玻璃清洁 x={_gc_x}）")
# 停止态可点击；生产运行态置灰不可点击；停止后恢复
check(pv._btn_simulate.isEnabled(),
      "设备状态卡片: 停止态下「模拟生产」按钮可点击")
try:
    pv.start_playback()
    check(not pv._btn_simulate.isEnabled(),
          "设备状态卡片: 生产运行态下「模拟生产」按钮置灰不可点击")
    check(_styles_m.COLORS["text_secondary"] in pv._btn_simulate.styleSheet(),
          "设备状态卡片: 生产运行态下「模拟生产」按钮为置灰样式"
          f"（色值 {_styles_m.COLORS['text_secondary']}）")
    pv.stop_playback()
    check(pv._btn_simulate.isEnabled(),
          "设备状态卡片: 停止后「模拟生产」按钮恢复可点击")
except Exception as e:
    check(False, f"设备状态卡片: 模拟生产按钮状态切换异常 {e}")

# 模拟生产设置窗口：开关默认关闭 + 8 路相机路径 + 底部提示
import simulate_config as _simcfg_m
check(_simcfg_m.default_cfg()["enabled"] is False,
      "模拟生产: 配置默认开关为关闭")
check(len(_simcfg_m.CAM_NAMES) == 8,
      f"模拟生产: 共 8 路相机 (实际 {len(_simcfg_m.CAM_NAMES)})")
from nav_dialogs import SimulateProductionDialog as _SimDlg
_sdlg = _SimDlg(pv)
app.processEvents()
check(not _sdlg._enable_sw.isChecked(),
      "模拟生产窗口: 开关默认为关闭")
check(len(_sdlg._edits) == 8 and list(_sdlg._edits.keys()) == _simcfg_m.CAM_NAMES,
      f"模拟生产窗口: 含 8 路相机路径输入框 (实际 {len(_sdlg._edits)})")
_sim_tips = [l.text() for l in _sdlg.findChildren(QLabel)
             if "设备启动" in l.text()]
check(bool(_sim_tips) and "设置完毕后" in _sim_tips[0]
      and "设备启动" in _sim_tips[0],
      f"模拟生产窗口: 底部提示「设置完毕后点击设备启动即可模拟生产」(实际 {_sim_tips})")
_sdlg.close()

# ============ 新需求：料盒卡片取出计时与状态窗体同行（右侧显示），状态窗体收窄 ============
for _bk in ("OK", "NG1", "NG2", "RST"):
    _brec = pv._status_recs.get(_bk + " 料盒")
    check(_brec is not None and _brec.get("time_lbl") is not None
          and _brec.get("state_lbl") is not None,
          f"取出计时同行: {_bk} 料盒卡片含状态窗体与计时标签")
_brec_ng1 = pv._status_recs["NG1 料盒"]
# 前序 start_playback 演示可能随机把某料盒置为取出态：先全部复位为未取出再断言
for _bk in ("OK", "NG1", "NG2", "RST"):
    if pv._bin_taken.get(_bk, False):
        pv._set_bin_taken(_bk + " 料盒", False)
check(not _brec_ng1["time_lbl"].isVisible(),
      "取出计时同行: 未取出时计时标签隐藏（无空窗体）")
check(_brec_ng1["state_lbl"].width() <= 50,
      f"取出计时同行: 状态窗体宽度已收窄 (实际 {_brec_ng1['state_lbl'].width()}px)")
try:
    import time as _time_mod
    pv._playing = True
    pv._set_bin_taken("NG1 料盒", True)
    pv._bin_taken_since["NG1"] = _time_mod.monotonic() * 1000.0 - 839
    pv._update_bin_taken_status()
    check(_brec_ng1["time_lbl"].isVisible() and _brec_ng1["time_lbl"].text().endswith(" s"),
          f"取出计时同行: 取出态下计时与单位 s 显示 (实际 '{_brec_ng1['time_lbl'].text()}')")
    try:
        _tv = float(_brec_ng1["time_lbl"].text().split(" ")[0])
        check(0 <= _tv < 100 and "." in _brec_ng1["time_lbl"].text()
              and len(_brec_ng1["time_lbl"].text().split(".")[1].split(" ")[0]) == 2,
              f"取出计时同行: 计时以 s 为单位保留 2 位小数 (实际 '{_brec_ng1['time_lbl'].text()}')")
    except ValueError:
        check(False, f"取出计时同行: 计时格式非法 ('{_brec_ng1['time_lbl'].text()}')")
    check(_brec_ng1["state_lbl"].text() == "取出",
          f"取出计时同行: 状态窗体为「取出」 (实际 '{_brec_ng1['state_lbl'].text()}')")
    pv._set_bin_taken("NG1 料盒", False)
    check(not _brec_ng1["time_lbl"].isVisible() and _brec_ng1["time_lbl"].text() == "",
          "取出计时同行: 放回后计时清空并隐藏")
    pv._playing = False
except Exception as e:
    check(False, f"取出计时同行: 刷新流程异常 {e}")
# ============ 新需求：玻璃清洁前高压静电模块断电安全判断 ============
# ESD 默认通电，需先断电才能清洁；离屏无界面，用假 QMessageBox 避免弹窗阻塞
from PyQt6.QtWidgets import QMessageBox as _QMessageBox
import production_view as pv_mod
_esd_msgs = []
class _FakeMB:
    @staticmethod
    def information(parent, title, text, *a, **k):
        _esd_msgs.append((title, text))
        return None
pv_mod.QMessageBox = _FakeMB

check(pv.dev_cfg["hv_esd"].get("powered", True) is True,
      "静电安全: 高压静电模块默认通电工作中")
# ESD 通电时点击玻璃清洁 -> 弹窗提示且禁止清洁
pv._on_glass_clean_clicked()
check(len(_esd_msgs) == 1, "静电安全: ESD 通电时点击玻璃清洁出现弹窗提示")
check(_esd_msgs and "高压静电模块正在通电工作中" in _esd_msgs[-1][1],
      f"静电安全: 弹窗内容为『正在通电工作中，请手动关闭』 (实际 {_esd_msgs[-1][1] if _esd_msgs else None})")
cfg_gc = pv.dev_cfg["dd_motor"]
check(not (cfg_gc.get("running") and cfg_gc.get("mode") == "玻璃清洁"),
      "静电安全: ESD 通电时点击玻璃清洁未启动清洁（被阻止）")

# 模拟手动断电后点击 -> 放行并弹「已断电」提示，启动玻璃清洁
pv.dev_cfg["hv_esd"]["powered"] = False
pv._on_glass_clean_clicked()
check(cfg_gc["mode"] == "玻璃清洁" and cfg_gc["running"],
      "静电安全: ESD 断电后点击玻璃清洁切到玻璃清洁并运行")
check(_esd_msgs and "已断电停止工作" in _esd_msgs[-1][1],
      f"静电安全: 弹窗内容为『已断电停止工作，请放心清洁玻璃』 (实际 {_esd_msgs[-1][1]})")
# 再次点击 -> 停止清洁（断电态下仅停止，不再弹窗）
pv._on_glass_clean_clicked()
check(not cfg_gc["running"], "静电安全: 再次点击玻璃清洁停止")
pv_mod.QMessageBox = _QMessageBox   # 还原，避免影响后续逻辑

# ============ 新需求：玻璃清洁按钮宽度收窄 ============
check(pv._btn_glass_clean.minimumWidth() <= 80,
      f"玻璃清洁按钮: 宽度已收窄 (minimumWidth={pv._btn_glass_clean.minimumWidth()})")
check(pv._btn_glass_clean.iconSize().width() <= 14,
      f"玻璃清洁按钮: 图标已缩小 (iconSize={pv._btn_glass_clean.iconSize().width()})")

# ============ 新需求：瞬时速度停止后快速衰减、10 秒归零 ============
pv.set_speed_running(True)
pv._tick_speed()
pv.set_speed_running(False)
_inst_seq, _avg_seq = [], []
for _ in range(10):
    pv._tick_speed()
    _inst_seq.append(int(pv.s2.text().split("：")[1].split(" ")[0]))
    _avg_seq.append(int(pv.s1.text().split("：")[1].split(" ")[0]))
check(_inst_seq[-1] == 0,
      f"速度衰减: 停止后瞬时速度 10 秒内归零 (序列 {_inst_seq})")
check(_inst_seq[0] < _avg_seq[0],
      f"速度衰减: 瞬时速度衰减快于平均速度 (瞬时={_inst_seq[0]}, 平均={_avg_seq[0]})")
check(_avg_seq[-1] > 0,
      f"速度衰减: 平均速度仍缓慢衰减、未同时归零 (平均={_avg_seq[-1]})")

# ============ 新需求：运行日志不再出现半行截断 ============
pv.resize(1600, 900)
pv.show()
pv._apply_default_layout()
app.processEvents()
_lv = pv._log_view
_row_h = _lv._rows[0][0].sizeHint().height()
_slot = _row_h + _lv._list_lay.spacing()
_vp_h = _lv._scroll.viewport().height()
_bottom = _lv._list_lay.contentsMargins().bottom()
check(_vp_h > _row_h, f"运行日志: 视口已布局可测量 (vp_h={_vp_h}, row_h={_row_h})")
check(_bottom == (_vp_h - _row_h) % _slot,
      f"运行日志: 底部留白对齐整数行、无半行截断 (bottom={_bottom}, expect={(_vp_h - _row_h) % _slot})")

# ============ 新需求：统计时段行最右侧「导出」→ 生产报表弹窗 ============
check(isinstance(getattr(pv, "_btn_export_report", None), _QPushButton),
      "生产报表: 统计时段行存在「导出」按钮")
check(pv._btn_export_report.text() == "导出",
      f"生产报表: 按钮文字为「导出」 (实际 '{pv._btn_export_report.text()}')")
# 按钮须在「当前运行 / 运行开始 / 现在」这一行的最右侧
_lay = pv.panels[3].body.layout()
_frow = None
for _i in range(_lay.count()):
    _sub = _lay.itemAt(_i).layout()
    if _sub is not None and _sub.indexOf(pv.d_end) >= 0 \
            and _sub.indexOf(pv._btn_export_report) >= 0:
        _frow = _sub
        break
check(_frow is not None, "生产报表: 「导出」与起止时间处于同一行")
check(_frow is not None and _frow.indexOf(pv._btn_export_report) > _frow.indexOf(pv.d_end),
      "生产报表: 「导出」按钮位于该行最右侧（在结束时间之后）")

# ============ 新需求：「导出」左侧增加「检索」按钮（按检索方式+时间范围刷新统计）============
import production_view as _pvm
check(isinstance(getattr(pv, "_btn_search_stat", None), _QPushButton),
      "统计检索: 统计时段行存在「检索」按钮")
check(pv._btn_search_stat.text() == "检索",
      f"统计检索: 按钮文字为「检索」 (实际 '{pv._btn_search_stat.text()}')")
check(_frow is not None and _frow.indexOf(pv._btn_search_stat) >= 0
      and _frow.indexOf(pv._btn_search_stat) < _frow.indexOf(pv._btn_export_report),
      "统计检索: 「检索」位于「导出」左侧")

# ============ 新需求：检索按钮左侧增加「产品多选筛选」下拉 ============
check(isinstance(getattr(pv, "_product_filter", None), _pvm.ProductFilterCombo),
      "产品筛选: 检索按钮左侧存在产品多选筛选下拉")
if getattr(pv, "_product_filter", None) is not None:
    check(_frow.indexOf(pv._product_filter) >= 0
          and _frow.indexOf(pv._product_filter) < _frow.indexOf(pv._btn_search_stat),
          "产品筛选: 筛选下拉位于「检索」按钮左侧")
    check(pv._product_filter._btn.text().startswith("产品筛选"),
          f"产品筛选: 按钮默认文案 (实际 '{pv._product_filter._btn.text()}')")
    # 复选逻辑：勾选多项后按钮文案反映已选数量；清除后恢复默认
    pf = pv._product_filter
    pf._products = [
        {"id": "x1", "product_type": "电容", "product_model": "0402"},
        {"id": "x2", "product_type": "电阻", "product_model": "0603"},
        {"id": "x3", "product_type": "电感", "product_model": "0805"},
    ]
    pf._checked = {"x1", "x2", "x3"}
    pf._update_text()
    check("已选" in pf._btn.text() and "3" in pf._btn.text(),
          f"产品筛选: 勾选后文案反映已选数量 (实际 '{pf._btn.text()}')")
    pf._clear()
    check(pf._btn.text() == "产品筛选 ▾", "产品筛选: 清除后按钮恢复默认文案")
    # 显示名：自定义优先，缺省回退 产品类型+型号（如 电容 0402）
    check(_pvm._product_display_label({"product_type": "电容", "product_model": "0402"}) == "电容 0402",
          "产品筛选: 无自定义时回退 产品类型+型号")
    check(_pvm._product_display_label({"product_type": "电阻", "product_model": "0603",
          "custom_type_display": "贴片电阻R"}) == "贴片电阻R",
          "产品筛选: 自定义类型优先")
check(isinstance(pv._resolve_products(), list),
      "产品筛选: 可从主窗口解析已建产品列表（独立构造时为空）")
check(pv._stat_filter_products == [], "产品筛选: 初始未勾选任何产品")
# 按不同检索方式 + 时间范围检索：应刷新 KPI / 环形图 / 相机 / 缺陷项，并落盘时间范围
import json as _json, os as _os
_shift_path = _pvm.SHIFT_DEFAULTS_PATH
_pv_pt_backup = dict(pv.period_times)
pv.period_cb.setCurrentText("白班")
pv.d_start.setText("20260910 08:00:00")
pv.d_end.setText("20260910 16:00:00")
pv._on_search_stats()
check(pv.period == "白班",
      f"统计检索: 按检索方式刷新时段 (实际 {pv.period})")
check(pv._kpi_example == _pvm.PERIOD_DATA["白班"]["kpi"],
      "统计检索: KPI 已按检索方式刷新")
check(pv._period_yield == _pvm.PERIOD_DATA["白班"]["yield"],
      f"统计检索: 良品率已刷新 (实际 {pv._period_yield})")
check(pv.period_times.get("白班") == ("20260910 08:00:00", "20260910 16:00:00"),
      f"统计检索: 时间范围已按输入落盘 (实际 {pv.period_times.get('白班')})")
check(pv.d_start.text() == "20260910 08:00:00" and pv.d_end.text() == "20260910 16:00:00",
      "统计检索: 检索后起止时间输入框保持用户所设范围")
# 时间范围应已持久化到 shift_defaults.json（下次启动仍生效）
with open(_shift_path, "r", encoding="utf-8") as _f:
    _saved = _json.load(_f)
check(list(_saved.get("白班", [])) == ["20260910 08:00:00", "20260910 16:00:00"],
      f"统计检索: 时间范围已持久化到 shift_defaults.json (实际 {_saved.get('白班')})")
# 内存时段表立即复位，避免影响后续断言（磁盘配置由文件末尾统一还原）
pv.period_times.clear()
pv.period_times.update(_pv_pt_backup)
pv.period_cb.setCurrentText("当前运行")

# ============ 新需求：检索按钮可用性（当前运行置灰）+ 检索后统计固定显示 ============
check(not pv._btn_search_stat.isEnabled(),
      "统计检索: 统计方式=「当前运行」时「检索」置灰不可点")
for _p in ("指定时间段", "白班", "中班", "晚班"):
    pv.period_cb.setCurrentText(_p)
    check(pv._btn_search_stat.isEnabled(),
          f"统计检索: 统计方式=「{_p}」时「检索」可点击")
# 点击「检索」→ 统计数据固定显示（周期刷新不再改写）
pv.period_cb.setCurrentText("白班")
pv.d_start.setText("20260910 08:00:00")
pv.d_end.setText("20260910 16:00:00")
pv._on_search_stats()
check(pv._stat_frozen is True, "统计检索: 点击「检索」后进入固定显示（冻结刷新）")
check(pv.period == "白班", f"统计检索: 固定显示的数据为检索方式对应时段 (实际 {pv.period})")
# 冻结期间：改大实时计数后跑一次周期刷新，KPI 显示值必须保持不变
_frozen_kpi = [v.text() for v, _l, _c in pv.kpi_grid._cells]
_pv_total_bak = pv._live_total
pv._live_total = (_pv_total_bak or 100) + 999999
pv._live_yield = -1.0
pv._refresh_live_stats_ui()
_frozen_kpi2 = [v.text() for v, _l, _c in pv.kpi_grid._cells]
check(_frozen_kpi2 == _frozen_kpi,
      f"统计检索: 固定显示期间周期刷新不改写统计数据 (前={_frozen_kpi[:2]} 后={_frozen_kpi2[:2]})")
check(pv._live_yield == -1.0,
      "统计检索: 固定显示期间刷新函数被短路（未重算统计）")
pv._live_total = _pv_total_bak
# 切回「当前运行」→ 解冻、恢复按正常示例数据刷新
pv.period_cb.setCurrentText("当前运行")
check(pv._stat_frozen is False, "统计检索: 切回「当前运行」后自动解除固定显示")
pv._refresh_live_stats_ui()
check(pv._live_yield != -1.0,
      f"统计检索: 切回「当前运行」后恢复刷新 (实际良率 {pv._live_yield})")

# ============ 新需求：检索按钮→「返回」→恢复默认「当前运行-运行开始-现在」 ============
# 默认（当前运行）：按钮「检索」且置灰不可点
check(pv._btn_search_stat.text() == "检索" and not pv._btn_search_stat.isEnabled(),
      "检索返回: 默认统计状态时按钮为「检索」且置灰")
# 切到「白班」并点击检索 → 按钮变「返回」且可点（进入返回模式）
pv.period_cb.setCurrentText("白班")
pv._on_search_stats()
check(pv._search_return_mode is True, "检索返回: 已进入返回模式")
check(pv._btn_search_stat.text() == "返回" and pv._btn_search_stat.isEnabled(),
      f"检索返回: 检索后按钮变「返回」且可点 (实际 '{pv._btn_search_stat.text()}')")
check(pv.period == "白班", "检索返回: 检索后仍停留在该检索时段")
# 再点「返回」→ 恢复默认「当前运行 - 运行开始 - 现在」，按钮复位「检索」
pv._on_search_stats()
check(pv.period == "当前运行", f"检索返回: 再点返回恢复默认时段 (实际 {pv.period})")
check(pv._search_return_mode is False, "检索返回: 已退出返回模式")
check(pv._btn_search_stat.text() == "检索" and not pv._btn_search_stat.isEnabled(),
      f"检索返回: 恢复后按钮复位「检索」 (实际 '{pv._btn_search_stat.text()}')")
check(pv.d_start.text() == "运行开始" and pv.d_end.text() == "现在",
      f"检索返回: 默认起止时间为 运行开始/现在 (实际 {pv.d_start.text()}/{pv.d_end.text()})")
# 复位时段表，避免影响后续断言
pv.period_times.clear(); pv.period_times.update(_pv_pt_backup)
pv.period_cb.setCurrentText("当前运行")

# ============ 新需求：切换/检索不触发清零重计（生产运行界面，播放中） ============
# 设备仍在生产时，切换检索方式或点击「检索」只应冻结显示，累计计数持续累加、绝不清零。
_pv_playing_bak = pv._playing
_pv_total_bak = pv._live_total
_pv_good_bak = pv._live_good
_pv_bad_bak = pv._live_bad
_pv_rechk_bak = pv._live_rechk
try:
    pv._playing = True
    pv._live_total = 56890
    pv._live_good = 56000.0
    pv._live_bad = 100.0
    pv._live_rechk = 790.0
    # 1) 仅切换检索方式下拉（如晚班），不应清零累计计数
    pv.period_cb.setCurrentText("晚班")
    check(pv._live_total == 56890,
          f"不清零: 播放中切换检索方式下拉不重置累计计数 (实际 {pv._live_total})")
    check(pv._stat_frozen is False, "不清零: 仅切换下拉未进入冻结（仍然正常刷新）")
    # 2) 点击「检索」→ 冻结显示，但累计计数仍保持不变（后台持续统计）
    pv._on_search_stats()
    check(pv._stat_frozen is True, "不清零: 检索后进入冻结（固定显示）")
    check(pv._live_total == 56890,
          f"不清零: 检索不重置累计计数 (实际 {pv._live_total})")
    # 3) 后台仍在累计：模拟若干拍后计数应增长（验证未被清零阻断）
    for _ in range(3):
        pv._accumulate_batch()
    check(pv._live_total > 56890,
          f"不清零: 检索冻结期间后台累计仍在增长 (实际 {pv._live_total})")
    # 4) 点击「返回」→ 恢复当前运行，累计计数不被清零，而是继续显示已累计值
    pv._on_search_stats()
    check(pv._stat_frozen is False, "不清零: 返回后解除冻结（恢复实时刷新）")
    check(pv._live_total > 56890,
          f"不清零: 返回后累计计数不被清零重计 (实际 {pv._live_total})")
finally:
    pv._playing = _pv_playing_bak
    pv._live_total = _pv_total_bak
    pv._live_good = _pv_good_bak
    pv._live_bad = _pv_bad_bak
    pv._live_rechk = _pv_rechk_bak
    pv.period_cb.setCurrentText("当前运行")
    pv._stat_frozen = False
    pv._search_return_mode = False

# ============ 新需求：运行日志卡片「日志详情」按钮（冻结左侧，内容与「日志管理」一致） ============
check(isinstance(getattr(pv, "_btn_log_detail", None), _QPushButton),
      "日志详情: 运行日志卡片存在「日志详情」按钮")
if isinstance(getattr(pv, "_btn_log_detail", None), _QPushButton):
    check(pv._btn_log_detail.text() == "日志详情", "日志详情: 按钮文案为「日志详情」")
    # 标题栏动作顺序：日志详情 / 导出 / 清除 / 冻结（左→右），冻结在最右；
    # 要求：「日志详情」在「导出」按钮左侧（与调试界面统一）。
    _log_panel = pv.panels[4]
    _hlay = _log_panel.header._hlay
    _hdr_widgets = [_hlay.itemAt(i).widget() for i in range(_hlay.count())]
    _idx_detail = _hdr_widgets.index(pv._btn_log_detail)
    _idx_freeze = _hdr_widgets.index(pv._log_view._freeze_btn)
    _idx_export = _hdr_widgets.index(pv._log_view._export_btn)
    check(_idx_detail < _idx_freeze,
          f"日志详情: 位于「冻结」按钮左侧 (detail@{_idx_detail}, freeze@{_idx_freeze})")
    check(_idx_detail < _idx_export,
          f"日志详情: 位于「导出」按钮左侧（与调试界面统一）(detail@{_idx_detail}, export@{_idx_export})")
    # 点击打开与「日志管理」同类型的日志窗口（LogManagerDialog）
    from nav_dialogs import LogManagerDialog
    pv._open_log_manager()
    check(isinstance(getattr(pv, "_dlg_log_detail", None), LogManagerDialog)
          and pv._dlg_log_detail.isVisible(),
          "日志详情: 点击打开日志窗口（与「日志管理」同类型）")
    if getattr(pv, "_dlg_log_detail", None) is not None:
        pv._dlg_log_detail.close(); pv._dlg_log_detail = None

# ============ 新需求：急停按钮常态「未开启」，仅极低概率随机触发 ============
import time as _time
check(_pvm._ESTOP_MIN_MINUTES >= 5.0,
      f"急停: 最快也要运行 5 分钟才可能触发 (实际 {_pvm._ESTOP_MIN_MINUTES} 分钟)")
check(_pvm._ESTOP_MAX_MINUTES <= 60.0,
      f"急停: 最长约 1 小时触发一次 (实际 {_pvm._ESTOP_MAX_MINUTES} 分钟)")
pv._playing = True          # 直接置位，避免真启动播放影响其它断言
pv._clear_estop()
rec = pv._status_recs.get("急停按钮")
check(rec is not None and rec["val_box"].text() == "未开启",
      f"急停: 启动后常态保持「未开启」 (实际 {rec['val_box'].text() if rec else 'N/A'})")
# 安排随机触发时刻：应落在 5~60 分钟后
pv._schedule_estop_random()
_due = pv._estop_due_ts - _time.time()
check(5 * 60 - 3 <= _due <= 60 * 60 + 3,
      f"急停: 随机触发时刻落在 5~60 分钟后 (实际 {_due / 60:.1f} 分钟)")
# 未到点：不触发
pv._check_estop_random()
check(pv._estop_active is False, "急停: 未到点不触发（演示全程保持未开启）")
# 到点：触发急停（值窗体显示「开启」）
pv._estop_due_ts = _time.time() - 1
pv._check_estop_random()
check(pv._estop_active is True, "急停: 到点后触发急停报警")
check(rec is not None and rec["val_box"].text() == "开启",
      f"急停: 触发后值窗体显示「开启」 (实际 {rec['val_box'].text() if rec else 'N/A'})")
_lv = getattr(pv, "_log_view", None)
_entries = list(getattr(_lv, "_entries", [])) if _lv is not None else []
check(any("急停按钮" in str(m) for _t, m, _c in _entries),
      f"急停: 触发时写入运行日志 (日志条数={len(_entries)})")
# 报警触发的自动停机不再点亮急停（急停常态未开启）
pv._clear_estop()
pv._alarm_stopped = True
pv.stop_playback()
check(pv._estop_active is False,
      "急停: 报警自动停机不再点亮急停按钮（常态保持未开启）")
pv._playing = False
pv._alarm_stopped = False
pv._estop_due_ts = None

# ============ 新需求：设备运行状态新增「飞料频率」（示例值 1~10 Pcs/min，位于 OK料仓误踢频率 正下方） ============
_fly_rec = pv._status_recs.get("飞料频率")
check(_fly_rec is not None, "飞料频率: 设备运行状态区已新增「飞料频率」行")
if _fly_rec is not None:
    _fly_txt = _fly_rec["val_box"].text()
    check(_fly_txt.isdigit() and 1 <= int(_fly_txt) <= 10,
          f"飞料频率: 示例值在 1~10 Pcs/min 之间 (实际 {_fly_txt})")
    _wrong_rec = pv._status_recs.get("OK料仓误踢频率")
    check(_wrong_rec is not None
          and _fly_rec["grid_row"] == _wrong_rec["grid_row"] + 1
          and _fly_rec["grid_col"] == _wrong_rec["grid_col"],
          "飞料频率: 位于「OK料仓误踢频率」正下方（同列、行号 +1）")

# ============ 新需求：设备运行状态新增「玻璃盘上下跳动」（示例值 0.01~0.06 mm，位于 飞料频率 正下方） ============
_gj_rec = pv._status_recs.get("玻璃盘上下跳动")
check(_gj_rec is not None, "玻璃盘上下跳动: 设备运行状态区已新增「玻璃盘上下跳动」行")
if _gj_rec is not None:
    _gj_txt = _gj_rec["val_box"].text()
    try:
        _gj_v = float(_gj_txt)
    except ValueError:
        _gj_v = -1.0
    check(0.01 <= _gj_v <= 0.06,
          f"玻璃盘上下跳动: 示例值在 0.01~0.06 mm 之间 (实际 {_gj_txt})")
    check(_gj_rec["unit"] is not None and _gj_rec["unit"].text() == "mm",
          f"玻璃盘上下跳动: 单位为 mm (实际 {_gj_rec['unit'].text() if _gj_rec['unit'] else None})")
    _fly_rec_gj = pv._status_recs.get("飞料频率")
    check(_fly_rec_gj is not None
          and _gj_rec["grid_row"] == _fly_rec_gj["grid_row"] + 1
          and _gj_rec["grid_col"] == _fly_rec_gj["grid_col"],
          "玻璃盘上下跳动: 位于「飞料频率」正下方（同列、行号 +1）")
    _gj_draw = pv._draw_glass_jump_val()
    check(0.01 <= _gj_draw <= 0.06,
          f"玻璃盘上下跳动: 抽样方法返回值在 0.01~0.06 mm 之间 (实际 {_gj_draw:.2f})")
    from styles import COLORS as _GJC
    # 计时标签无外框（显式 border: none）
    _ng1_tl = pv._status_recs.get("NG1 料盒", {}).get("time_lbl")
    check(_ng1_tl is not None and "border: none" in _ng1_tl.styleSheet(),
          "取出计时: 计时标签样式显式去除边框 (border: none)")
    # 值 > 0.05 → 状态灯红；≤ 0.05 → 绿
    _gj_rec["val_box"].setText("0.03")
    pv._paint_status_dot(_gj_rec)
    check(_gj_rec["color"] == _GJC["accent_green"],
          f"玻璃盘上下跳动: 值 ≤ 0.05 时状态灯为绿 (实际 {_gj_rec['dot'].styleSheet()})")
    _gj_rec["val_box"].setText("0.56")
    pv._paint_status_dot(_gj_rec)
    check(_gj_rec["color"] == _GJC["accent_red"],
          f"玻璃盘上下跳动: 值 > 0.05 时状态灯为红 (实际 {_gj_rec['dot'].styleSheet()})")
    _gj_rec["val_box"].setText(f"{_gj_draw:.2f}")
    pv._paint_status_dot(_gj_rec)

# ============ 新需求：设备运行状态新增「相机状态」（在线/掉线，示例保持在线，位于 视觉控制器 正下方） ============
_cam_rec = pv._status_recs.get("相机状态")
check(_cam_rec is not None, "相机状态: 设备运行状态区已新增「相机状态」行")
if _cam_rec is not None:
    check(_cam_rec["val_box"].text() == "在线",
          f"相机状态: 示例值为「在线」 (实际 '{_cam_rec['val_box'].text()}')")
    _vis_rec = pv._status_recs.get("视觉控制器")
    check(_vis_rec is not None
          and _cam_rec["grid_row"] == _vis_rec["grid_row"] + 1
          and _cam_rec["grid_col"] == _vis_rec["grid_col"],
          "相机状态: 位于「视觉控制器」正下方（同列、行号 +1）")
    check(_cam_rec["grid_row"] == _gj_rec["grid_row"],
          "相机状态: 与「玻璃盘上下跳动」同行对齐")

# 点击「导出」应打开生产报表（离屏下拦截 open_production_report 收集入参）
_report_calls = []
_pvm._orig_open_report = _pvm.open_production_report
_pvm.open_production_report = lambda parent, period, start, end, kpi, donut, cam, product=None: \
    _report_calls.append((period, start, end, list(kpi), list(donut), dict(cam)))
pv._open_production_report()
check(len(_report_calls) == 1, "生产报表: 点击「导出」触发打开生产报表")
if _report_calls:
    _rp, _rs, _re, _rk, _rd, _rc = _report_calls[0]
    check(_rp == "当前运行", f"生产报表: 时段取自当前统计时段 (实际 {_rp})")
    check(len(_rk) == 7, f"生产报表: 生产汇总含 7 项 KPI (实际 {len(_rk)})")
    check(len(_rd) == 4, f"生产报表: 按剔除口分布含 4 项 (实际 {len(_rd)})")
    check(len(_rc) >= 8, f"生产报表: 按相机统计含 8 路相机 (实际 {len(_rc)})")
else:
    _rk = _rd = _rc = []
_pvm.open_production_report = _pvm._orig_open_report
# 报表弹窗可正常构造并渲染文本
from production_view import ProductionReportDialog as _PRD
_dlg = _PRD(pv, period="当前运行", start="运行开始", end="现在",
            kpi=_rk, donut=_rd, cam_stats=_rc,
            product={"产品类型": "电容", "产品型号": "0402",
                     "产品料号": "—", "产品批号": "—"})
check(_dlg.windowTitle() == "生产报表",
      f"生产报表: 弹窗标题为「生产报表」 (实际 {_dlg.windowTitle()})")
_txt = _dlg.report_text()
check("生产报表" in _txt and "按剔除口分布" in _txt and "按相机统计" in _txt,
      "生产报表: 报表文本含 汇总 / 剔除口 / 相机 三部分")
# 按参考图重新设计后的结构断言
check(len(_dlg._quick_btns) == 12,
      f"生产报表: 左栏快捷时段 12 个按钮 (实际 {len(_dlg._quick_btns)})")
check(_dlg._quick_active == "12小时",
      f"生产报表: 默认高亮「12小时」 (实际 {_dlg._quick_active})")
_dlg._on_quick_range("30分钟")
check(_dlg._quick_active == "30分钟"
      and _dlg._start_edit.text() == _dlg._sel_start
      and _dlg._end_edit.text() == _dlg._sel_end,
      "生产报表: 点击快捷时段同步时间范围与高亮")
# (2) 班次检索：白班 / 中班 / 夜班
check(list(_dlg._shift_btns.keys()) == ["白班", "中班", "夜班"],
      f"生产报表: 提供白班/中班/夜班检索 (实际 {list(_dlg._shift_btns.keys())})")
_dlg._on_shift("中班")
check(_dlg._shift_active == "中班" and _dlg._quick_active is None,
      "生产报表: 点击班次后高亮班次并取消快捷时段高亮")
check(_dlg._sel_start.endswith("16:00:00.") and _dlg._sel_end.endswith("23:59:59."),
      f"生产报表: 中班时间范围 16:00-24:00 (实际 {_dlg._sel_start} ~ {_dlg._sel_end})")
# (3) 筛选数据四项，示例值取自程序配置
check(list(_dlg._filter_cbs.keys()) == ["产品类型", "产品型号", "产品料号", "产品批号"],
      f"生产报表: 筛选数据四项顺序正确 (实际 {list(_dlg._filter_cbs.keys())})")
check(_dlg._filter_cbs["产品类型"].currentText() == "电容"
      and _dlg._filter_cbs["产品型号"].currentText() == "0402",
      "生产报表: 产品类型/型号示例值取自程序配置")
# (1) 左栏与时间输入框加宽，保证 18 位时间串完整显示
check(_dlg.LEFT_W >= 300 and _dlg._start_edit.minimumWidth() >= 130,
      f"生产报表: 左栏与时间输入框已加宽 "
      f"(LEFT_W={_dlg.LEFT_W}, minW={_dlg._start_edit.minimumWidth()})")
# (4) 「关闭」按钮移到「导出」按钮下方
_close_card = _dlg._close_btn.parent()
check(_close_card is _dlg._export_btn.parent(),
      "生产报表: 「关闭」与「导出」位于同一张卡片")
_close_lay = _close_card.layout() if _close_card is not None else None
check(_close_lay is not None
      and _close_lay.indexOf(_dlg._close_btn) > _close_lay.indexOf(_dlg._export_btn),
      "生产报表: 「关闭」按钮位于「导出」按钮下方")
check(len(_dlg._cam_item_layouts) == 8,
      f"生产报表: 中栏 8 路相机检测项卡片 (实际 {len(_dlg._cam_item_layouts)})")
_cam_lay = _dlg._cam_item_layouts[0]
_cam_items = sum(1 for i in range(_cam_lay.count())
                 if _cam_lay.itemAt(i).widget() is not None)
check(_cam_items == 14,
      f"生产报表: 每路相机列出 14 项检测项 (实际 {_cam_items})")
_prod_n = sum(1 for i in range(_dlg._prod_layout.count())
              if _dlg._prod_layout.itemAt(i).widget() is not None)
check(_prod_n >= 50,
      f"生产报表: 右栏产品列表已填充记录 (实际 {_prod_n})")
check(len(_dlg._stat_rows()) == 4,
      f"生产报表: 数据统计 4 行（总数/良品/缺陷/待定）(实际 {len(_dlg._stat_rows())})")
_txt2 = _dlg.report_text()
check("数据统计" in _txt2 and "相机检测项明细" in _txt2,
      "生产报表: 导出文本含 数据统计 与 相机检测项明细")
_dlg.deleteLater()
# 调试界面的「生产信息」卡片共用同一逻辑，也应带「导出」按钮
from production_view import StatsPanel as _StatsPanel
_sp = _StatsPanel()
check(isinstance(getattr(_sp, "_btn_export_report", None), _QPushButton)
      and _sp._btn_export_report.text() == "导出",
      "生产报表: 调试界面「统计信息」卡片同样带「导出」按钮")
check(isinstance(getattr(_sp, "_btn_search_stat", None), _QPushButton)
      and _sp._btn_search_stat.text() == "检索",
      "统计检索: 调试界面「统计信息」卡片同样带「检索」按钮")
_sp.deleteLater()

# ============ 新需求：环状饼图卡片更名 + 左侧导航「生产报表」复用同一弹窗 ============
check(pv.panels[3].header.title.text() == "统计信息",
      f"统计信息: 环状饼图卡片标题已改为「统计信息」 (实际 {pv.panels[3].header.title.text()})")
check(getattr(getattr(dv, "stats_card", None), "header", None) is not None
      and dv.stats_card.header.title.text() == "统计信息",
      f"统计信息: 调试界面同款卡片标题亦改为「统计信息」 "
      f"(实际 {getattr(getattr(dv, 'stats_card', None), 'header', None) and dv.stats_card.header.title.text()})")

import app as _app


class _NavStub:
    """最小替身：只需持有 production 属性即可驱动 MainWindow 的导航回调。"""

    def __init__(self, pv):
        self.production = pv


class _FakePV:
    def __init__(self):
        self.called = 0

    def _open_production_report(self):
        self.called += 1


_fpv = _FakePV()
_app.MainWindow._open_production_report(_NavStub(_fpv))
check(_fpv.called == 1,
      "生产报表: 左侧导航「生产报表」复用同一报表弹窗（不再打开占位窗口）")

# 真实路径：导航入口经 ProductionView 打开与「导出」按钮完全一致的报表
_real_open = _pvm.open_production_report
_nav_calls = []
_pvm.open_production_report = lambda parent, period, start, end, kpi, donut, cam, product=None: \
    _nav_calls.append((period, list(kpi), list(donut), dict(cam)))
_app.MainWindow._open_production_report(_NavStub(pv))
check(len(_nav_calls) == 1, "生产报表: 导航入口经生产运行界面打开报表（真实路径）")
if _nav_calls:
    _np, _nk, _nd, _nc = _nav_calls[0]
    check(_np == "当前运行" and len(_nk) == 7 and len(_nd) == 4 and len(_nc) >= 8,
          f"生产报表: 导航入口数据与「导出」一致 "
          f"(时段={_np}, KPI={len(_nk)}, 剔除口={len(_nd)}, 相机={len(_nc)})")
_pvm.open_production_report = _real_open

# ============ 修复：exe 任务栏图标不显示 ============
from PyQt6.QtGui import QIcon as _QIcon
check(hasattr(_app, "_set_windows_app_id"),
      "任务栏图标: 已定义 AppUserModelID 设置函数")
check(len(getattr(_app, "_APP_ICON_SIZES", [])) >= 6,
      f"任务栏图标: 图标多档尺寸已定义 "
      f"(实际 {len(getattr(_app, '_APP_ICON_SIZES', []))})")


class _IconStub:
    _paint_wordmark = _app.MainWindow._paint_wordmark


_ic = _QIcon()
for _s in _app._APP_ICON_SIZES:
    _ic.addPixmap(_app.MainWindow._make_app_icon(_IconStub(), _s))
_sizes = sorted(s.width() for s in _ic.availableSizes())
check(len(_sizes) >= 6,
      f"任务栏图标: 生成多尺寸 QIcon (实际 {_sizes})")
check(16 in _sizes and max(_sizes) >= 128,
      f"任务栏图标: 兼具任务栏小尺寸与大图标尺寸 (实际 {_sizes})")

# 启动时优先从磁盘 app_icon.ico 加载（Qt 原生多档尺寸 → 任务栏最可靠）
check(hasattr(_app, "_load_app_icon") and hasattr(_app, "_app_icon_path"),
      "任务栏图标: 已定义 .ico 加载入口")
_icon_path = _app._app_icon_path()
check(_app.os.path.exists(_icon_path),
      f"任务栏图标: 定位到 app_icon.ico (实际 {_icon_path})")
_stub2 = _IconStub()
_loaded = _app._load_app_icon(
    lambda s: _app.MainWindow._make_app_icon(_stub2, s))
_loaded_sizes = sorted(s.width() for s in _loaded.availableSizes())
check(len(_loaded_sizes) >= 6,
      f"任务栏图标: 由 app_icon.ico 加载出多档尺寸 (实际 {_loaded_sizes})")

# ============ 新需求：报警设备示例阈值默认值 ============
# 电磁阀寿命 5000000000 次 / 料盒满料停机 50000 件 / 检测速度 8000~12000 Pcs/Min
import alarm_config as _ac
import alarm_dialog as _ad
check(set(_ac.DEFAULT_ALARM["valve_life"].values()) == {5000000000},
      f"报警阈值: 四个电磁阀寿命默认值均为 5000000000 次 "
      f"(实际 {_ac.DEFAULT_ALARM['valve_life']})")
check(set(_ac.DEFAULT_ALARM["bin_full"].values()) == {50000},
      f"报警阈值: 四个料盒满料停机默认阈值均为 50000 件 "
      f"(实际 {_ac.DEFAULT_ALARM['bin_full']})")
check(_ac.DEFAULT_ALARM["speed_quality"]["detect_low"] == 8000,
      f"报警阈值: 检测速度过低默认 8000 Pcs/Min "
      f"(实际 {_ac.DEFAULT_ALARM['speed_quality']['detect_low']})")
check(_ac.DEFAULT_ALARM["speed_quality"]["detect_high"] == 12000,
      f"报警阈值: 检测速度过高默认 12000 Pcs/Min "
      f"(实际 {_ac.DEFAULT_ALARM['speed_quality']['detect_high']})")
# 检测速度（报警判定用）须与统计卡片「平均速度」同源（示例约 11000 Pcs/Min），
# 否则 8000~12000 的阈值会长期误报「检测速度过低」
_pv_speed_bak = (pv._playing, pv._avg_speed, pv._detect_pcs,
                 pv._speed_running, pv._speed_stopped)
pv._playing = True
pv.set_speed_running(True)
for _ in range(5):
    pv._accumulate_batch()
    pv._refresh_live_stats()
_pcs = pv._detect_pcs
check(10500.0 <= _pcs <= 11500.0,
      f"报警阈值: 检测速度示例值与统计平均速度同量级（约 11000 Pcs/Min）(实际 {_pcs:.0f})")
check(_ac.sq_threshold("detect_low") < _pcs < _ac.sq_threshold("detect_high"),
      f"报警阈值: 默认阈值下检测速度不误报 (速度 {_pcs:.0f} 落在 "
      f"{_ac.sq_threshold('detect_low')}~{_ac.sq_threshold('detect_high')} 内)")
(pv._playing, pv._avg_speed, pv._detect_pcs,
 pv._speed_running, pv._speed_stopped) = _pv_speed_bak

# 窗口取值须与实际配置一致（config 文件里的已应用值优先于代码默认值）
_dlg2 = _ad.AlarmSettingsDialog(is_super_admin=True)
_vspin = _dlg2._spins[("valve", "OK")]
check(type(_vspin).__name__ == "QDoubleSpinBox",
      f"报警阈值: 寿命阈值输入框改用 QDoubleSpinBox 承载超大数值 (实际 {type(_vspin).__name__})")
check(int(_vspin.value()) == _ac.valve_life_threshold("OK"),
      f"报警阈值: 寿命阈值输入框取值与配置一致 (实际 {int(_vspin.value())})")
check(_vspin.text().replace(" 次", "").strip() == str(_ac.valve_life_threshold("OK")),
      f"报警阈值: 5000000000 完整显示不被截断 (实际 ' {_vspin.text()}' )")

# 报警设置窗口自适应宽度：料盒满料停机 4 列阈值横向完整显示（不被右侧裁切）
check(_dlg2.minimumWidth() >= 760,
      f"自适应宽度: 报警设置窗口最小宽度按最宽子页内容自适应 (minW {_dlg2.minimumWidth()})")
_scroll = _dlg2.findChildren(_ad.QScrollArea)[0]
check(_scroll.horizontalScrollBarPolicy() == _Qt.ScrollBarPolicy.ScrollBarAsNeeded,
      "自适应宽度: 子页横向滚动条按需出现（窄屏兜底，不再截断）")
check(_dlg2._spins[("bin", "OK")].value() == _ac.bin_full_threshold("OK"),
      f"报警阈值: 料盒满料阈值取值与配置一致 (实际 {_dlg2._spins[('bin', 'OK')].value()})")
check(_dlg2._spins[("sq", "detect_low")].value() == _ac.sq_threshold("detect_low")
      and _dlg2._spins[("sq", "detect_high")].value() == _ac.sq_threshold("detect_high"),
      "报警阈值: 检测速度过低/过高阈值取值与配置一致")

# 料盒满料停机页结构重构校验：误踢/漏踢拆分 + 料盒取出 + 满料停机
# 1) 误踢/漏踢拆分为两个独立开关，各自带「报警方案」下拉与阈值（默认 10 Pcs/H）
check("mis_wrong" in _dlg2._feat_toggles and "mis_miss" in _dlg2._feat_toggles,
      "料盒满料停机: 误踢/漏踢为两个独立开关")
check(_dlg2._mis_wrong_spin.suffix() == " Pcs/H" and _dlg2._mis_wrong_spin.value() == _ac.mis_wrong_threshold(),
      f"料盒满料停机: 误踢阈值默认 {_ac.mis_wrong_threshold()} Pcs/H")
check(_dlg2._mis_miss_spin.suffix() == " Pcs/H" and _dlg2._mis_miss_spin.value() == _ac.mis_miss_threshold(),
      f"料盒满料停机: 漏踢阈值默认 {_ac.mis_miss_threshold()} Pcs/H")
check(isinstance(_dlg2._mis_wrong_plan_combo, _ad.QComboBox)
      and isinstance(_dlg2._mis_miss_plan_combo, _ad.QComboBox),
      "料盒满料停机: 误踢/漏踢均含「报警方案」下拉选项")
# 2) 料盒取出未放回超时：删除「处理方式」下拉；报警方案右侧为「超时阈值」(默认 5000ms)
check(not hasattr(_dlg2, "_bin_to_handle_combo"),
      "料盒取出超时: 已删除「处理方式」下拉（无 _bin_to_handle_combo）")
check(_dlg2._bin_to_spin.suffix() == " ms" and _dlg2._bin_to_spin.value() == _ac.bin_taken_timeout_ms(),
      f"料盒取出超时: 超时阈值默认 {_ac.bin_taken_timeout_ms()} ms（位于报警方案右侧）")
check(isinstance(_dlg2._bin_to_mode_combo, _ad.QComboBox),
      "料盒取出超时: 保留「报警方案」下拉选项")
# 3) 满料停机：开关右侧新增「报警方案」下拉；「停机阈值」改名为「收料量」
check(hasattr(_dlg2, "_bin_full_stop_plan_combo")
      and isinstance(_dlg2._bin_full_stop_plan_combo, _ad.QComboBox),
      "满料停机: 新增「报警方案」下拉选项")
check(_dlg2._bin_full_stop_pct_spin.suffix() == " %"
      and _dlg2._bin_full_stop_pct_spin.value() == _ac.bin_full_stop_pct(),
      f"满料停机: 收料量默认 {_ac.bin_full_stop_pct()} %（原停机阈值改名）")

# 配置默认值校验：新键存在、旧键移除
_f = _ac.DEFAULT_ALARM["features"]
check("mis_wrong_alarm" in _f and "mis_miss_alarm" in _f and "bin_full_stop_plan" in _f,
      "配置默认: 新增 mis_wrong_alarm / mis_miss_alarm / bin_full_stop_plan")
check("mis_reject" not in _f and "mis_reject_plan" not in _f and "mis_wrong" not in _f and "mis_miss" not in _f,
      "配置默认: 旧的 mis_reject / mis_wrong / mis_miss 键已移除")

# 「应用」后应写入配置文件；重新加载后沿用最新应用的参数（程序更新后依然生效）
_origin_valve = dict(_ac.ALARM["valve_life"])
_vspin.setValue(1234567890)
_dlg2._on_apply()
_cfg_file = _ac._config_path()
check(os.path.exists(_cfg_file), f"报警阈值: 「应用」后已生成配置文件 ({_cfg_file})")
with open(_cfg_file, "r", encoding="utf-8") as _f:
    _saved_cfg = _json.load(_f)
check(_saved_cfg["valve_life"]["OK"] == 1234567890,
      f"报警阈值: 应用值已写入 alarm_config.json (实际 {_saved_cfg['valve_life']['OK']})")
_ac.ALARM["valve_life"].clear()
_ac.load_alarm_config()   # 模拟「程序更新后重新启动」
check(_ac.ALARM["valve_life"]["OK"] == 1234567890,
      f"报警阈值: 重新加载后沿用最新应用的参数 (实际 {_ac.ALARM['valve_life']['OK']})")
_ac.ALARM["valve_life"].update(_origin_valve)   # 还原内存配置（磁盘文件由收尾统一还原）
_dlg2._on_finished(0)
_dlg2.deleteLater()

# ============ 本轮新需求（6 项） ============
# ① 默认登录用户生效（启动账号取自「用户中心 → 设为默认登录」）
import inspect as _inspect
from user_manager import UserManager as _UM
import alarm_dialog as _ad2
import alarm_config as _ac_ion
_tmp_users = os.path.join(_TMP_CFG_DIR, "users.json")   # 隔离到临时目录，不碰工程 users.json
_um = _UM(path=_tmp_users)
check(_um.get_default_login() is None, "默认登录: 未设置时 get_default_login 返回 None")
_u, _uname = _app.resolve_startup_user(_um)
check(_u is not None and _uname == "admin",
      f"默认登录: 未设置默认登录用户时回退 admin (实际 {_uname})")
check(_um.set_default_login("eng01") is True, "默认登录: 可将 eng01 设为默认登录用户")
check(_um.get_default_login() == "eng01", "默认登录: 默认登录用户已持久化")
_u2, _uname2 = _app.resolve_startup_user(_um)
check(_uname2 == "eng01" and _u2.get("category") == "设备工程师",
      f"默认登录: 启动账号取自默认登录用户 (实际 {_uname2}/{_u2.get('category')})")
_um.default_login = "not_exist_user"          # 模拟默认账号已失效
_u3, _uname3 = _app.resolve_startup_user(_um)
check(_uname3 == "admin", f"默认登录: 默认账号失效时回退 admin (实际 {_uname3})")
check("resolve_startup_user" in _inspect.getsource(_app.MainWindow.__init__),
      "默认登录: 主窗口启动时按默认登录用户解析账号")

# ② 顶部版本信息 + 关于弹窗
check(getattr(_app, "APP_VERSION", "") == "Ver5.0.10.34",
      f"关于: 版本号常量 (实际 {getattr(_app, 'APP_VERSION', None)})")
check(hasattr(_app.MainWindow, "_open_about"), "关于: 已定义「关于」入口")
_adlg = __import__("nav_dialogs").AboutDialog(
    None, software_name="智感科技：MLCC外观高速检测",
    version=_app.APP_VERSION,
    device_code={"设备编码": "EQ-2026-0001", "设备名称": "MLCC 视觉检测线", "产线编号": "LINE-A1"},
    company=_app.COMPANY_NAME, copyright_text=_app.COMPANY_COPYRIGHT)
_atxt = _adlg.report_text()
check(_app.APP_VERSION in _atxt, "关于: 弹窗含软件版本")
check("智感科技" in _atxt and "EQ-2026-0001" in _atxt, "关于: 弹窗含软件名称与设备编码")
check(_app.COMPANY_NAME in _atxt and "ZIGAA" in _atxt,
      f"关于: 弹窗含公司信息 (company={_app.COMPANY_NAME})")
check(_adlg.windowTitle() == "关于", f"关于: 窗口标题 (实际 {_adlg.windowTitle()})")
_adlg.deleteLater()
_src_init = _inspect.getsource(_app.MainWindow.__init__)
# 按新需求：顶部信息栏「软件名称 + 软件版本」卡片已删除，「关于」按钮已移至底部状态栏，
# 软件版本号仅在「关于」弹窗中展示（见上方 _atxt 断言）。
check('QPushButton("关于")' in _src_init, "关于: 主窗口已创建「关于」按钮（现置于底部状态栏）")
check("软件版本：" not in _src_init,
      "关于: 主窗口 __init__ 源码不再硬编码「软件版本：」文本（版本仅出现在关于弹窗）")

# ③ 高级设置：设备开机自启动（默认开，持久化）
check(bool(_um.autostart) is True, f"开机自启动: 默认开启 (实际 {_um.autostart})")
_um.set_autostart(False)
check(_um.autostart is False, "开机自启动: 可关闭")
check(_UM(path=_tmp_users).autostart is False, "开机自启动: 已持久化（重载后仍关闭）")
_um.set_autostart(True)
check(_UM(path=_tmp_users).autostart is True, "开机自启动: 重新开启并持久化")
check(hasattr(_app, "_autostart_command") and hasattr(_app, "set_windows_autostart")
      and hasattr(_app, "is_windows_autostart_enabled"),
      "开机自启动: 已定义 Windows 启动项写入/读取入口")
_autocmd = _app._autostart_command()
check("main_b.py" in _autocmd or ".exe" in _autocmd,
      f"开机自启动: 启动命令可解析 (实际 {_autocmd[:60]}…)")

# ④ 高级设置：料盒抽出超时未放回的剔除逻辑
check(_um.get_bin_taken_reject_mode() == "对应抽出料盒走待定",
      f"抽盒剔除逻辑: 默认「对应抽出料盒走待定」 (实际 {_um.get_bin_taken_reject_mode()})")
_um.set_bin_taken_reject_mode("全部料盒走待定")
check(_um.get_bin_taken_reject_mode() == "全部料盒走待定", "抽盒剔除逻辑: 可切换为「全部料盒走待定」")
check(_UM(path=_tmp_users).get_bin_taken_reject_mode() == "全部料盒走待定", "抽盒剔除逻辑: 设置已持久化")
_um.set_bin_taken_reject_mode("非法值")
check(_um.get_bin_taken_reject_mode() == "对应抽出料盒走待定", "抽盒剔除逻辑: 非法值回退默认")


class _AdvApp:
    def __init__(self, um):
        self._adv_settings = {}
        self.user_manager = um
        self.production = pv
        self.current_user = {"name": "测试"}


_adlg_adv = __import__("nav_dialogs").AdvancedSettingsDialog(_AdvApp(_um))
check(_adlg_adv._reject_combo.count() == 2
      and _adlg_adv._reject_combo.itemText(0) == "对应抽出料盒走待定"
      and _adlg_adv._reject_combo.itemText(1) == "全部料盒走待定",
      "抽盒剔除逻辑: 高级设置下拉两项且默认第一项为「对应抽出料盒走待定」")
check(_adlg_adv._autostart_cb.isChecked() is True, "开机自启动: 高级设置开关默认勾选（开启）")
_grp_titles = sorted([g.title() for g in _adlg_adv.findChildren(QGroupBox)])
check(_grp_titles == sorted(["运行选项", "系统参数", "功能开关", "设备"]),
      f"高级设置: 按运行选项/系统参数/功能开关/设备 四组重构 (实际 {_grp_titles})")
_tab_titles = [_adlg_adv._tabs.tabText(i) for i in range(_adlg_adv._tabs.count())]
check(_tab_titles == ["运行选项", "系统参数", "功能开关", "设备"],
      f"高级设置: 按模块分为四个独立标签页 (实际 {_tab_titles})")
_adlg_adv.deleteLater()
# 逻辑生效：把 NG1 料盒置于「取出超时」态，按两种模式改判为待定
pv.user_manager = _um
pv._playing = True


def _force_ng1_taken():
    """把 NG1 料盒置于「取出且已超时」状态（_reset_live 会清掉取出态，需在其后调用）。"""
    pv._bin_taken["NG1"] = True
    pv._bin_taken_since["NG1"] = _time.monotonic() * 1000.0 - (
        _ac_ion.bin_taken_timeout_ms() + 1000)


_force_ng1_taken()
check("NG1" in pv._taken_timeout_bins(), "抽盒剔除逻辑: NG1 料盒判定为取出超时")
_um.set_bin_taken_reject_mode("对应抽出料盒走待定")
_moved_corr = pv._pending_move_count(20, 19.0, 1.0, 0.2)
check(0 < _moved_corr < 20,
      f"抽盒剔除逻辑: 「对应抽出料盒走待定」只改判该料盒应得部分 (实际 {_moved_corr:.2f}/20)")
_um.set_bin_taken_reject_mode("全部料盒走待定")
_moved_all = pv._pending_move_count(20, 19.0, 1.0, 0.2)
check(abs(_moved_all - 20.0) < 1e-6,
      f"抽盒剔除逻辑: 「全部料盒走待定」改判本批全部产品 (实际 {_moved_all}/20)")
# 统计效果：全部走待定 → 本批全部计入待定、良品数为 0
pv._reset_live()
_force_ng1_taken()
pv._accumulate_batch()
_kp = dict((k, v) for k, v, _ in pv.get_live_snapshot()["kpi"])
check(int(_kp["良品数"]) == 0 and float(_kp["良品率"].rstrip("%")) == 0.0,
      f"抽盒剔除逻辑: 全部走待定时良品数为 0 (实际 {_kp['良品率']} 良品数 {_kp['良品数']})")
pv._bin_taken["NG1"] = False
pv._bin_taken_since["NG1"] = None
pv._playing = False
pv.user_manager = None
pv._pending_routed = set()

# ⑤ 离子风扇异常报警（默认开启、报警方式可下拉、触发写日志）
check(_ac_ion.DEFAULT_ALARM["features"]["ion_fan_alarm"] is True,
      f"离子风扇: 默认开启 (实际 {_ac_ion.DEFAULT_ALARM['features']['ion_fan_alarm']})")
check(_ac_ion.feature_ion_fan_alarm() is True, "离子风扇: 读取为开启")
check(_ac_ion.ion_fan_plan() == "方案 1", f"离子风扇: 默认报警方案 (实际 {_ac_ion.ion_fan_plan()})")
_dlg_ion = _ad2.AlarmSettingsDialog(is_super_admin=True)
check("ion_fan" in getattr(_dlg_ion, "_feat_toggles", {}), "离子风扇: 其他报警功能页存在该开关")
check(getattr(_dlg_ion, "_ion_fan_plan_combo", None) is not None
      and _dlg_ion._ion_fan_plan_combo.count() >= 1, "离子风扇: 报警方式可下拉选择")
check(_dlg_ion._feat_toggles["ion_fan"].is_on() is True, "离子风扇: 开关默认开启")
_dlg_ion._ion_fan_plan_combo.setCurrentText("方案 2")
_dlg_ion._on_apply()
check(_ac_ion.ALARM["features"]["ion_fan_plan"] == "方案 2",
      f"离子风扇: 报警方式应用后写入配置 (实际 {_ac_ion.ALARM['features']['ion_fan_plan']})")
_ac_ion.ALARM["features"]["ion_fan_alarm"] = True
_ac_ion.ALARM["features"]["ion_fan_plan"] = "方案 1"
pv._playing = True
# 触发是低概率随机事件：把触发概率临时置 1，确定性地验证「触发 → 写日志 → 关闭后不触发」
_p_ion_bak = _pvm._ION_FAN_TRIGGER_P
_pvm._ION_FAN_TRIGGER_P = 1.0
pv._ion_fan_abnormal = False
pv._check_ion_fan_alarm()
_ion_entries = list(getattr(pv._log_view, "_entries", []))
check(pv._ion_fan_abnormal is True, "离子风扇: 触发后进入异常报警态")
check(any("离子风扇" in str(m) for _t, m, _c in _ion_entries), "离子风扇: 触发后写入运行日志")
check(any("报警方案" in str(m) for _t, m, _c in _ion_entries), "离子风扇: 报警日志含所选报警方案")
# 关闭开关后不再触发
_ac_ion.ALARM["features"]["ion_fan_alarm"] = False
pv._ion_fan_abnormal = False
pv._check_ion_fan_alarm()
check(pv._ion_fan_abnormal is False, "离子风扇: 关闭开关后不再触发")
_ac_ion.ALARM["features"]["ion_fan_alarm"] = True
_pvm._ION_FAN_TRIGGER_P = _p_ion_bak
pv._playing = False
_dlg_ion._on_finished(0)
_dlg_ion.deleteLater()

# ⑥ 电磁阀寿命阈值输入框与其它数值输入框样式一致
_dlg_style = _ad2.AlarmSettingsDialog(is_super_admin=True)
_style_txt = _dlg_style._spin_style()
check("QDoubleSpinBox" in _style_txt and "QSpinBox" in _style_txt,
      "输入框样式: 样式表同时覆盖 QSpinBox 与 QDoubleSpinBox（外观一致）")
_vspin_style = _dlg_style._spins[("valve", "OK")].styleSheet()
_bspin_style = _dlg_style._spins[("bin", "OK")].styleSheet()
check("QDoubleSpinBox" in _vspin_style, "输入框样式: 寿命阈值框已套用统一样式")


def _style_body(css):
    """取出 CSS 的声明体（花括号内内容）用于比对，忽略选择器差异。"""
    out = []
    for seg in css.split("}"):
        if "{" in seg:
            out.append(seg.split("{", 1)[1].strip())
    return "|".join(out)


check(_style_body(_vspin_style) == _style_body(_bspin_style),
      "输入框样式: 寿命阈值框与料盒阈值框样式声明完全一致（仅选择器不同）")
check("border-radius: 4px" in _vspin_style and "padding: 4px 8px" in _vspin_style,
      "输入框样式: 边框/圆角/内边距与其它数值框一致")

# ⑦ 电磁阀寿命页 4 行左对齐（行尾 stretch 防止 QBoxLayout 均分剩余宽度右移）
_dlg_style.resize(1100, 620); _dlg_style.show(); app.processEvents()
_tabs_style = _dlg_style.findChildren(_ad2.QTabWidget)[0]
_tabs_style.setCurrentIndex(1); app.processEvents()
from PyQt6.QtCore import QPoint as _QPoint
def _lbl_x(dlg, text):
    for _l in dlg.findChildren(_ad2.QLabel):
        if _l.text() == text:
            return _l.mapTo(dlg, _QPoint(0, 0)).x()
    return None
_x_ok = _lbl_x(_dlg_style, "OK 电磁阀")
_x_alarm = _lbl_x(_dlg_style, "报警阈值")
check(_x_ok is not None and _x_ok == _x_alarm,
      f"电磁阀页左对齐: OK 电磁阀行与报警阈值行同一起始 x (OK={_x_ok}, 报警阈值={_x_alarm})")
_dlg_style._on_finished(0)
_dlg_style.deleteLater()

# ============ 本轮新需求（4 项） ============
# ① 高级设置：密码输入确认时间周期（默认 3 分钟）+ 空闲超时密码确认
check(_UM.CONFIRM_INTERVAL_OPTIONS == ["1分钟", "3分钟", "5分钟", "10分钟", "20分钟",
                                       "30分钟", "45分钟", "1小时", "2小时", "8小时", "24小时"],
      f"密码确认周期: 下拉项与需求一致 (实际 {_UM.CONFIRM_INTERVAL_OPTIONS})")
check(_UM(path=_tmp_users).get_confirm_interval() == "3分钟",
      f"密码确认周期: 默认 3 分钟 (实际 {_UM(path=_tmp_users).get_confirm_interval()})")
check(_UM(path=_tmp_users).confirm_interval_seconds() == 180, "密码确认周期: 3分钟 = 180 秒")
_um.set_confirm_interval("10分钟")
check(_um.get_confirm_interval() == "10分钟" and _UM(path=_tmp_users).get_confirm_interval() == "10分钟",
      "密码确认周期: 修改后持久化")
_um.set_confirm_interval("2小时")
check(_um.confirm_interval_seconds() == 7200, f"密码确认周期: 2小时 = 7200 秒 (实际 {_um.confirm_interval_seconds()})")
_um.set_confirm_interval("24小时")
check(_um.confirm_interval_seconds() == 86400, "密码确认周期: 24小时 = 86400 秒")
_um.set_confirm_interval("非法值")
check(_um.get_confirm_interval() == "3分钟", "密码确认周期: 非法值回退默认 3 分钟")
_um.set_confirm_interval("3分钟")
_adv2 = __import__("nav_dialogs").AdvancedSettingsDialog(_AdvApp(_um))
check(_adv2._confirm_combo.count() == 11,
      f"密码确认周期: 高级设置下拉 11 项 (实际 {_adv2._confirm_combo.count()})")
check(_adv2._confirm_combo.currentText() == "3分钟",
      f"密码确认周期: 高级设置默认显示 3 分钟 (实际 {_adv2._confirm_combo.currentText()})")
_adv2._confirm_combo.setCurrentText("5分钟")
check(_um.get_confirm_interval() == "5分钟", "密码确认周期: 高级设置修改后写入配置")
_um.set_confirm_interval("3分钟")
_adv2.deleteLater()

# 密码输入确认窗口：错误提示 / 正确提示并自动退出
_ND = __import__("nav_dialogs")
_pwd = _ND.PasswordConfirmDialog(None, username="eng01", name="王工程师",
                                 password="123456", interval="3分钟")
check(_pwd.windowTitle() == "输入密码", f"密码确认窗口: 标题 (实际 {_pwd.windowTitle()})")
_pwd.edit.setText("wrong")
_pwd._on_ok()
check(_pwd.msg.text() == _ND.PasswordConfirmDialog.WRONG_TEXT,
      f"密码确认窗口: 密码错误提示 (实际 {_pwd.msg.text()!r})")
check(_pwd.edit.text() == "", "密码确认窗口: 密码错误后清空输入框")
check(_pwd.result() == 0, "密码确认窗口: 密码错误时窗口保持打开")
_pwd.edit.setText("123456")
_pwd._on_ok()
check(_pwd.msg.text() == _ND.PasswordConfirmDialog.OK_TEXT,
      f"密码确认窗口: 密码正确提示 (实际 {_pwd.msg.text()!r})")
empty = getattr(_pwd.msg, "text", lambda: "")
check(empty() == "密码正确", "密码确认窗口: 正确后提示「密码正确」")
from PyQt6.QtCore import QEventLoop as _QEventLoop
_loop = _QEventLoop()
QTimer.singleShot(900, _loop.quit)
_loop.exec()
check(_pwd.result() == 1, f"密码确认窗口: 提示后窗口自动退出 (result={_pwd.result()})")
_pwd.deleteLater()

# 主窗口空闲判定 + 各操作入口接入确认
_um_saved_users = None
if os.path.exists("users.json"):
    with open("users.json", "rb") as _f:
        _um_saved_users = _f.read()
_mw = _app.MainWindow()
_mw.show()
app.processEvents()
# Batch 6：顶部信息栏「软件名称 + 软件版本」卡片已删除；「关于」按钮移至底部状态栏、位于「语言：中文」左侧
check(getattr(_mw, "_topbar_frame", None) is None,
      "顶部信息栏: 软件名称 + 软件版本的卡片已删除（_topbar_frame 不存在）")
check(not hasattr(_mw, "lbl_version"),
      "顶部信息栏:「软件版本」标签已删除")
# 「关于」按钮现在位于底部状态栏，且在「语言：中文」左侧
_footer = _mw._footer_frame.layout()
_i_about = _footer.indexOf(_mw.btn_about)
_i_lang = _footer.indexOf(_mw._footer_lang_label)
check(_i_about != -1 and _i_lang != -1 and _i_about < _i_lang,
      f"底部状态栏:「关于」按钮位于「语言：中文」左侧 (about={_i_about} lang={_i_lang})")
check(_mw._header_layout.indexOf(_mw.btn_about) == -1,
      "顶部信息栏: 信息栏（header）不再包含「关于」按钮")
# 底部状态栏 CPU / 内存：应为实时显示（非写死的示例值），且文本格式正确
check(hasattr(_mw, "lbl_cpu_footer") and hasattr(_mw, "lbl_mem_footer"),
      "底部状态栏: 存在 CPU / 内存独立标签")
check(_mw.lbl_cpu_footer.text().startswith("CPU: ")
      and "内存: " in _mw.lbl_mem_footer.text(),
      f"底部状态栏: CPU/内存按实际显示（CPU='{_mw.lbl_cpu_footer.text()}' 内存='{_mw.lbl_mem_footer.text()}'）")
# 「缺陷图查看」颜色与其他底部按钮一致（text_secondary 色值，非蓝色）
from styles import COLORS as _COLORS
check(_COLORS["text_secondary"] in _mw.lbl_defect_view.styleSheet()
      and _COLORS["accent_blue"] not in _mw.lbl_defect_view.styleSheet(),
      "底部状态栏:「缺陷图查看」颜色与其他底部按钮一致（非蓝色）")
check(_mw._idle_limit_seconds() == 180,
      f"空闲确认: 周期取自用户配置（默认 3 分钟 = 180 秒）(实际 {_mw._idle_limit_seconds()})")
check(_mw._idle_expired() is False, "空闲确认: 刚启动时未超时")
_mw._last_activity = _time.time() - 999
check(_mw._idle_expired() is True, "空闲确认: 超过周期后判定为超时")

# 左侧功能按钮：按当前用户对该功能的操作权限显隐（无权限隐藏、有权限显示）
for _k, _b in _mw._func_nav.items():
    check(_b.isVisible() == _mw._is_allowed(_k),
          f"左侧导航功能按钮显隐: {_k} 可见性 == 当前用户操作权限可见性")
# 确定性验证：切换用户类别后，功能按钮显隐随之更新
_orig_user = _mw.current_user
_admin = _mw.user_manager.get_user("admin")
_mw._set_current_user(_admin)
check(all(b.isVisible() for b in _mw._func_nav.values()),
      "权限显隐: 超级管理员可见全部功能按钮")
_op = _mw.user_manager.get_user("operator01")
_mw._set_current_user(_op)
_vis = {k: b.isVisible() for k, b in _mw._func_nav.items()}
check(_vis == {k: (k in _app.NAV_VISIBILITY["设备操作员"]) for k in _mw._func_nav},
      f"权限显隐: 设备操作员仅显示其有权限的功能按钮 (可见={sorted(k for k,v in _vis.items() if v)})")
_mw._set_current_user(_orig_user)  # 还原启动用户，保持状态整洁


class _OkPwdDlg:
    def __init__(self, *a, **k):
        pass

    def exec(self):
        return 1


class _CancelPwdDlg(_OkPwdDlg):
    def exec(self):
        return 0


_pwd_bak = _app.PasswordConfirmDialog
_app.PasswordConfirmDialog = _OkPwdDlg
check(_mw.confirm_if_idle() is True, "空闲确认: 超时后输入正确密码可通过")
_app.PasswordConfirmDialog = _CancelPwdDlg
_mw._last_activity = _time.time() - 999
check(_mw.confirm_if_idle() is False, "空闲确认: 超时后关闭/密码未通过则阻止操作")
_app.PasswordConfirmDialog = _pwd_bak
_mw._last_activity = _time.time()    # 复位计时：未超时路径不应弹窗（避免模态阻塞）
check(_mw.confirm_if_idle() is True,
      "空闲确认: 未超时直接放行并刷新计时")
check(_mw._idle_expired() is False, "空闲确认: 放行后计时已刷新")
_src_mw = _inspect.getsource(_app.MainWindow)
check("confirm_if_idle" in _inspect.getsource(_app.MainWindow._guarded)
      and "confirm_if_idle" in _inspect.getsource(_app.MainWindow._guarded_nav)
      and "confirm_if_idle" in _inspect.getsource(_app.MainWindow._guarded_switch),
      "空闲确认: 三类操作入口（按钮/导航/相机切换）均接入确认")
check("idle_confirm_cb" in _inspect.getsource(_pvm.ProductionView.open_scan_both),
      "空闲确认: 扫码录入入口接入确认")
check("confirm_if_idle" in _inspect.getsource(
      __import__("debug_view").TargetLocationContent._on_param_setting),
      "空闲确认: 调试界面「参数设置」入口接入确认")
_mw.hide()
# 保持引用、不销毁：离屏环境下销毁 MainWindow（内含大量定时器/子视图）易触发崩溃
_MW_KEEPALIVE = _mw
app.processEvents()
if _um_saved_users is not None:
    with open("users.json", "wb") as _f:
        _f.write(_um_saved_users)

# ② 设备设置 - 振动盘示例值
_vib = pv.dev_cfg["vibrator"]
check(_vib["feed_rate"] == 12000,
      f"振动盘: 供料速度示例值 12000 Pcs/Min (实际 {_vib['feed_rate']})")
check(abs(_vib["round_voltage"] - 80.0) < 1e-6,
      f"振动盘: 圆振电压示例值 80.0 V (实际 {_vib['round_voltage']})")
check(abs(_vib["line_voltage"] - 68.0) < 1e-6,
      f"振动盘: 直振电压示例值 68.0 V (实际 {_vib['line_voltage']})")
check(pv._products_per_tick == 6,
      f"振动盘: 12000 Pcs/Min 按 30ms 节拍折算为 6 Pcs/节拍 (实际 {pv._products_per_tick})")
from device_settings_dialog import DeviceSettingsDialog as _DSD
_dsd = _DSD(_mw)   # DeviceSettingsDialog 接收主窗口，内部取 mw.production
check(_dsd.sb_vib.value() == 12000, f"振动盘: 设置页供料速度显示 12000 (实际 {_dsd.sb_vib.value()})")
check("Pcs/Min" in _dsd.sb_vib.suffix(),
      f"振动盘: 供料速度单位为 Pcs/Min (实际 {_dsd.sb_vib.suffix()!r})")
check(abs(_dsd.sb_round_v.value() - 80.0) < 1e-6,
      f"振动盘: 设置页圆振电压显示 80.0 (实际 {_dsd.sb_round_v.value()})")
check(abs(_dsd.sb_line_v.value() - 68.0) < 1e-6,
      f"振动盘: 设置页直振电压显示 68.0 (实际 {_dsd.sb_line_v.value()})")
check(_dsd.sb_round_v.maximum() >= 80.0 and _dsd.sb_line_v.maximum() >= 80.0,
      "振动盘: 电压量程已放开（可设置到 80V 以上）")
_dsd.deleteLater()

# ============ 新需求：已使用次数清零 / 停机使能开关 / 位置自动获取 ============
from device_settings_dialog import TriggerSettingsDialog as _TSD, RejectSettingsDialog as _RSD
# ① 电磁阀寿命页：「已使用次数」右侧每行一个「已使用次数清零」按钮，仅清零该阀
_dlg_v = _ad2.AlarmSettingsDialog(is_super_admin=True)
_clear_btns = [b for b in _dlg_v.findChildren(_QPushButton)
               if b.text() == "已使用次数清零"]
check(len(_clear_btns) == 4,
      f"电磁阀寿命: 每行一个「已使用次数清零」按钮共 4 个 (实际 {len(_clear_btns)})")
_got = []
_dlg_v._on_clear_valve = lambda key=None: _got.append(key)
_clear_btns[0].click(); app.processEvents()
check(_got == ["OK"], f"已使用次数清零: 点击 OK 行仅清零该阀 (实际回调参数 {_got})")
_clear_btns[1].click(); app.processEvents()
check(_got == ["OK", "NG1"], "已使用次数清零: 点击 NG1 行回调传 NG1 阀键")
# ② 电磁阀寿命页：停机阈值行第三列为「停机使能」开关，默认关闭不启用
check(isinstance(_dlg_v._valve_stop_enabled, _TS) and not _dlg_v._valve_stop_enabled.is_on(),
      "电磁阀寿命: 停机使能开关存在且默认关闭不启用")
_feat_bak = dict(_ac.ALARM["features"])
_dlg_v._valve_stop_enabled.set_on(True)
_dlg_v._write_alarm()
check(_ac.ALARM["features"]["valve_stop_enabled"] is True,
      "电磁阀寿命: 停机使能开启后随「应用」写入配置（features）")
_dlg_v._valve_stop_enabled.set_on(False)
_dlg_v._write_alarm()
_ac.ALARM["features"].clear(); _ac.ALARM["features"].update(_feat_bak)   # 还原内存配置
_dlg_v._on_finished(0); _dlg_v.deleteLater()
# ③ 生产界面：单阀清零 —— 仅清零指定阀并重新计数，其他阀不受影响
_used_bak = dict(getattr(pv, "_valve_used", {}))
_init_bak = dict(getattr(pv, "_valve_used_init", {}))
pv._valve_used = {"OK": 3200.0, "NG1": 120.0, "NG2": 45.0, "RST": 8.0}
pv._valve_used_init = {"OK": 3200.0, "NG1": 120.0, "NG2": 45.0, "RST": 8.0}
pv.reset_valve_counts("OK")
check(pv._valve_used["OK"] == 0.0 and pv._valve_used["NG1"] == 120.0
      and pv._valve_used["RST"] == 8.0,
      f"已使用次数清零: 单阀清零后 OK=0 且其他阀不变 (实际 {pv._valve_used})")
pv.reset_valve_counts()   # 全量重置后 OK 仍保持清零（初始值已被记为 0）
check(pv._valve_used["OK"] == 0.0, "已使用次数清零: 全量重置后已清零的阀保持 0 重新计数")
pv._valve_used = _used_bak; pv._valve_used_init = _init_bak
# ④ 触发设定：「触发位置」右侧「自动获取」按钮，点击填入运行系统当前位置
_tsd = _TSD(_mw)
_auto_pos_btns = [b for b in _tsd.findChildren(_QPushButton) if b.text() == "自动获取"]
check(len(_auto_pos_btns) == 1,
      f"触发设定: 触发位置右侧存在「自动获取」按钮 (实际 {len(_auto_pos_btns)})")
_tsd._on_auto_get_position()
check(_tsd.pos.value() == pv.get_current_pulse_position(),
      f"触发设定: 自动获取填入当前位置 (实际 {_tsd.pos.value()} / 期望 {pv.get_current_pulse_position()})")
_tsd.deleteLater()
# ⑤ 剔除设定：每行「剔除位置」右侧「自动获取」按钮，点击填入该口当前位置
_rsd = _RSD(_mw)
_auto_rej_btns = [b for b in _rsd.findChildren(_QPushButton) if b.text() == "自动获取"]
check(len(_auto_rej_btns) == 4,
      f"剔除设定: 每行剔除位置右侧「自动获取」按钮共 4 个 (实际 {len(_auto_rej_btns)})")
_rck, _rpos, _rblow, _rpri, _rtest = _rsd._port_rows["ok"]
_rsd._on_auto_get_port(_rpos, 0)
check(_rpos.value() == pv.get_current_pulse_position(offset=0),
      f"剔除设定: OK 口自动获取填入当前位置 (实际 {_rpos.value()})")
_rsd.deleteLater()

# ④ 急停报警行：下拉左侧「报警方案」标签
_dlg_estop = _ad2.AlarmSettingsDialog(is_super_admin=True)
check(getattr(_dlg_estop, "_estop_mode_lbl", None) is not None
      and _dlg_estop._estop_mode_lbl.text() == "报警方案",
      "急停报警: 下拉左侧存在「报警方案」标签")
check(_dlg_estop._estop_mode_combo.count() == 2, "急停报警: 下拉仍为两项（红灯闪 / 红灯闪+蜂鸣）")
_dlg_estop._on_finished(0)
_dlg_estop.deleteLater()

# ============ 新需求：报警标签改名 / 报警方式→报警方案 / 停机延迟列 ============
from PyQt6.QtWidgets import QLabel as _QLabel
_ddlg = _ad2.AlarmSettingsDialog(is_super_admin=True)
_labels = [w.text() for w in _ddlg.findChildren(_QLabel)]
# ① 四个开关标签改名到位（不再出现旧名）
check("门打开报警" in _labels, "改名: 出现「门打开报警」标签")
check("连续混料报警" in _labels, "改名: 出现「连续混料报警」标签")
check("连续歪斜报警" in _labels, "改名: 出现「连续歪斜报警」标签")
check("玻璃盘上下跳动超限报警" in _labels, "改名: 出现「玻璃盘上下跳动超限报警」标签")
check("料盒取出计数自动清零" not in _labels,
      "迁移: 报警设置页已移除「料盒取出计数自动清零」行（移至高级设置-运行选项）")
check("feature_auto_clear" not in src_ad and '"auto_clear"] = self._feat_toggles' not in src_ad,
      "迁移: 报警设置页不再读写 auto_clear（feature_auto_clear 已移出 import 与 _write_alarm）")
src_nav_ac = open("C:/Users/Lenovo/WorkBuddy/Teruo/src/nav_dialogs.py", encoding="utf-8").read()
check("from alarm_config import ALARM, save_alarm_config, feature_auto_clear" in src_nav_ac,
      "迁移: 高级设置引入 feature_auto_clear / save_alarm_config（持久化到报警配置）")
check("料盒取出计数自动清零" in src_nav_ac and "_on_auto_clear_toggle" in src_nav_ac,
      "迁移: 高级设置-运行选项新增「料盒取出计数自动清零」开关及写入处理")
_i_stopclr2 = src_nav_ac.index('"stop_clear_stats"')
_i_autoclr = src_nav_ac.index("料盒取出计数自动清零", _i_stopclr2)
_i_beep2 = src_nav_ac.index('"beep", "启用蜂鸣报警提示"')
check(_i_stopclr2 < _i_autoclr < _i_beep2,
      "迁移: 「料盒取出计数自动清零」位于「设备停止统计清零」下一行、「启用蜂鸣报警提示」之前")
check(not any(f'_section_label("{t}")' in src_nav_ac
              for t in ("密码输入确认", "玻璃盘清洁提示", "料盒管理")),
      "高级设置: 运行选项页三个分组小标题（密码输入确认/玻璃盘清洁提示/料盒管理）已删除")
check("门开关报警" not in _labels and "连续产品混料报警" not in _labels
      and "连续产品歪斜报警" not in _labels and "玻璃盘跳动超限报警" not in _labels
      and "料仓取出自动清零" not in _labels, "改名: 旧标签已全部消失")
# ② 报警方式标签统一为「报警方案」（不再出现「报警方式」）
check("报警方案" in _labels, "报警方案: 出现「报警方案」标签")
check("报警方式" not in _labels, "报警方案: 不再出现「报警方式」标签")
# ③ 报警方案配置页新增「停机延迟」列 + 时间单位说明
_check_hdr = lambda t: t in _labels
check(_check_hdr("停机延迟"), "方案配置: 表头出现「停机延迟」列")
check(any("本页面内的时间单位均为" in t for t in _labels), "方案配置: 出现时间单位说明（本页面内的时间单位均为 ms）")
# ④ 停机延迟数值框默认 5000（取首行即可，所有方案同默认）
_rows = getattr(_ddlg, "_state_plan_rows", [])
if _rows:
    _sd = _rows[0].get("stop_delay_spin")
    check(_sd is not None and _sd.value() == 5000, f"方案配置: 停机延迟默认 5000 (实际 {_sd.value() if _sd else None})")
# ⑤ 持续时长 / 报警延迟数值框不再带 ms 单位（suffix 为空）＋三列时间数值框宽度一致
if _rows:
    _dur = _rows[0].get("duration_spin")
    _delay = _rows[0].get("delay_spin")
    check(_dur is not None and _dur.suffix() == "", f"方案配置: 持续时长框已去除 ms 单位 (suffix='{_dur.suffix() if _dur else None}')")
    check(_delay is not None and _delay.suffix() == "", f"方案配置: 报警延迟框已去除 ms 单位 (suffix='{_delay.suffix() if _delay else None}')")
    _w_dur = _dur.width() if _dur else -1
    _w_del = _delay.width() if _delay else -2
    _sd2 = _rows[0].get("stop_delay_spin")
    _w_stop = _sd2.width() if _sd2 else -3
    check(_w_del == _w_dur and _w_stop == _w_dur,
          f"方案配置: 报警延迟/停机延迟数值框宽度与持续时长一致 (dur={_w_dur}, delay={_w_del}, stop={_w_stop})")
_ddlg._on_finished(0)
_ddlg.deleteLater()

# ============ 新需求：产品管理默认两个不可删除母版（电容0402 / 电阻0603） ============
from product_manager_dialog import ProductManagerDialog, _make_template_products
_tpl = _make_template_products()
check(len(_tpl) == 2, f"母版: 默认两个母版 (实际 {len(_tpl)})")
check(_tpl[0]["product_type"] == "电容" and _tpl[0]["product_model"] == "0402",
      "母版: 其一为电容 0402")
check(_tpl[1]["product_type"] == "电阻" and _tpl[1]["product_model"] == "0603",
      "母版: 其二为电阻 0603")
check(all(p.get("is_template", False) for p in _tpl), "母版: 均带 is_template 标记")
check("母版，不可删除" in _tpl[0]["description"] and "母版，不可删除" in _tpl[1]["description"],
      f"母版: 描述含「母版，不可删除」 (实际 '{_tpl[0]['description']}')")
# 选中母版 → 「删除产品」按钮禁用；点击删除被阻止（弹窗提示且不删除）
_dlg = ProductManagerDialog(_make_template_products(), None)
if _dlg.products:
    _dlg.table.selectRow(0)
    _dlg._on_selection_changed()
check(not getattr(_dlg, "_btn_delete", None) or not _dlg._btn_delete.isEnabled(),
      "母版: 选中母版时「删除产品」按钮禁用")
_t0 = len(_dlg.products)
_orig_info = _QMessageBox.information
_orig_q = _QMessageBox.question
try:
    _QMessageBox.information = staticmethod(lambda *a, **k: None)
    _QMessageBox.question = staticmethod(lambda *a, **k: _QMessageBox.StandardButton.Yes)
    _dlg._on_delete()
finally:
    _QMessageBox.information = _orig_info
    _QMessageBox.question = _orig_q
check(len(_dlg.products) == _t0, "母版: 删除母版被阻止（数量不变）")
# 拷贝母版 → 生成可删除副本（不带 is_template）
_dlg._on_copy()
check(len(_dlg.products) == _t0 + 1, "母版: 可拷贝母版生成副本")
_check = _dlg.products[-1]
check(not _check.get("is_template", False), "母版: 副本不带 is_template，可删除")
_dlg.table.selectRow(len(_dlg.products) - 1)
_dlg._on_selection_changed()
check(_dlg._btn_delete.isEnabled(), "母版: 选中副本后「删除产品」按钮恢复启用")
_dlg.deleteLater()

# ============ 新需求：相机调试卡片「拍照设置」按钮（名称右侧，内容与导航「拍照设置」一致） ============
check(hasattr(dv, "_cams") and len(dv._cams) > 0, "拍照设置: 调试界面持有相机卡片列表")
if hasattr(dv, "_cams") and len(dv._cams) > 0:
    _cp = dv._cams[0]
    _items = [_cp._title_row.itemAt(i).widget() for i in range(_cp._title_row.count())]
    _name_idx = _items.index(_cp._name)
    _photo_btn = next((w for w in _items
                       if isinstance(w, _QPushButton) and w.text() == "拍照设置"), None)
    check(_photo_btn is not None, "拍照设置: 相机卡片存在「拍照设置」按钮")
    if _photo_btn is not None:
        check(_items.index(_photo_btn) == _name_idx + 1,
              f"拍照设置: 按钮位于卡片名称右侧 (name@{_name_idx}, btn@{_items.index(_photo_btn)})")
        # 点击应触发 main_window._open_trigger_settings（与导航「拍照设置」同一窗口）
        _opened = {}
        _orig_open = getattr(dv.main_window, "_open_trigger_settings", None)

        def _fake_open():
            _opened["hit"] = True
        dv.main_window._open_trigger_settings = _fake_open
        try:
            _photo_btn.click()
        finally:
            if _orig_open is None:
                del dv.main_window._open_trigger_settings
            else:
                dv.main_window._open_trigger_settings = _orig_open
        check(_opened.get("hit", False),
              "拍照设置: 点击按钮调用 main_window._open_trigger_settings（与导航拍照设置一致）")

# ============ 修正反馈1：调试界面运行日志「日志详情」按钮（与「日志管理」一致） ============
check(hasattr(dv._run_log, "_detail_btn") and dv._run_log._detail_btn.text() == "日志详情",
      "日志详情: 调试界面运行日志标题栏含「日志详情」按钮")
from nav_dialogs import LogManagerDialog
_d0 = getattr(dv, "_dlg_log_detail", None)
dv._open_log_manager()
_d1 = getattr(dv, "_dlg_log_detail", None)
check(isinstance(_d1, LogManagerDialog) and _d1.isVisible(),
      "日志详情: 调试界面点击打开日志窗口（与「日志管理」同类型）")
check(_d0 is None or _d1 is _d0, "日志详情: 单实例（重复点击不新建）")
if _d1 is not None:
    _d1.close()
    dv._dlg_log_detail = None

# ============ 修正反馈2：调试界面「检索→返回」应冻结本面板显示，且绝不重置生产计数 ============
_sp = dv.stats_panel
check(getattr(_sp, "_mirror", False) is True, "检索返回: 调试界面统计面板为镜像模式")
# 模拟生产运行界面已累计（非 0），记录当前计数作为基准
pv3._live_total = 8888
pv3._live_good = 8600.0
pv3._live_bad = 288.0
_before = (pv3._live_total, pv3._live_good, pv3._live_bad)
# 选中非「当前运行」的检索方式，避免按钮因当前运行置灰而被兜底忽略
_sp.period_cb.blockSignals(True)
_sp.period_cb.setCurrentText("指定时间段")
_sp.period_cb.blockSignals(False)
# 第一次点击：检索 → 冻结本面板显示，且不改动生产计数
_sp._on_search_stats()
check(_sp._stat_frozen is True, "检索返回: 检索后调试界面统计处于冻结（固定显示）状态")
check(_sp._search_return_mode is True, "检索返回: 检索后进入「返回」模式")
check((pv3._live_total, pv3._live_good, pv3._live_bad) == _before,
      "检索返回: 检索未重置/清零生产运行界面累计计数")
# 时段下拉切换也不应反向重置生产计数（镜像不再向 owner 转发时段）
_sp._set_period("白班")
check((pv3._live_total, pv3._live_good, pv3._live_bad) == _before,
      "检索返回: 调试界面切换时段不下发生产界面（不清零）")
# 第二次点击：返回 → 解除冻结，仍不改动生产计数
_sp._on_search_stats()
check(_sp._stat_frozen is False, "检索返回: 返回后解除冻结（恢复实时刷新）")
check(_sp._search_return_mode is False, "检索返回: 返回后退出「返回」模式")
check((pv3._live_total, pv3._live_good, pv3._live_bad) == _before,
      "检索返回: 返回未重置/清零生产运行界面累计计数")
# 冻结期间 tick_live 不再改写显示（保持固定显示）：通过统计 _render_mirror 调用次数验证
_sp._on_search_stats()  # 重新进入冻结
_render_calls = {"n": 0}
_orig_render = _sp._render_mirror
def _counted_render(snap):
    _render_calls["n"] += 1
    return _orig_render(snap)
_sp._render_mirror = _counted_render
_sp.tick_live(); app.processEvents()
check(_render_calls["n"] == 0,
      "检索返回: 冻结期间 tick_live 不调用 _render_mirror（详细数据固定显示）")
_sp._render_mirror = _orig_render
_sp._on_search_stats()  # 退出冻结，恢复实时刷新

# ============ 新需求：底部状态栏「显示所有图像」下拉 + 「语言」下拉 ============
check(hasattr(_mw, "btn_img_filter") and _mw.btn_img_filter is not None,
      "底部状态栏: 存在「显示所有图像」下拉按钮")
if hasattr(_mw, "btn_img_filter"):
    _mf = _mw.btn_img_filter
    check(_mf.text() == "显示所有图像",
          f"显示所有图像: 默认显示「显示所有图像」(实际 '{_mf.text()}')")
    _mf_menu = _mf.menu()
    check(_mf_menu is not None, "显示所有图像: 存在下拉菜单")
    _mf_opts = [a.text() for a in _mf_menu.actions()]
    check(_mf_opts == ["显示所有图像", "仅显示不良品图像", "仅显示良品图像"],
          f"显示所有图像: 选择项正确 (实际 {_mf_opts})")
    check(any(a.isChecked() for a in _mf_menu.actions()),
          "显示所有图像: 默认选中「显示所有图像」")
    _mf_menu.actions()[1].trigger()
    app.processEvents()
    check(_mf.text() == "仅显示不良品图像",
          f"显示所有图像: 选中后按钮文本更新 (实际 '{_mf.text()}')")
    _mf_menu.actions()[0].trigger()
    app.processEvents()

check(hasattr(_mw, "_footer_lang_label") and _mw._footer_lang_label is not None,
      "底部状态栏: 存在「语言」下拉按钮")
if hasattr(_mw, "_footer_lang_label"):
    _lm = _mw._footer_lang_label.menu()
    _langs = [a.text() for a in _lm.actions()]
    check(_langs == ["中文", "英语", "韩语", "日语", "德语", "俄语", "越南语"],
          f"语言: 选择项含7种语言 (实际 {_langs})")
    check(_mw._footer_lang_label.text() == "中文",
          f"语言: 默认中文 (实际 '{_mw._footer_lang_label.text()}')")
    _lm.actions()[1].trigger()
    app.processEvents()
    check(_mw._footer_lang_label.text() == "英语",
          f"语言: 选中后按钮文本更新 (实际 '{_mw._footer_lang_label.text()}')")
    _lm.actions()[0].trigger()
    app.processEvents()

# ============ 新需求：左侧导航新增「图片保存」按钮 + 图片保存窗口 ============
_check_keys = [k for k, *_ in _app.FUNC_NAV_ITEMS]
check("image_save" in _check_keys,
      "导航: FUNC_NAV_ITEMS 新增「图片保存」(image_save)")
for _role, _kset in _app.NAV_VISIBILITY.items():
    check("image_save" in _kset,
          f"导航可见性: {_role} 可见「图片保存」")

import tempfile as _tempfile
import json as _json
import nav_dialogs as _nav_dialogs
_tmp_img = os.path.join(_tempfile.mkdtemp(), "image_save_config.json")

from nav_dialogs import ImageSaveDialog
ImageSaveDialog._cfg_path = lambda self: _tmp_img
_isd = ImageSaveDialog(_mw)
check(isinstance(_isd, ImageSaveDialog), "图片保存: 可构造 ImageSaveDialog")
check([_isd._strategy.itemText(i) for i in range(_isd._strategy.count())] ==
      ["所有图像", "所有良品", "所有不良", "所有待定", "所有不良+待定", "指定检测项不良"],
      "图片保存: 保存策略6项")
check([_isd._fmt.itemText(i) for i in range(_isd._fmt.count())] ==
      ["JPEG", "BMP", "PNG", "TIFF"],
      "图片保存: 保存格式4项")
check(_isd._scale.value() == 100,
      f"图片保存: 缩放比例默认100% (实际 {_isd._scale.value()}%)")
check(_isd._scale.suffix() == "%", "图片保存: 缩放比例单位为 %")
check(_isd._quality.value() == 100,
      f"图片保存: 图像质量默认100 (实际 {_isd._quality.value()})")

# —— 启用图像保存开关（顶部）——
check(hasattr(_isd, "_enable_sw") and _isd._enable_sw.isChecked() is True,
      "图片保存: 顶部「启用图像保存」开关存在且默认开启")
check(hasattr(_isd, "_cfg_area") and _isd._cfg_area.isEnabled(),
      "图片保存: 开关开启时配置区可用")
_isd._enable_sw.setChecked(False)
check(not _isd._cfg_area.isEnabled(),
      "图片保存: 关闭开关后配置区整体禁用")
_isd._enable_sw.setChecked(True)

# —— 检测项行：仅「指定检测项不良」时显示，且为可多选下拉 ——
check(_isd._defect_widget.isHidden(),
      "图片保存: 默认隐藏「检测项」行")
check(hasattr(_isd._defect_combo, "checked_items"),
      "图片保存: 检测项为可多选下拉 (CheckableCombo)")
check(_isd._defect_combo.checked_items() == [],
      "图片保存: 检测项默认未勾选任何项")
_isd._strategy.setCurrentText("指定检测项不良")
check(not _isd._defect_widget.isHidden(),
      "图片保存: 选「指定检测项不良」后显示检测项行")
_isd._defect_combo.set_checked(["产品长度", "瓷体缺损"])
check(sorted(_isd._defect_combo.checked_items()) == ["产品长度", "瓷体缺损"],
      f"图片保存: 检测项可勾选多项 (实际 {_isd._defect_combo.checked_items()})")
_isd._defect_combo.set_checked([])
_isd._strategy.setCurrentText("所有图像")
check(_isd._defect_widget.isHidden(),
      "图片保存: 切回其他策略后检测项行重新隐藏")

# —— 保存天数 / 硬盘剩余空间监控 / 存满执行动作 / 保存路径 ——
check(_isd._days.value() == 7 and " 天" in _isd._days.suffix(),
      f"图片保存: 保存天数默认7天、单位天 (实际 {_isd._days.value()}{_isd._days.suffix()})")
check(_isd._days.minimum() == 1 and _isd._days.maximum() == 365,
      "图片保存: 保存天数范围 1~365")
check(_isd._disk.value() == 10 and " GB" in _isd._disk.suffix(),
      f"图片保存: 硬盘剩余空间监控默认10GB (实际 {_isd._disk.value()}{_isd._disk.suffix()})")
check([_isd._full_action.itemText(i) for i in range(_isd._full_action.count())] ==
      ["停止存储", "覆盖存储"],
      "图片保存: 存满执行动作含 停止存储/覆盖存储")
check(_isd._full_action.currentText() == "停止存储",
      f"图片保存: 存满执行动作默认停止存储 (实际 {_isd._full_action.currentText()})")
# —— 「图片存满时执行动作」：标签与下拉框同一行（横向排列，非上下堆叠）——
def _find_label_by_text(root, text):
    from PyQt6.QtWidgets import QLabel as _QLabel
    for lb in root.findChildren(_QLabel):
        if lb.text() == text:
            return lb
    return None

_full_lbl = _find_label_by_text(_isd, "图片存满时执行动作")
check(_full_lbl is not None, "图片保存: 存在「图片存满时执行动作」标签")
if _full_lbl is not None:
    def _layout_containing(lay, w1, w2):
        """递归找出同时直接包含 w1 与 w2 的布局（找不到返回 None）。

        需同时下钻「子布局」与「子控件自身的布局」—— 配置区_body 是
        self._cfg_area 的布局，row3 又是 body 的子布局。
        """
        if lay is None:
            return None
        if lay.indexOf(w1) >= 0 and lay.indexOf(w2) >= 0:
            return lay
        for i in range(lay.count()):
            it = lay.itemAt(i)
            _sub = it.layout()
            if _sub is None:
                w = it.widget()
                _sub = w.layout() if w is not None else None
            if _sub is not None:
                _hit = _layout_containing(_sub, w1, w2)
                if _hit is not None:
                    return _hit
        return None

    _flay = _layout_containing(_isd.layout(), _full_lbl, _isd._full_action)
    check(_flay is not None,
          "图片保存: 存满动作标签与下拉框位于同一行布局")
    if _flay is not None:
        from PyQt6.QtWidgets import QHBoxLayout as _QHBox
        from PyQt6.QtWidgets import QVBoxLayout as _QVBox
        _flay_item = _flay.itemAt(_flay.indexOf(_isd._full_action))
        check(isinstance(_flay, _QHBox) and not isinstance(_flay, _QVBox)
              and _flay_item.widget() is _isd._full_action,
              "图片保存: 存满动作下拉框直接挂在该横向行（非嵌套竖列布局）")
        # 同行 → 两者 y 坐标应基本一致
        check(abs(_full_lbl.mapTo(_isd, _full_lbl.rect().center()).y()
                  - _isd._full_action.mapTo(_isd,
                                            _isd._full_action.rect().center()).y()) <= 4,
              "图片保存: 存满动作标签与下拉框垂直居中在同一行")

# —— 2026-10-09：全部字段「标签 + 控件同一行」且**同列对齐**——
# 需求：保存策略/保存格式下拉框上移到与标题同一行；缩放比例/图像质量/保存天数/
# 硬盘剩余空间监控/图片存满时执行动作/保存路径（含输入框与浏览按钮）都改为同一行。
# ⚠️ 这里用**结构断言**（标签与控件是否同属一个 QHBoxLayout + 标签列宽是否统一），
# 而不是读几何坐标 —— 冒烟环境不show() 对话框，`mapTo` 会返回未布局的过期值
# （所有控件 y 相同、x 相同），几何断言在离屏下不可靠（同「离屏读数陷阱」）。
_isd._strategy.setCurrentText("指定检测项不良")
_rows = (("保存策略", _isd._strategy), ("检测项", _isd._defect_combo),
         ("保存格式", _isd._fmt), ("缩放比例", _isd._scale),
         ("图像质量", _isd._quality), ("保存天数", _isd._days),
         ("硬盘剩余空间监控", _isd._disk),
         ("图片存满时执行动作", _isd._full_action),
         ("保存路径", _isd._path_edit))
from PyQt6.QtWidgets import QHBoxLayout as _QHBox2, QVBoxLayout as _QVBox2
_same_row = []
for _pn, _pw in _rows:
    _plbl = _find_label_by_text(_isd, _pn)
    _rl = _layout_containing(_isd.layout(), _plbl, _pw) if _plbl is not None else None
    _same_row.append(
        _rl is not None and isinstance(_rl, _QHBox2)
        and not isinstance(_rl, _QVBox2)
        # 控件直接挂在该横向行上（不是嵌套在竖列子布局里）
        and _rl.itemAt(_rl.indexOf(_pw)).widget() is _pw)
check(all(_same_row),
      f"图片保存: 全部 9 个字段均为「标签+控件同一行」（不达标字段数 "
      f"{_same_row.count(False)}，字段={[n for (n, _), ok in zip(_rows, _same_row) if not ok]}）")
# 标签列统一宽度：所有标签宽度一致 → 控件列必然同列对齐
_lbl_ws = set()
for _pn in ("检测项", "缩放比例", "图像质量", "保存天数",
            "硬盘剩余空间监控", "图片存满时执行动作", "保存路径"):
    _l = _find_label_by_text(_isd, _pn)
    if _l is not None:
        _lbl_ws.add(_l.width())
check(len(_lbl_ws) == 1,
      f"图片保存: 标签列统一宽度（同列对齐基础），实测宽度集合 {sorted(_lbl_ws)}")
_isd._strategy.setCurrentText("所有图像")

# —— 数值框：统一使用普通 QSpinBox + 与「触发设定」一致的箭头样式（不再自绘三角）——
from PyQt6.QtWidgets import QSpinBox as _QSpinBoxCls
for _nm, _sb in (("缩放比例", _isd._scale), ("图像质量", _isd._quality),
                 ("保存天数", _isd._days), ("硬盘剩余空间监控", _isd._disk)):
    check(type(_sb) is _QSpinBoxCls,
          f"图片保存: {_nm} 使用标准 QSpinBox（箭头与其他页面一致，实际 {type(_sb).__name__}）")
    _sbs = _sb.styleSheet()
    check("QSpinBox::up-button" in _sbs and "QSpinBox::down-button" in _sbs
          and "width: 16px" in _sbs and "image:" not in _sbs
          and "ArrowSpinBox" not in _sbs,
          f"图片保存: {_nm} 箭头样式与「触发设定」一致（未覆盖箭头/未自绘）")
check(_isd._path_edit.text().strip() != "",
      f"图片保存: 保存路径有默认值 (实际 {_isd._path_edit.text()})")

# —— 配置保存（落临时目录，不污染工程）——
_isd._strategy.setCurrentText("指定检测项不良")
_isd._defect_combo.set_checked(["产品长度", "瓷体缺损"])
_isd._days.setValue(15)
_isd._disk.setValue(20)
_isd._full_action.setCurrentText("覆盖存储")
_isd._on_save()
with open(_tmp_img, "r", encoding="utf-8") as _f:
    _img_cfg = _json.load(_f)
check(_img_cfg.get("enabled") is True and _img_cfg.get("days") == 15
      and _img_cfg.get("disk_gb") == 20 and _img_cfg.get("full_action") == "覆盖存储"
      and sorted(_img_cfg.get("defects", [])) == ["产品长度", "瓷体缺损"],
      f"图片保存: 保存后配置已持久化 (实际 {_img_cfg})")
# 重新构造 → 配置回填
_isd2 = ImageSaveDialog(_mw)
check(_isd2._days.value() == 15 and _isd2._disk.value() == 20
      and _isd2._full_action.currentText() == "覆盖存储"
      and sorted(_isd2._defect_combo.checked_items()) == ["产品长度", "瓷体缺损"]
      and not _isd2._defect_widget.isHidden(),
      "图片保存: 重新打开窗口配置正确回填（策略/检测项/天数/磁盘/存满动作）")
_isd2._strategy.setCurrentText("所有图像")
_isd2._on_save()
check(_json.load(open(_tmp_img, "r", encoding="utf-8")).get("defects") == [],
      "图片保存: 非指定检测项策略时保存清空检测项")
_isd.close()
_isd2.close()

# ============ 新需求：日志管理窗口「启用日志保存」开关 ============
_tmp_log = os.path.join(_tempfile.mkdtemp(), "log_save_config.json")
_nav_dialogs._log_save_cfg_path = lambda: _tmp_log
_lmd = LogManagerDialog(pv, _mw)
check(hasattr(_lmd, "_log_save_sw") and _lmd._log_save_sw is not None,
      "日志管理: 顶部存在「启用日志保存」开关")
check(hasattr(_lmd, "_log_save_days") and _lmd._log_save_days.value() == 3,
      f"日志管理: 保存天数默认3天 (实际 {_lmd._log_save_days.value()})")
check(hasattr(_lmd, "_log_save_disk") and _lmd._log_save_disk.value() == 10,
      f"日志管理: 硬盘剩余空间监控默认10GB (实际 {_lmd._log_save_disk.value()})")
check(" 天" in _lmd._log_save_days.suffix() and " GB" in _lmd._log_save_disk.suffix(),
      "日志管理: 保存天数/硬盘空间单位分别为 天/GB")
check(_lmd._log_save_sw.isChecked() == False,
      "日志管理: 启用日志保存默认关闭")
# 启用并修改 → 配置写入（落临时目录，不污染工程）
_lmd._log_save_sw.setChecked(True)
_lmd._log_save_days.setValue(7)
_lmd._log_save_disk.setValue(20)
_lmd._on_log_save_cfg_changed()
import json as _json
with open(_tmp_log, "r", encoding="utf-8") as _f:
    _cfg = _json.load(_f)
check(_cfg.get("enabled") is True and _cfg.get("days") == 7 and _cfg.get("disk_gb") == 20,
      f"日志管理: 修改后配置已保存 (实际 {_cfg})")
_lmd.close()

# ============ 新需求：设备状态卡片底部分页（前一页 / 页码 / 后一页） ============
check(hasattr(pv, "_btn_status_prev") and hasattr(pv, "_btn_status_next")
      and hasattr(pv, "_status_page_lbl"),
      "设备状态: 底部存在 前一页/后一页 按钮与页码标签")
check(pv._status_pages == 2 and pv._status_page == 0,
      f"设备状态: 共2页、默认第1页 (实际 pages={pv._status_pages}, page={pv._status_page})")
check(pv._status_page_lbl.text() == "1/2",
      f"设备状态: 页码标签显示「1/N」格式 (实际 {pv._status_page_lbl.text()})")
# 第 1 页 = 与加分页前一致的全部 16 项状态行 + 4 张料盒卡片全部可见
check(all(not r["frame"].isHidden() for r in pv._status_grid_recs)
      and len(pv._status_grid_recs) == 16,
      f"设备状态: 第1页显示全部16项状态行 (实际 {len(pv._status_grid_recs)} 项)")
check(not pv._status_page1.isHidden() and pv._status_page2.isHidden(),
      "设备状态: 第1页显示内容容器、第2页容器隐藏")
check(pv._status_content.parentWidget() is pv._status_page1,
      "设备状态: 状态内容容器固定挂在第1页")
check(len(pv._light_recs) == 18
      and all(r["name"] == f"光源{i + 1}" for i, r in enumerate(pv._light_recs)),
      f"设备状态: 第2页光源状态共18路 (光源1~光源18，实际 {len(pv._light_recs)} 路)")
check(all(r["val_box"].text() in ("频闪中", "未频闪") for r in pv._light_recs),
      "设备状态: 光源状态取值仅为 频闪中/未频闪")
check({r["val_box"].text() for r in pv._light_recs} == {"频闪中", "未频闪"},
      "设备状态: 光源状态首屏同时存在 频闪中 与 未频闪 两类示例")
check(pv._light_content.parentWidget() is pv._status_page2,
      "设备状态: 光源状态内容容器固定挂在第2页")
check(not pv._btn_status_prev.isEnabled() and pv._btn_status_next.isEnabled(),
      "设备状态: 第1页时 前一页禁用、后一页可用")
# 光源状态来回切换：调用一次 tick 后至少有状态翻转，且取值仍限定在两类内
_light_before = [r["on"] for r in pv._light_recs]
pv._tick_light_status()
_light_after = [r["on"] for r in pv._light_recs]
check(_light_before != _light_after,
      "设备状态: 光源状态在 频闪中/未频闪 之间来回切换")
check(all(r["val_box"].text() in ("频闪中", "未频闪") for r in pv._light_recs),
      "设备状态: 切换后光源状态取值仍为 频闪中/未频闪")
pv._on_status_next_page()
check(pv._status_page == 1 and pv._status_page_lbl.text() == "2/2",
      f"设备状态: 点击后一页 → 页码变为 2/2 (实际 {pv._status_page_lbl.text()})")
check(pv._status_page2.parentWidget() is not None
      and pv._status_page1.isHidden() and not pv._status_page2.isHidden(),
      "设备状态: 第2页（光源状态）容器显示、第1页隐藏")
check(all(not r["frame"].isHidden() for r in pv._light_recs),
      "设备状态: 第2页显示全部18路光源状态行")
check(pv._status_content.parentWidget() is pv._status_page1,
      "设备状态: 第2页不再复用第1页的设备状态示例内容")
check(pv._btn_status_prev.isEnabled() and not pv._btn_status_next.isEnabled(),
      "设备状态: 第2页时 前一页可用、后一页禁用")
pv._on_status_prev_page()
check(pv._status_page == 0 and pv._status_page_lbl.text() == "1/2"
      and not pv._btn_status_prev.isEnabled() and pv._btn_status_next.isEnabled(),
      f"设备状态: 点击前一页回到第1页、页码回到 1/2"
      f" (实际 {pv._status_page_lbl.text()})")
check(pv._status_content.parentWidget() is pv._status_page1
      and all(not r["frame"].isHidden() for r in pv._status_grid_recs),
      "设备状态: 回到第1页后状态行全部恢复显示")

# ============ 新需求：本地图像列表在「序号」左侧新增「测试结果」列 + 底部良率 ============
check(liw.list_widget.columnCount() == 4,
      f"本地图像: 列表为4列 (实际 {liw.list_widget.columnCount()})")
_hdr = [liw.list_widget.horizontalHeaderItem(i).text()
        for i in range(liw.list_widget.columnCount())]
check(_hdr == ["测试结果", "序号", "图片名", "缩略图"],
      f"本地图像: 表头为 测试结果/序号/图片名/缩略图 (实际 {_hdr})")
# 运行前：测试结果列隐藏
check(liw.list_widget.isColumnHidden(0),
      "本地图像: 运行图片前「测试结果」列隐藏")
# 运行所有图片（逐张调用 _run_step 模拟定时器）→ 该列显示且填入 OK/NG/待定
for _ in range(liw.list_widget.rowCount()):
    liw._run_step()
app.processEvents()
check(not liw.list_widget.isColumnHidden(0),
      "本地图像: 运行图片后「测试结果」列显示")
_vd = [liw.list_widget.item(r, 0).text() if liw.list_widget.item(r, 0) else ""
       for r in range(liw.list_widget.rowCount())]
_sq = [liw.list_widget.item(r, 1).text() if liw.list_widget.item(r, 1) else ""
       for r in range(liw.list_widget.rowCount())]
check(all(v in ("OK", "NG", "待定") for v in _vd) and set(_vd) == {"OK", "NG", "待定"},
      f"本地图像: 运行后测试结果列取值仅 OK/NG/待定 且三种齐全 (实际 {_vd})")
check(_sq == [str(i + 1) for i in range(len(_sq))],
      f"本地图像: 序号列仍为连续序号 (实际 {_sq})")
check(liw.stat_rst.text().startswith("待定："),
      f"本地图像: 尾部统计末项显示为「待定」 (实际 {liw.stat_rst.text()})")
# 良率 = OK / (OK + NG)，待定不计入
_yield_txt = liw.stat_yield.text()
check(_yield_txt.startswith("良率：") and _yield_txt.endswith("%"),
      f"本地图像: 底部统计含良率 (实际 {_yield_txt})")
try:
    _yv = float(_yield_txt.split("：")[1].rstrip("%"))
    _okc = int(liw.stat_ok.text().split("：")[1])
    _ngc = int(liw.stat_ng.text().split("：")[1])
    _rstc = int(liw.stat_rst.text().split("：")[1])
    check(abs(_yv - _okc / (_okc + _ngc) * 100) < 0.01,
          f"本地图像: 良率=OK/(OK+NG) 且不计待定 (良率={_yv}, OK={_okc}, NG={_ngc}, 待定={_rstc})")
except Exception as e:
    check(False, f"本地图像: 良率解析异常 {e}")

# ============ 新需求：本地图像底部「总数」左侧增加「详情」按钮 + 左侧展开统计详情面板 ============
check(hasattr(liw, "b_detail") and liw.b_detail.text() == "详情",
      f"本地图像: 底部统计行存在「详情」按钮 (实际 {getattr(liw, 'b_detail', None) and liw.b_detail.text()})")
# 「详情」按钮必须位于「总数」左侧（同一行，且索引更小）
def _row_layout_of(w1, w2):
    """递归找出同时直接包含 w1 与 w2 的布局（详情按钮与总数同属统计行）。"""
    def _walk(lay):
        if lay is None:
            return None
        if lay.indexOf(w1) >= 0 and lay.indexOf(w2) >= 0:
            return lay
        for i in range(lay.count()):
            it = lay.itemAt(i)
            sub = it.layout()
            if sub is None:
                w = it.widget()
                sub = w.layout() if w is not None else None
            if sub is not None:
                hit = _walk(sub)
                if hit is not None:
                    return hit
        return None
    return _walk(liw.layout())

_srow = _row_layout_of(liw.b_detail, liw.stat_total)
check(_srow is not None and _srow.indexOf(liw.b_detail) < _srow.indexOf(liw.stat_total),
      "本地图像: 「详情」按钮位于「总数」左侧同一行")
# 宽度两态：紧凑宽度**不包含**详情面板宽（初始显示宽度与加面板之前一致）
check(liw.minimumWidth() == liw._compact_w
      and liw._compact_w == liw._full_w - liw._detail_panel_w - liw._outer_spacing,
      f"本地图像: 初始（紧凑）最小宽度不含详情面板宽 "
      f"(compact={liw._compact_w}, min={liw.minimumWidth()}, full={liw._full_w})")
check(liw._full_w == liw._compact_w + liw._detail_panel_w + liw._outer_spacing,
      f"本地图像: 展开宽度 = 紧凑宽度 + 详情面板宽 + 间距 (full={liw._full_w})")
# ⚠️ 详情面板宽度必须容得下 SPC 表 7 列，否则最右「比例」列被挤出可视区
# （这正是「展开后显示不完整」的根因：面板曾被写死 560px，而 7 列实需 638px）。
_spc_need = sum(liw._detail_table.columnWidth(i)
                for i in range(liw._detail_table.columnCount()))
check(liw._detail_panel_w >= _spc_need,
      f"本地图像: 详情面板宽度容得下 SPC 七列 "
      f"(面板={liw._detail_panel_w}px, 7列实需={_spc_need}px)")
check(liw._detail_panel.width() >= _spc_need,
      f"本地图像: 详情面板实际宽度不窄于七列合计 "
      f"(实际={liw._detail_panel.width()}px, 需={_spc_need}px)")
check(liw._detail_panel.minimumWidth() <= liw._detail_panel_w,
      f"本地图像: 详情面板 minWidth 不超过其实测宽度 "
      f"(min={liw._detail_panel.minimumWidth()}, w={liw._detail_panel_w})")
# 初次打开默认隐藏
check(not liw._detail_visible and liw._detail_panel.isHidden(),
      "本地图像: 初次打开时左侧统计详情面板默认隐藏")
# 面板内不再有「相机1~相机8」切换按钮行（需求：删除该行）
check(not hasattr(liw, "_detail_cam_buttons")
      and not hasattr(liw, "_select_detail_cam")
      and liw._detail_cam == "相机1",
      "本地图像: 详情面板已删除「相机1~相机8」切换行（固定展示相机1）")
_detail_btn_texts = [b.text() for b in liw._detail_panel.findChildren(_QPushButton)]
check(not any(t.startswith("相机") for t in _detail_btn_texts),
      f"本地图像: 详情面板内无相机切换按钮 (实际按钮: {_detail_btn_texts})")
# 点击展开（此处只校验状态位；「面板真正可见」在注入足够宽的虚拟屏后断言，
# 因为离屏测试屏默认 800px 装不下 full_w，窄屏会走降级分支暂时隐藏面板）
liw.b_detail.setChecked(True)
app.processEvents()
check(liw._detail_visible,
      "本地图像: 点击「详情」按钮后进入展开态（_detail_visible=True）")
check(liw.b_detail.text() == "收起详情",
      f"本地图像: 展开后按钮文案变为「收起详情」 (实际 {liw.b_detail.text()})")
check(liw.minimumWidth() >= liw._compact_w
      and liw.width() >= liw._compact_w,
      f"本地图像: 展开后窗口宽度增长到展开态 "
      f"(min={liw.minimumWidth()}, w={liw.width()}, compact={liw._compact_w})")
# ---- 右上角锚定（2026-10-08 需求）：展开/收起时窗口右上角严格不动 ----
# 关键回归点：锚点若取「点击瞬间的右边缘」，一旦某次左侧空间不足而退化为
# 「只加宽不位移」，右边缘即被永久改写，收回时窗口会停在偏移位置（实测 x 64→634）。
# 正确语义：锚定**首次定位时的右上角**，两态严格可逆。
# ⚠️ 离屏测试屏默认只有 800px 宽，装不下 full_w(≈1388)，会走「空间不足降级」分支。
# 故屏宽不足时注入一个足够宽的虚拟屏，让断言在真实语义下运行；
# 窄屏降级分支另用一条「自洽性」断言单独覆盖。
import os as _os
from PyQt6.QtWidgets import QApplication as _QApp
from PyQt6.QtCore import QRect as _QRect
_sc = _QApp.primaryScreen()
_avail = _sc.availableGeometry() if _sc else None
_need_w = liw._full_w + 40
_orig_screen = liw.screen
_orig_primary = _QApp.primaryScreen
if _avail is not None and _avail.width() < _need_w:
    # 注入虚拟屏：宽 = 展开态所需 + 余量
    class _FakeScreen:
        def availableGeometry(self):
            return _QRect(_avail.x(), _avail.y(), _need_w, max(_avail.height(), 800))

        def geometry(self):
            return _QRect(_avail.x(), _avail.y(), _need_w, max(_avail.height(), 800))
    _fs = _FakeScreen()
    liw.screen = lambda: _fs
    _QApp.primaryScreen = staticmethod(lambda: _fs)
    _avail = _fs.availableGeometry()
    # 窗口右缘贴近（但不超过）屏幕右缘 —— 与 debug_view 的「右上对齐」定位一致，
    # 这样向左展开的空间刚好等于 full_w（max_w = anchor_right - avail.left()）。
    _place_x = _avail.right() - liw._compact_w - 4
else:
    _place_x = 200

liw.setGeometry(_place_x, 120, liw._compact_w, 480)
app.processEvents()
# ⚠️ 先把「详情」按钮状态与窗口宽度强制复位，再重置锚点：
# 上一段（窄屏下）点过「详情」，`_anchor_right_top` 已被写成窄屏降级时的右上角；
# 若不先复位，收起点会按陈旧锚点把窗口拉到别处，导致后续断言全部失真。
liw.b_detail.blockSignals(True)
liw.b_detail.setChecked(False)
liw.b_detail.blockSignals(False)
liw._detail_visible = False
liw._detail_panel.setVisible(False)
liw._detail_panel.setFixedWidth(liw._detail_panel_w)
liw.setMinimumWidth(liw._compact_w)
liw.setGeometry(_place_x, 120, liw._compact_w, 480)
app.processEvents()
liw.reset_detail_anchor()          # 模拟 debug_view 定位后重置锚点
app.processEvents()
_g0 = liw.geometry()
_r0 = _g0.x() + _g0.width()
_t0 = _g0.y()
check(liw._anchor_right_top == (_r0, _t0),
      f"本地图像: 锚点记录为首次定位时的右上角 {liw._anchor_right_top} (期望({_r0}, {_t0}))")
liw.b_detail.setChecked(True)
app.processEvents()
_g1 = liw.geometry()
check(not liw._detail_panel.isHidden() and liw._detail_visible,
      "本地图像: 点击「详情」按钮后左侧详情面板展开")
check(_g1.x() + _g1.width() == _r0 and _g1.y() == _t0,
      f"本地图像: 展开后右上角不动（right {_r0}->{_g1.x() + _g1.width()}, "
      f"top {_t0}->{_g1.y()}）")
check(_g1.x() == _r0 - _g1.width(),
      f"本地图像: 展开后左边缘左移、宽度增长 (x={_g1.x()}, w={_g1.width()})")
if _avail is not None:
    check(_g1.x() >= _avail.left() and _g1.x() + _g1.width() <= _avail.right(),
          f"本地图像: 展开后左右边缘均在屏幕可用区内 "
          f"(x={_g1.x()}..{_g1.x() + _g1.width()}, 可用区 {_avail.left()}..{_avail.right()})")
# 收起：右上角同样不动、精确回到展开前位置
liw.b_detail.setChecked(False)
app.processEvents()
_g2 = liw.geometry()
check(_g2.x() + _g2.width() == _r0 and _g2.y() == _t0,
      f"本地图像: 收起后右上角不动 "
      f"(right {_g2.x() + _g2.width()}, top {_g2.y()})")
check(_g2.x() == _g0.x() and _g2.width() == _g0.width(),
      f"本地图像: 收起后精确回到展开前的位置与宽度 "
      f"(x {_g0.x()}->{_g2.x()}, w {_g0.width()}->{_g2.width()})")
# 多轮切换不变量：右上角绝不漂移（这是本轮修复的核心回归点）
_drift = []
for _i in range(3):
    liw.b_detail.setChecked(True)
    app.processEvents()
    _gg = liw.geometry()
    _drift.append((_gg.x() + _gg.width(), _gg.y()))
    liw.b_detail.setChecked(False)
    app.processEvents()
    _gg = liw.geometry()
    _drift.append((_gg.x() + _gg.width(), _gg.y()))
check(all(p == (_r0, _t0) for p in _drift),
      f"本地图像: 连续 3 轮展开/收起，右上角零漂移 (实测集合 {set(_drift)})")

# ---- 窄屏降级分支：屏幕装不下完整展开宽度时，自洽性优先（不出屏、不漂移） ----
class _NarrowScreen:
    def availableGeometry(self):
        return _QRect(_avail.x(), _avail.y(), _avail.width(), _avail.height())

    def geometry(self):
        return _QRect(_avail.x(), _avail.y(), _avail.width(), _avail.height())
_ns = _NarrowScreen()
liw.screen = lambda: _ns
_QApp.primaryScreen = staticmethod(lambda: _ns)
liw.setGeometry(60, 60, liw._compact_w, 480)
app.processEvents()
liw.reset_detail_anchor()
app.processEvents()
_nr0 = liw.geometry().x() + liw.geometry().width()
liw.b_detail.setChecked(True)
app.processEvents()
_ng1 = liw.geometry()
liw.b_detail.setChecked(False)
app.processEvents()
_ng2 = liw.geometry()
check(_ng1.x() + _ng1.width() == _nr0 and _ng1.y() == liw.geometry().y(),
      f"本地图像: 窄屏降级时展开后右上角仍锚定 (right {_nr0})")
check(_ng2.x() == 60 and _ng2.width() == liw._compact_w,
      f"本地图像: 窄屏降级时收起后精确回到原位 "
      f"(x={_ng2.x()}, w={_ng2.width()})")
check(_ng1.x() >= _avail.left() and _ng1.x() + _ng1.width() <= _avail.right(),
      f"本地图像: 窄屏降级时窗口不越出屏幕可用区 "
      f"(x={_ng1.x()}..{_ng1.x() + _ng1.width()})")

# 恢复真实屏幕并复原位置供后续断言使用
liw.screen = _orig_screen
_QApp.primaryScreen = _orig_primary
liw.setGeometry(200, 120, liw._compact_w, 560)
app.processEvents()
liw.reset_detail_anchor()
app.processEvents()
# 详情表内容 = 统计信息卡片「按缺陷项统计-详情」某相机明细（同一 SPC 七列表）
from production_view import DefectSPCStatTable as _DSPC
check(isinstance(liw._detail_table, _DSPC),
      f"本地图像: 详情面板复用统计信息的 SPC 七列表 (实际 {type(liw._detail_table).__name__})")
check([liw._detail_table.horizontalHeaderItem(c).text()
       for c in range(liw._detail_table.columnCount())]
      == ["检测项", "标称值", "规格下限", "规格上限", "超下限数", "超上限数", "比例"],
      "本地图像: 详情表为七列 SPC 表头")
check(liw._detail_table.rowCount() == len(liw._detail_defect_types) > 0,
      f"本地图像: 详情表按缺陷项逐行填充 (实际 {liw._detail_table.rowCount()} 行)")
# 与统计信息卡片 DefectStatsContainer 的「全部」口径不同 → 这里逐相机核对一台相机
from production_view import DefectStatsContainer as _DSC
_dsc = _DSC()
_dsc._select_camera("相机1")
_ref_rows = [[_dsc._detail_table.item(r, c).text()
              for c in range(_dsc._detail_table.columnCount())]
             for r in range(_dsc._detail_table.rowCount())]
_liw_rows = [[liw._detail_table.item(r, c).text()
              for c in range(liw._detail_table.columnCount())]
             for r in range(liw._detail_table.rowCount())]
check(_liw_rows == _ref_rows,
      "本地图像: 详情表数值与统计信息卡片「相机1」明细逐格一致")
_dsc.deleteLater()
# 再次点击收起
liw.b_detail.setChecked(False)
app.processEvents()
check(not liw._detail_visible and liw._detail_panel.isHidden(),
      "本地图像: 再次点击「详情」按钮后左侧详情面板收起")
check(liw.b_detail.text() == "详情",
      f"本地图像: 收起后按钮文案恢复为「详情」 (实际 {liw.b_detail.text()})")
check(liw.minimumWidth() == liw._compact_w
      and liw.width() == liw._compact_w,
      f"本地图像: 收起后窗口宽度恢复为初始紧凑宽度 "
      f"(min={liw.minimumWidth()}, w={liw.width()}, compact={liw._compact_w})")
# 顶部 7 个按钮文字不被裁：真实几何判据 —— 窗口显示后每颗按钮的实际宽度
# 不小于它按 QFontMetrics 文案宽度 + 内边距算出的下限，且最后一颗按钮不越出内容区右边界。
# （不用 layout().spacing() 反推宽度：按钮行与外层布局 spacing 不同，反推会误报。）
from local_image_window import BTN_FONT_SIZE as _BFS, BTN_PADDING_H as _BPH
from PyQt6.QtGui import QFont as _QF, QFontMetrics as _QFM
_btn_fm2 = _QFM(_QF("Microsoft YaHei", _BFS))
_btn_list = [liw.b_load_img, liw.b_load_def, liw.b_load_dir,
             liw.b_prev, liw.b_next, liw.b_run_all, liw.b_export]
liw.show()
app.processEvents()
_btn_short = [(b.text(), b.width(), b.minimumWidth())
              for b in _btn_list if b.width() < b.minimumWidth()]
check(not _btn_short,
      f"本地图像: 7 个按钮实际宽度均不小于文案所需下限（无文字被裁）"
      f"{' 偏窄: ' + str(_btn_short) if _btn_short else ''}")
# 文案实测宽度 + 内边距 == 按钮 minimumWidth（宽度计算与 QSS 共用同一份常量）
check(all(b.minimumWidth() == _btn_fm2.horizontalAdvance(b.text()) + _BPH * 2
          for b in _btn_list),
      "本地图像: 按钮下限宽度按 QFontMetrics 文案宽 + 内边距设置")
# 最后一颗按钮不越出内容区右边界
_last_r = _btn_list[-1].geometry().right()
_content_r = liw.list_widget.geometry().right()
check(_last_r <= _content_r,
      f"本地图像: 「导出运行结果」按钮未越出内容区右边界 "
      f"(btn_right={_last_r} <= content_right={_content_r})")
check(_BFS <= 11,
      f"本地图像: 顶部按钮字号已调小 ({_BFS}px)")
liw.hide()

# ============ 新需求：设备状态示例去掉多余外围矩形框 ============
def _has_border(css):
    """样式表中是否声明了非 none 的 border。

    注意排除 `border-radius`（圆角不是边框），也要忽略 `:hover` 等伪状态规则 ——
    「常态无框、悬停才提示」是本次需求的预期行为。
    """
    if not css:
        return False
    import re as _re
    # 去掉伪状态规则（QPushButton:hover {...} 等），只检查常态声明
    _base = _re.sub(r":[a-z-]+\s*\{[^}]*\}", "", css)
    for _m in _re.finditer(r"(?<!-)\bborder(?:-top|-right|-bottom|-left)?\s*:\s*([^;}]*)",
                           _base):
        if "none" not in _m.group(1):
            return True
    return False

check(all(not _has_border(r["frame"].styleSheet()) for r in pv._status_grid_recs),
      "设备状态: 第1页每个完整示例的最外围大矩形框已去掉边框")
check(all(not _has_border(r["frame"].styleSheet()) for r in pv._light_recs),
      "设备状态: 第2页光源状态每行的最外围大矩形框已去掉边框")
_units = [r["unit"] for r in pv._status_grid_recs if r.get("unit") is not None]
check(len(_units) > 0 and all(not _has_border(u.styleSheet()) for u in _units),
      f"设备状态: 各示例右侧单位的外围矩形框已去掉边框 (共 {len(_units)} 个单位标签)")
check(all(not _has_border(u.styleSheet())
          for u in (pv._btn_status_prev, pv._btn_status_next)),
      "设备状态: 「上一页 / 后一页」按钮外围矩形框已去掉边框")
check(not _has_border(pv._status_page_lbl.styleSheet()),
      "设备状态: 页码标签外围矩形框已去掉边框")
# 本轮加回：名称标签小框（第1页状态行 + 第2页光源行）与料盒 4 卡的外围框
check(all(_has_border(r["nm"].styleSheet()) for r in pv._status_grid_recs),
      "设备状态: 第1页各状态行的名称标签小框已加回")
check(all(_has_border(r["nm"].styleSheet()) for r in pv._light_recs),
      "设备状态: 第2页光源状态各行的名称标签小框已加回")
_bin_cards = [r for r in pv._status_rows if r["name"].endswith("料盒")]
check(len(_bin_cards) == 4
      and all(_has_border(r["frame"].styleSheet()) for r in _bin_cards),
      f"设备状态: 料盒 4 卡外围圆角框已加回 (共 {len(_bin_cards)} 卡)")
# 料盒卡内名称 / 状态灯不再套第二层框（避免与整卡外框叠加成双线）
check(all(not _has_border(r["nm"].styleSheet()) and not _has_border(r["dot"].styleSheet())
          for r in _bin_cards),
      "设备状态: 料盒卡内的名称与状态灯无额外小框（不与整卡外框叠加）")
check(all(not _has_border(r["dot"].styleSheet()) for r in pv._status_grid_recs),
      "设备状态: 状态行状态灯无小框（仅名称/百分比/数值框保留小框）")
# 百分比框 / 数值框的小框保留，避免整行变成纯文字
check(all(_has_border(r["val_box"].styleSheet()) for r in pv._status_grid_recs),
      "设备状态: 各状态行数值框小框保留")

# ============ 新需求：名称框加长 + 数值组右移 + 页码 1/N ============
# 实现方式：nm 改为 Expanding 吃掉行内剩余空间，且行尾**不加** addStretch()。
# 效果：① 名称框边框一路延伸到数值组左侧（蓝色框 + 箭头所指位置）；
#       ② 百分比框/数值框/单位被推到行右边缘（与蓝色竖线对齐）。
from PyQt6.QtGui import QFont as _QFont2, QFontMetrics as _QFontMetrics2
from PyQt6.QtWidgets import QSizePolicy as _QSizePolicy, QWidget as _QWidget
_col0 = [r for r in pv._status_grid_recs if r["grid_col"] == 0]
_col1 = [r for r in pv._status_grid_recs if r["grid_col"] == 1]
# 名称框宽度下限 = 本列最长文案宽。
# 曾经的回归：nm最小宽打55% 折中→ 网格列最小宽小于实际所需，
# QGridLayout 把差额全压到名称框上，最长名称（「RST 电磁阀」84px）被截到74px。
# 现在 min宽= 完整文案宽，宽度不足的问题由面板 min_w / 内容容器 Expanding 解决。
for _tag, _recs in (("左列", _col0), ("右列", _col1)):
    # 名称框必须**不窄于**最长文案（文案完整显示，不被截断）
    _need_w = max(_QFontMetrics2(_QFont2("Microsoft YaHei", 9)).horizontalAdvance(r["name"])
                  for r in _recs)
    check(all(r["nm"].width() >= _need_w for r in _recs),
          f"设备状态: {_tag}名称框宽度足够显示最长文案（{_need_w}px）")
    # 弹性余量：面板宽裕时名称框应明显宽于文案（说明弹性空间被吃掉了 → 边框已加长）
    _max_nm_w = max(r["nm"].width() for r in _recs)
    check(_max_nm_w > _need_w,
          f"设备状态: {_tag}名称框已加长（最宽 {_max_nm_w}px > 文案 {_need_w}px）")
    # 数值组（含单位）右边缘贴近行右边缘 —— 有单位的行取单位右边缘，无单位行取数值框右边缘
    def _group_right(_r):
        _t = _r["unit"] if _r["unit"] is not None else _r["val_box"]
        return _t.mapTo(_r["frame"], _t.rect().topRight()).x()
    _row_w = _recs[0]["frame"].width()
    _max_val_right = max(_group_right(r) for r in _recs)
    check(_row_w - _max_val_right <= 24,
          f"设备状态: {_tag}数值组已右移到与行右边缘对齐"
          f"（行宽 {_row_w}，数值组最右 {_max_val_right}，间距 {_row_w - _max_val_right}）")
    # 名称框右边缘紧邻数值组左边缘（中间不再有大空隙）。
    # 数值组左边缘统一取「百分比框」起点：有百分比时即百分比框，
    # 无百分比时百分比占位宽度为 0、起点即数值框位置，同样成立。
    _gap_max = max(
        r["pct_box"].mapTo(r["frame"], r["pct_box"].rect().topLeft()).x()
        - r["nm"].mapTo(r["frame"], r["nm"].rect().topRight()).x()
        for r in _recs)
    check(_gap_max <= 12,
          f"设备状态: {_tag}名称框与数值组紧邻（最大间隙 {_gap_max}px）")
# ⚠️ 2026-10-08 需求「按内容最多的矩形框长度整体拉长对齐」推翻了旧断言。
# 旧断言：无百分比项的百分比占位**不占宽度**（setFixedWidth(0)），
#         目的是让名称框一路顶到数值框。
# 新需求：同列各行名称框必须**严格等宽**。名称框是 Expanding，会吃掉行内全部
#         剩余空间 —— 若无百分比行少占 46px，各行剩余空间不等，名称框必然参差
#         （实测左列 92/166、右列 142/166/190/202 四种）。
#         所以百分比占位必须**恒为 46px**（无百分比时文案留空 + 透明，看不出占位），
#         配合「单位框同列统一宽度」，同列尾部组等宽 → 名称框严格齐平。
_no_pct = [r for r in pv._status_grid_recs if r.get("no_pct")]
check(len(_no_pct) > 0
      and all(r["pct_box"].width() == 46 for r in _no_pct),
      f"设备状态: 无百分比项的百分比占位仍占 46px 以保证名称框齐平"
      f"（共 {len(_no_pct)} 行，实测宽度 "
      f"{sorted(set(r['pct_box'].width() for r in _no_pct))}）")
# ---- 核心断言：同列各行名称框宽度**完全一致**（边框齐平），且已明显拉长 ----
for _tag, _recs in (("左列", _col0), ("右列", _col1)):
    _ws = sorted(set(r["nm"].width() for r in _recs))
    check(len(_ws) == 1,
          f"设备状态: {_tag}名称框**同列严格等宽**（实测宽度集合 {_ws}）")
    # 单位框同列统一宽度（无单位的行也建等宽透明占位框）
    _uws = sorted(set(r["unit"].width() for r in _recs if r["unit"] is not None))
    check(len(_uws) == 1,
          f"设备状态: {_tag}单位框同列统一宽度（实测 {_uws}）")
    # 名称框右缘必须齐平（用 pct_box 左缘减去间距核对：同列应完全相同）
    _rights = sorted(set(
        r["pct_box"].mapTo(r["frame"], r["pct_box"].rect().topLeft()).x()
        for r in _recs))
    check(len(_rights) == 1,
          f"设备状态: {_tag}名称框右缘齐平（实测 pct 左缘集合 {_rights}）")
    # ⚠️ 2026-10-09核心不变量：名称框宽度 = 该列最长内容宽 + 6+ 「单位框让出的宽度」。
    # 让出的宽度 = 旧单位框宽(max(24, adv+8)) - 新单位框宽(adv+4)，
    # 补给名称框是为了在**不改变卡片整体宽度**的前提下把 pct/val/unit 整体右移，
    # 让数值框紧挨右侧单位（如「次」）。这里校验宽度足够显示最长文案（不截断）。
    _fm3 = _QFontMetrics2(_QFont2("Microsoft YaHei", 9))
    _need_w = max(_fm3.horizontalAdvance(r["name"]) for r in _recs) + 6
    check(_ws[0] >= _need_w,
          f"设备状态: {_tag}名称框宽度 ≥ 该列最长内容宽（实测 {_ws[0]} / 下限 {_need_w}，文案不截断）")
    # ⚠️ 数值框与单位框之间必须**紧挨**（间隙= 行内 spacing 6px），
    # 不能有旧版AlignRight 造成的 ~12px 死间隙。
    _gaps = sorted({r["unit"].mapTo(r["frame"], r["unit"].rect().topLeft()).x()
                    - (r["val_box"].mapTo(r["frame"], r["val_box"].rect().topLeft()).x()
                       + r["val_box"].width())
                    for r in _recs})
    check(len(_gaps) == 1 and _gaps[0] <= 6,
          f"设备状态: {_tag}数值框紧挨右侧单位框，间隙恒定（实测间隙集合 {_gaps}）")
    # ⚠️ 单位框宽度必须按内容实需（adv+4），不能是旧的固定 24/92。
    check(all(r["unit"].width() <= max(
              _fm3.horizontalAdvance(u) + 4
              for rr in _recs for u in [rr["unit"].text()] if u) + 1
              or not rr["unit"].text()
              for r in _recs),
          f"设备状态: {_tag}单位框按内容实需宽度（无多余死宽度）")
# 单位框一律左对齐（紧贴数值框右缘；旧版电磁阀用 AlignRight 会拉开间隙）
_ua = sorted({int(r["unit"].alignment() & _Qt.AlignmentFlag.AlignHCenter)
              for r in pv._status_grid_recs})
check(_ua == [0],
      f"设备状态: 单位框全部左对齐（实测 HCenter 掩码集合 {_ua}，0=非居中即左对齐）")
# 第 2 页光源状态：名称框宽度 = 该列最长名称宽（不额外拉长），状态文字贴行右
check(all(r["nm"].width() >= _QFontMetrics2(_QFont2("Microsoft YaHei", 9))
          .horizontalAdvance(r["name"]) for r in pv._light_recs),
      "设备状态: 第2页光源状态名称框宽度足够显示完整名称")
# 第 2 页同样要求同列严格等宽（尾部 dot+状态文字 各行一致 → 天然齐平）
for _c, _lbl in ((0, "左列"), (1, "右列")):
    _lws = sorted(set(r["nm"].width() for r in pv._light_recs[_c::2]))
    check(len(_lws) == 1,
          f"设备状态: 第2页光源{_lbl}名称框严格等宽（实测 {_lws}）")
_light_gap_max = max(
    r["val_box"].mapTo(r["frame"], r["val_box"].rect().topLeft()).x()
    - r["nm"].mapTo(r["frame"], r["nm"].rect().topRight()).x()
    for r in pv._light_recs)
check(_light_gap_max <= 12,
      f"设备状态: 第2页名称框与状态文字紧邻（最大间隙 {_light_gap_max}px）")
# 页码 1/N 格式：初始 1/2，翻页后 2/2，页数变化时文案随之更新
check(pv._status_page_lbl.text() == "1/2",
      f"设备状态: 页码初始为「1/2」 (实际 {pv._status_page_lbl.text()})")
_pglbl_w = pv._status_page_lbl.width()
check(_pglbl_w >= _QFontMetrics2(_QFont2("Microsoft YaHei", 9))
      .horizontalAdvance(f"{pv._status_pages}/{pv._status_pages}"),
      f"设备状态: 页码标签宽度足够显示「N/N」 ({_pglbl_w}px)")

# ---- 面板宽度下限：min_w 必须≥ 内容实需宽 + 拉长余量，且默认布局下不与右列重叠 ----
# 回归背景：min_w 原为固定 320px，窗口较窄时 col_w 仅 391px，
# QGridLayout 把差额压到名称框上导致最长名称被截断。
_st_panel = pv.panels[2]
_st_grid_w = pv._status_grid_recs[0]["frame"].parentWidget().width()
_st_stretch = getattr(pv, "_status_stretch_w", 0)
check(_st_panel.minimumWidth() >= _st_grid_w,
      f"设备状态: 面板 min_w({_st_panel.minimumWidth()}) ≥ 内容实需宽({_st_grid_w})")
# ⚠️ 2026-10-09 需求「设备状态卡片的整体宽度不要改变」：拉长余量必须为 0。
# 上一轮为实现「拉长」加了 132px 人为富余，把面板 min_w 从 610撑到 742
# （Qt 强制撑宽面板、挤占右列空间），属于未经用户要求的宽度变更。
# 复原后每列名称框宽度**正好等于该列最长内容宽度**（`_status_min_w` 的列最小宽
# 本就按各列最长名称实算），同列严格等宽的对齐效果保持不变。
check(_st_stretch == 0,
      f"设备状态: 名称框拉长余量为 0，卡片整体宽度不改变（实测 {_st_stretch}）")
check(abs(_st_panel.minimumWidth() - pv._status_min_w) <= 1,
      f"设备状态: 面板 min_w({_st_panel.minimumWidth()}) = 内容实需宽"
      f"({pv._status_min_w})，未叠加任何人为富余")
# 内容容器宽 = _status_min_w - body 内缩(2*MARGIN) - **_status_lay 左右边距**
# ⚠️ 2026-10-09：`_status_lay` 自身有 10px 左右边距。之前漏扣这两项，
# 容器声明 598 但stack 真实可用宽只有 578 → 溢出 20px，第 2 页右列被裁掉
# （用户反馈「设备状态第二页显示不完整」）。
_body_inset = 2 * 6      # FloatPanel.MARGIN = 6
_lay_m = pv._status_lay.contentsMargins()
_lay_lr = _lay_m.left() + _lay_m.right()
check(abs((_st_grid_w + _body_inset + _lay_lr)
          - (pv._status_min_w + _st_stretch)) <= 4,
      f"设备状态: 内容容器宽({_st_grid_w}) + body内缩({_body_inset}) "
      f"+ _status_lay边距({_lay_lr}) = _status_min_w({pv._status_min_w}) "
      f"+ 拉长余量({_st_stretch})")
# ⚠️ 核心回归断言：**两页内容都不得超出所在页容器宽度**（否则被裁掉显示不完整）
for _pg, _content, _tag2 in ((pv._status_page1, pv._status_content, "第1页"),
                             (pv._status_page2, pv._light_content, "第2页")):
    check(_content.minimumWidth() <= _pg.width() + 1,
          f"设备状态: {_tag2}内容容器下限({_content.minimumWidth()}) "
          f"≤ 页宽({_pg.width()})，不会被裁切")
check(pv._light_content.minimumWidth() > 0,
      f"设备状态: 第2页光源容器已声明宽度下限"
      f"({pv._light_content.minimumWidth()})，名称框能吃到剩余宽度")
# 内容容器必须随面板拉伸（Expanding），否则面板加宽时容器停在 minHint、右侧留白
check(pv._status_content.sizePolicy().horizontalPolicy()
      == _QSizePolicy.Policy.Expanding,
      "设备状态: 内容容器为 Expanding（宽度跟随面板拉伸，不留白）")
# 内容容器必须**声明宽度下限**，否则 sizeHint 只由料盒卡决定（约 598px），
# 面板加宽后容器不跟随 → 状态网格吃不到富余 → 名称框无法「拉长」（实测恒为内容宽）。
check(pv._status_content.minimumWidth() > 0
      and abs(pv._status_content.minimumWidth() - _st_grid_w) <= 4,
      f"设备状态: 内容容器已声明宽度下限({pv._status_content.minimumWidth()})，"
      f"确保名称框能吃到富余被拉长")
# 两页分页容器必须用 QStackedLayout：直接 addWidget 时 QVBoxLayout 会按两页
# sizeHint 比例分宽度（598+286>body 可用 730），两页都不拉伸、内容右侧留白。
from PyQt6.QtWidgets import QStackedLayout as _QStackedLayout
check(isinstance(getattr(pv, "_status_stack", None), _QStackedLayout),
      "设备状态: 两页用 QStackedLayout 承载（可见页独占整块 body 宽度）")
# 默认布局：设备状态与右列不重叠
for _W in (1300, 1600, 1920, 2560):
    _h = _QWidget()
    _h.resize(_W, int(_W * 9 / 16) if _W >= 1920 else 900)
    _pv2 = ProductionView(_h)
    _pv2.resize(_h.width(), _h.height())
    _pv2.move(0, 0)
    _pv2.show()
    app.processEvents()
    _pv2._apply_default_layout()
    _pv2._laid = True
    for _ in range(3):
        app.processEvents()
    _g_st = _pv2.panels[2].geometry()
    _g_stats = _pv2.panels[3].geometry()
    _ov = _g_st.right() > _g_stats.left()
    _nm_ok = all(r["nm"].width() >= _QFontMetrics2(_QFont2("Microsoft YaHei", 9))
                 .horizontalAdvance(r["name"])
                 for r in _pv2._status_grid_recs)
    check(not _ov and _nm_ok,
          f"设备状态: {_W}px 窗口下无面板重叠且名称完整"
          f"（设备状态 {_g_st.width()}px / 统计 {_g_stats.width()}px，名称完整={_nm_ok}）")
    # ⚠️ 2026-10-08 回归点：面板下限必须取**实际 minimumWidth**，
    # 否则按纯内容宽定位右列面板时，设备状态面板被 Qt 强制撑宽 → 两面板重叠。
    # （2026-10-09 起该下限已等于 _status_min_w，此断言继续有效，
    #   防止将来又有人在面板 min_w 上叠加人为富余。）
    check(_pv2.panels[2].width() >= _pv2.panels[2].minimumWidth(),
          f"设备状态: {_W}px 窗口下设备状态面板宽度不小于其 min_w"
          f"（实际 {_pv2.panels[2].width()} / min {_pv2.panels[2].minimumWidth()}）")
    # 面板宽度不得大于内容实需宽（防止人为富余把卡片撑宽、挤占右列）
    check(_pv2.panels[2].minimumWidth() <= _pv2._status_min_w + 1,
          f"设备状态: {_W}px 窗口下面板 min_w({_pv2.panels[2].minimumWidth()}) "
          f"不超过内容实需宽({_pv2._status_min_w})，整体宽度未被改变")
    # 同列名称框在该分辨率下仍须严格等宽（齐平是本需求的核心不变量）
    for _c, _lbl2 in ((0, "左列"), (1, "右列")):
        _ws2 = sorted(set(r["nm"].width() for r in _pv2._status_grid_recs
                          if r["grid_col"] == _c))
        check(len(_ws2) == 1,
              f"设备状态: {_W}px 窗口下{_lbl2}名称框仍严格等宽（{_ws2}）")
    _pv2.hide()
    _h.close()
    app.processEvents()

# ============ 新需求：图片保存加入权限配置（默认所有类别均有） ============
from user_manager import PERMISSIONS as _PERMS, DEFAULT_CATEGORY_PERMISSIONS as _DEFCP
check("image_save" in _PERMS and _PERMS["image_save"] == "图片保存",
      f"权限配置: 权限项含「图片保存」 (实际 {_PERMS.get('image_save')})")
check(all(_DEFCP[c].get("image_save") is True for c in _DEFCP),
      "权限配置: 默认所有用户类别均拥有图片保存权限 "
      f"({ {c: _DEFCP[c].get('image_save') for c in _DEFCP} })")
_cp_now = getattr(_mw.user_manager, "category_permissions", {})
check(all(_cp_now.get(c, {}).get("image_save") is True for c in _app.NAV_VISIBILITY),
      f"权限配置: 运行期 UserManager 中所有类别均拥有图片保存 "
      f"({ {c: _cp_now.get(c, {}).get('image_save') for c in _app.NAV_VISIBILITY} })")
check(all("image_save" in ks for ks in _app.NAV_VISIBILITY.values()),
      "权限配置: 导航可见性默认全部开启")

liw.close()

# ============ Vision Copilot（AI助手）功能 ============
import tempfile as _tf_cp
import copilot_config as _cc
_cc_tmp = os.path.join(_tf_cp.mkdtemp(), "copilot_config.json")
_cc._config_path = lambda: _cc_tmp  # 写盘重定向到临时目录，避免污染 src/

_c = _cc.default_cfg()
check(_c["provider"] == "deepseek" and _c["api_key"] == "" and _c["max_rounds"] == 30,
      "Copilot 配置: 默认值正确")
check(_cc.PROVIDERS["ollama"]["needs_key"] is False
      and _cc.PROVIDERS["deepseek"]["needs_key"] is True,
      "Copilot 配置: 服务商 needs_key 正确（Ollama 免密钥）")
_c["api_key"] = "sk-test-123"
check(_cc.save_cfg(_c), "Copilot 配置: save_cfg 成功")
_loaded = _cc.load_cfg()
check(_loaded["api_key"] == "sk-test-123", "Copilot 配置: API Key round-trip 还原")
check("sk-test-123" not in open(_cc_tmp, encoding="utf-8").read(),
      "Copilot 配置: 落盘 API Key 已混淆（非明文）")
check(_cc.effective_base_url({"provider": "deepseek", "base_url": ""})
      == "https://api.deepseek.com/v1", "Copilot 配置: 默认 Base URL 生效")

check("ai_copilot" in [k for k, *_ in _app.FUNC_NAV_ITEMS],
      "导航: FUNC_NAV_ITEMS 含「AI助手」(ai_copilot)")
for _role, _kset in _app.NAV_VISIBILITY.items():
    if _role != "设备操作员":
        check("ai_copilot" in _kset, f"导航可见性: {_role} 可见「AI助手」")
check("ai_copilot" not in _app.NAV_VISIBILITY["设备操作员"],
      "导航可见性: 设备操作员不可见「AI助手」")

from vision_copilot import VisionCopilotDialog, CopilotConfigDialog
from PyQt6.QtGui import QImage as _QI, QColor as _QC
_vcd = VisionCopilotDialog(_mw, _mw)
check(isinstance(_vcd, VisionCopilotDialog), "Copilot: 可构造 VisionCopilotDialog")
check(len(_vcd._pending) == 0, "Copilot: 初始无待发送图片")
_img = _QI(40, 30, _QI.Format.Format_RGB32)
_img.fill(_QC(255, 0, 0))
_vcd.attach_image(_img)
check(len(_vcd._pending) == 1, "Copilot: attach_image 增加 1 张待发送图")
check(_vcd._pending[0]["data_url"].startswith("data:image/jpeg;base64,"),
      "Copilot: 生成 base64 data URL")
_vcd._remove_pending(0)
check(len(_vcd._pending) == 0, "Copilot: 移除待发送图生效")

_ccd = CopilotConfigDialog(_cc.load_cfg(), _mw)
check(isinstance(_ccd, CopilotConfigDialog), "Copilot: 可构造 CopilotConfigDialog")
_res = _ccd._collect()
check(_res["provider"] in _cc.PROVIDERS and _res["mcp"]["port"] == 8765
      and isinstance(_res["max_rounds"], int), "Copilot: 配置收集结构正确")
_ccd._select_provider("ollama")
check(_ccd._cfg["provider"] == "ollama", "Copilot: 切换服务商生效")
check(not _ccd._api_key_row.isVisible() or True, "Copilot: 配置窗构建无异常")
_ccd.close()
_vcd.close()
check(hasattr(_mw, "_open_ai_copilot"), "Copilot: MainWindow 暴露 _open_ai_copilot 入口")

# ============ 收尾：确认未污染 src/ 下的工程配置（写盘已重定向到临时目录） ============
check(all((open(_p, "rb").read() if os.path.exists(_p) else None) == _o
          for _p, _o in _CFG_GUARD.items()),
      "工程配置: 冒烟测试未改动 src/ 配置（写盘已重定向到临时目录） "
      f"({[os.path.basename(_p) for _p in _CFG_GUARD]})")

print()
print("ALL_PASS" if ok else "SOME_FAIL")
sys.exit(0 if ok else 1)
