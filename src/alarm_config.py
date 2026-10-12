"""报警设备阈值配置（示例默认值 + 可变字典 + 持久化）。

与 styles.py 的 COLORS 同一思路：维护一个模块级可变字典 ALARM，生产运行界面
实时读取它来换算料盒满料百分比、电磁阀寿命百分比；报警设置对话框在保存时直接
原地修改 ALARM 内部字典并写入同目录 alarm_config.json，下次启动自动加载。
"""

import copy
import json
import os
import sys

# 料盒 / 电磁阀的分类键（与设备运行状态面板、调试界面一致：OK / NG1 / NG2 / RST）
BIN_KEYS = ["OK", "NG1", "NG2", "RST"]
VALVE_KEYS = ["OK", "NG1", "NG2", "RST"]

# 速度 / 良率报警阈值的分类键（单位说明见 SQ_UNITS）
# - turntable_*：转盘速度，单位 RPM
# - detect_*：   检测速度，单位 Pcs/Min
# - good_low：   综合良率过低，单位 %
# - cam_yield_low：单相机良率过低，单位 %（比较各相机实时最低良率）
# - recheck_high：重检率过高，单位 %
SQ_KEYS = [
    "turntable_low", "turntable_high",
    "detect_low", "detect_high",
    "good_low", "cam_yield_low", "recheck_high",
]
SQ_LABELS = {
    "turntable_low": "转盘速度过低",
    "turntable_high": "转盘速度过高",
    "detect_low": "检测速度过低",
    "detect_high": "检测速度过高",
    "good_low": "综合良率低",
    "cam_yield_low": "单相机良率低",
    "recheck_high": "重检率过高",
}
SQ_UNITS = {
    "turntable_low": " RPM", "turntable_high": " RPM",
    "detect_low": " Pcs/Min", "detect_high": " Pcs/Min",
    "good_low": " %", "cam_yield_low": " %", "recheck_high": " %",
}

# 示例阈值（演示用，可在「报警设备」窗口中修改并保存）
# - bin_full：料盒满料停机阈值，单位「件」，料盒累计达到该值即视为满料触发停机报警
# - valve_life：电磁阀使用寿命阈值，单位「次动作」，已用动作次数达到该值即寿命到期
# - speed_quality：速度/良率报警阈值，超出范围即在运行日志记录报警（不触发停机）
DEFAULT_ALARM = {
    # 料盒满料停机示例阈值：50000 件（四个料盒一致）
    "bin_full": {"OK": 50000, "NG1": 50000, "NG2": 50000, "RST": 50000},
    # 电磁阀使用寿命示例阈值：5000000000 次（四个电磁阀一致）
    "valve_life": {"OK": 5000000000, "NG1": 5000000000,
                   "NG2": 5000000000, "RST": 5000000000},
    "speed_quality": {
        "turntable_low": 10, "turntable_high": 22,
        # 检测速度示例阈值：过低 8000 Pcs/Min、过高 12000 Pcs/Min
        "detect_low": 8000, "detect_high": 12000,
        "good_low": 90, "cam_yield_low": 85, "recheck_high": 5,
    },
    # 报警时长 / 报警延时（单位 ms）：作用于总气源/旋转盘/负压/静电四类设备状态报警
    # - duration_ms：报警触发后保持激活的时长，到时自动解除并重新开始延时计数
    # - delay_ms：   状态越界后需持续该时长才真正触发报警（去抖，避免瞬时波动误报）
    "alarm_timing": {
        "duration_ms": 3000, "delay_ms": 1000,
    },
    # 其他报警功能开关（默认状态见下；可在「报警设备」窗口修改并保存）
    # - auto_clear：料盒取出计数自动清零——料盒取出后会自动清零并继续运行，不触发停机（默认开启）
    # - mis_wrong_alarm / mis_miss_alarm：OK 良品料仓误踢 / 漏踢监控报警——默认均关闭；
    #               开启后对应误踢/漏踢频率（Pcs/H）超阈值即按所选报警方案（别名）报警显示
    # - mis_wrong_plan / mis_miss_plan：误踢 / 漏踢监控所选报警方案（别名），默认取第一个方案
    # - mis_wrong_pcs / mis_miss_pcs：误踢 / 漏踢阈值，单位 Pcs/H（1 小时内超过阈值即触发，默认 10）
    # - door_alarm：门打开报警——默认关闭；开启且设备门打开则按 door_mode 选择报警或停机
    # - door_mode： 门触发方式——"alarm"（报警，默认）或 "stop"（停机）
    # - buzzer：    报警蜂鸣器——任意报警触发时蜂鸣提示（默认开启）
    # - bin_taken_timeout：料盒取出未放回超时报警——默认开启；某料盒被取出后，其取出
    #               持续时间超过 bin_taken_timeout_ms（毫秒）即状态灯变红并记报警日志；
    #               若关闭，则不变红但仍在运行日志记录一条提示。
    # - cont_mix / cont_tilt / cont_stick：连续混料 / 连续歪斜 / 连续连料报警——默认均关闭；
    #               连续不良产品数达到对应 Pcs 阈值即记红色报警（不触发停机），恢复后自动解除。
    "features": {
        "auto_clear": True,
        "mis_wrong_alarm": False,
        "mis_wrong_plan": "方案 1",
        "mis_wrong_pcs": 10,
        "mis_miss_alarm": False,
        "mis_miss_plan": "方案 1",
        "mis_miss_pcs": 10,
        "door_alarm": False,
        "door_mode": "alarm",
        "buzzer": True,
        "bin_taken_timeout": True,
        "bin_taken_timeout_ms": 5000,
        # 料盒取出未放回超时报警触发方式——报警方案配置中的「别名」（默认取第一个方案）
        "bin_taken_timeout_plan": "方案 1",
        # 料盒取出未放回超时报警的处理方式——"alarm"（报警，默认）或 "stop"（停机）
        "bin_taken_timeout_mode": "alarm",
        # 满料报警：料盒达满料阈值即触发一条报警（与「料盒满料停机」共用同一阈值）；
        # 默认开启，触发时按 bin_full_plan 选择的报警方案（别名，默认「方案 1」）记录并显示
        "bin_full_alarm": True,
        "bin_full_plan": "方案 1",
        # 满料报警的「收料百分比阈值」：料盒收料百分比达到该值即按所选报警方案报警
        # （与 100% 满料停机报警独立，默认 90%）
        "bin_full_pct": 90,
        # 满料停机：料盒达该百分比即触发停机报警（默认开启，阈值 100%）
        "bin_full_stop": True,
        "bin_full_stop_plan": "方案 1",
        "bin_full_stop_pct": 100,
        "cont_mix": False,
        "cont_mix_pcs": 5,
        "cont_mix_plan": "方案 1",
        "cont_tilt": False,
        "cont_tilt_pcs": 8,
        "cont_tilt_plan": "方案 1",
        "cont_stick": False,
        "cont_stick_pcs": 5,
        "cont_stick_plan": "方案 1",
        "cont_fly": False,
        "cont_fly_pcs": 10,
        "cont_fly_plan": "方案 1",
        # 急停报警：示例演示中急停常态「未开启」，仅以极低概率随机触发一次
        # （需运行 5~60 分钟才可能触发）；触发时状态灯红灯闪（estop_mode 决定
        # 是否叠加蜂鸣）——"blink"（红灯闪）或 "blink_buzzer"（红灯闪+蜂鸣）。
        "estop_alarm": True,
        "estop_mode": "blink",
        # 电磁阀使用寿命报警 / 停机阈值：以「使用寿命阈值（次）」为 100%，
        # 已用动作次数达到该百分比即按所选报警方案报警 / 触发停机；
        # 报警阈值默认 90%，停机阈值默认 100%。（全局统一，与各电磁阀具体寿命无关）
        "valve_alarm_pct": 90,
        "valve_alarm_plan": "方案 1",
        "valve_stop_pct": 100,
        # 电磁阀寿命停机使能开关：默认关闭（不启用）。开启后已用次数达停机阈值才执行停机
        "valve_stop_enabled": False,
        # 门打开报警（触发方式 = 报警）时的报警方案（别名），默认取第一个方案
        "door_alarm_plan": "方案 1",
        # 离子风扇异常报警：默认开启；运行中检测到离子风扇异常即按 ion_fan_plan
        # 选择的报警方案（别名）记录并显示报警（不触发停机）
        "ion_fan_alarm": True,
        "ion_fan_plan": "方案 1",
        # 玻璃盘上下跳动超限报警：默认开启；运行中检测到玻璃盘上下跳动超限即按所选
        # 报警方案（别名）记录并显示报警（不触发停机）
        "glass_disk_jump_alarm": True,
        "glass_disk_jump_plan": "方案 1",
        # 玻璃盘上下跳动超限报警条件：连续超限次数（达到该次数才触发报警），示例值 10 次
        "glass_disk_jump_count": 10,
        # 检测项良率预警：阈值在调试界面「良率预警设置」列按检测项逐行设置，
        # 此处仅选择触发预警时所按的报警方案（别名，默认取第一个方案）
        "item_yield_plan": "方案 1",
    },
    # 状态方案（报警方案配置）：用于报警参数页配置多组状态灯/蜂鸣/持续时长方案
    # - count：显示的方案数量（1-20）
    # - plans：每个方案包含别名、红/绿/黄灯状态、蜂鸣状态、持续时长(ms)、报警延迟时长(ms)
    #   灯状态取值："闪烁"/"开"/"关"；蜂鸣："开"/"关"
    #   持续时长(duration_ms)：报警触发后保持激活的时长，示例 3000ms
    #   报警延迟时长(delay_ms)：状态越界后需持续该时长才真正触发报警（去抖），示例 1000ms
    "state_plans": {
        "count": 10,
        "plans": [
            {"alias": "方案 1", "red": "闪烁", "green": "关", "yellow": "关", "buzzer": "开",
             "stop": "关", "duration_ms": 3000, "delay_ms": 1000, "stop_delay_ms": 5000},
            {"alias": "方案 2", "red": "开", "green": "开", "yellow": "开", "buzzer": "关",
             "stop": "关", "duration_ms": 3000, "delay_ms": 1000, "stop_delay_ms": 5000},
        ] + [
            {"alias": f"方案 {i}", "red": "开", "green": "关", "yellow": "关", "buzzer": "关",
             "stop": "关", "duration_ms": 3000, "delay_ms": 1000, "stop_delay_ms": 5000}
            for i in range(3, 11)
        ],
    },
    # 速度 / 良率报警的「报警方案」选择（按 SQ_KEYS 逐项指定，默认取第一个方案）。
    # 各指标越界报警时按其对应方案记录并显示。
    "sq_plan": {
        "turntable_low": "方案 1", "turntable_high": "方案 1",
        "detect_low": "方案 1", "detect_high": "方案 1",
        "good_low": "方案 1", "cam_yield_low": "方案 1", "recheck_high": "方案 1",
    },
}

# 可变字典（运行时被对话框原地修改，所有已导入模块读到的都是最新值）
ALARM = copy.deepcopy(DEFAULT_ALARM)


def _config_path():
    """配置落盘路径：与 exe 或脚本同目录（优先跟随可执行文件所在目录）。"""
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "alarm_config.json")


def load_alarm_config():
    """启动时加载阈值：文件不存在或损坏则回退到示例默认值。

    注意：结果**原地写回**模块级 ALARM（而非重新绑定），这样其它模块
    `from alarm_config import ALARM` 得到的引用始终有效、不会指向旧字典。
    """
    p = _config_path()
    merged = None
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = copy.deepcopy(DEFAULT_ALARM)
            for k in DEFAULT_ALARM:
                if isinstance(data.get(k), dict):
                    for key, val in data[k].items():
                        if key not in DEFAULT_ALARM[k]:
                            continue
                        # 布尔开关需原样保留（Python 中 bool 是 int 的子类，
                        # 若用 int(val) 会把 True/False 错误地转成 1/0 破坏语义）
                        if isinstance(val, bool):
                            merged[k][key] = bool(val)
                        elif isinstance(val, (int, float)):
                            merged[k][key] = int(val)
                        elif isinstance(val, (list, dict)):
                            merged[k][key] = copy.deepcopy(val)
                        elif isinstance(val, str):
                            merged[k][key] = val
        except Exception:
            merged = None
    if merged is None:
        merged = copy.deepcopy(DEFAULT_ALARM)
    ALARM.clear()
    ALARM.update(merged)


def save_alarm_config():
    """把当前 ALARM（已被对话框原地修改后）写回同目录 alarm_config.json。"""
    p = _config_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(ALARM, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def bin_full_threshold(key):
    """料盒满料停机阈值（件）。"""
    return ALARM["bin_full"].get(key, DEFAULT_ALARM["bin_full"][key])


def valve_life_threshold(key):
    """电磁阀使用寿命阈值（次动作）。"""
    return ALARM["valve_life"].get(key, DEFAULT_ALARM["valve_life"][key])


def sq_threshold(key):
    """速度 / 良率报警阈值（转盘 RPM / 检测 Pcs-Min / 良率·重检率 %）。"""
    return ALARM["speed_quality"].get(key, DEFAULT_ALARM["speed_quality"][key])


def alarm_duration_ms():
    """报警时长（ms）：报警触发后保持激活的时长。"""
    return int(ALARM["alarm_timing"].get("duration_ms", DEFAULT_ALARM["alarm_timing"]["duration_ms"]))


def alarm_delay_ms():
    """报警延时（ms）：状态越界后需持续该时长才真正触发报警（去抖）。"""
    return int(ALARM["alarm_timing"].get("delay_ms", DEFAULT_ALARM["alarm_timing"]["delay_ms"]))


# ------------------------------------------------------------------
# 其他报警功能开关（料盒取出计数自动清零 / 误漏剔除监控 / 门打开报警 / 蜂鸣器）
# ------------------------------------------------------------------
def feature_auto_clear():
    """料仓自动清零：料盒达满料阈值时自动清料并继续运行（默认开启）。"""
    return bool(ALARM["features"].get("auto_clear", DEFAULT_ALARM["features"]["auto_clear"]))


def feature_mis_wrong():
    """OK 良品料仓误踢监控报警：默认关闭；开启后误踢频率(Pcs/H)超阈值即按所选报警方案（别名）报警。"""
    return bool(ALARM["features"].get("mis_wrong_alarm", DEFAULT_ALARM["features"]["mis_wrong_alarm"]))


def mis_wrong_plan():
    """OK 良品料仓误踢监控报警的报警方案（报警方案配置中的「别名」），默认取第一个方案。"""
    return str(ALARM["features"].get("mis_wrong_plan", DEFAULT_ALARM["features"]["mis_wrong_plan"]))


def mis_wrong_threshold():
    """OK 良品料仓误踢监控阈值（Pcs/H）。"""
    return int(ALARM["features"].get("mis_wrong_pcs", DEFAULT_ALARM["features"]["mis_wrong_pcs"]))


def feature_mis_miss():
    """OK 良品料仓漏踢监控报警：默认关闭；开启后漏踢频率(Pcs/H)超阈值即按所选报警方案（别名）报警。"""
    return bool(ALARM["features"].get("mis_miss_alarm", DEFAULT_ALARM["features"]["mis_miss_alarm"]))


def mis_miss_plan():
    """OK 良品料仓漏踢监控报警的报警方案（报警方案配置中的「别名」），默认取第一个方案。"""
    return str(ALARM["features"].get("mis_miss_plan", DEFAULT_ALARM["features"]["mis_miss_plan"]))


def mis_miss_threshold():
    """OK 良品料仓漏踢监控阈值（Pcs/H）。"""
    return int(ALARM["features"].get("mis_miss_pcs", DEFAULT_ALARM["features"]["mis_miss_pcs"]))


def feature_door_alarm():
    """门打开报警：默认关闭；开启且设备门打开则按 door_mode 报警或停机。"""
    return bool(ALARM["features"].get("door_alarm", DEFAULT_ALARM["features"]["door_alarm"]))


def feature_door_mode():
    """门触发方式：'alarm'（报警，默认）或 'stop'（停机）。"""
    return str(ALARM["features"].get("door_mode", DEFAULT_ALARM["features"]["door_mode"]))


def feature_buzzer():
    """报警蜂鸣器：任意报警触发时蜂鸣提示（默认开启）。"""
    return bool(ALARM["features"].get("buzzer", DEFAULT_ALARM["features"]["buzzer"]))


# ------------------------------------------------------------------
# 料盒取出未放回超时 + 连续混料/歪斜/连料 报警开关与阈值
# ------------------------------------------------------------------
def feature_bin_taken_timeout():
    """料盒取出未放回超时报警：默认开启；某料盒取出持续时间超过阈值(ms)即变红报警。"""
    return bool(ALARM["features"].get("bin_taken_timeout", DEFAULT_ALARM["features"]["bin_taken_timeout"]))


def bin_taken_timeout_ms():
    """料盒取出未放回超时阈值（毫秒）。"""
    return int(ALARM["features"].get("bin_taken_timeout_ms", DEFAULT_ALARM["features"]["bin_taken_timeout_ms"]))


def bin_taken_timeout_plan():
    """料盒取出未放回超时报警的报警方案（报警方案配置中的「别名」），默认取第一个方案。"""
    return str(ALARM["features"].get("bin_taken_timeout_plan",
                                    DEFAULT_ALARM["features"]["bin_taken_timeout_plan"]))


def feature_bin_taken_timeout_mode():
    """料盒取出未放回超时报警的处理方式：'alarm'（报警，默认）或 'stop'（停机）。"""
    return str(ALARM["features"].get("bin_taken_timeout_mode",
                                    DEFAULT_ALARM["features"]["bin_taken_timeout_mode"]))


def feature_bin_full_alarm():
    """满料报警：料盒达满料阈值即触发一条报警（与「料盒满料停机」共用同一阈值），默认开启。"""
    return bool(ALARM["features"].get("bin_full_alarm", DEFAULT_ALARM["features"]["bin_full_alarm"]))


def bin_full_plan():
    """满料报警的报警方案（报警方案配置中的「别名」），默认取第一个方案。"""
    return str(ALARM["features"].get("bin_full_plan", DEFAULT_ALARM["features"]["bin_full_plan"]))


def bin_full_pct():
    """满料报警的「收料百分比阈值」（%）：料盒收料百分比达到该值即按所选报警方案报警（默认 90%）。"""
    return int(ALARM["features"].get("bin_full_pct", DEFAULT_ALARM["features"]["bin_full_pct"]))


def feature_bin_full_stop():
    """满料停机：料盒达满料停机阈值百分比即触发停机报警，默认开启。"""
    return bool(ALARM["features"].get("bin_full_stop", DEFAULT_ALARM["features"]["bin_full_stop"]))


def bin_full_stop_pct():
    """满料停机的「收料百分比阈值」（%）：料盒收料百分比达到该值即触发停机（默认 100%）。"""
    return int(ALARM["features"].get("bin_full_stop_pct", DEFAULT_ALARM["features"]["bin_full_stop_pct"]))


def bin_full_stop_plan():
    """满料停机的报警方案（报警方案配置中的「别名」），默认取第一个方案。"""
    return str(ALARM["features"].get("bin_full_stop_plan", DEFAULT_ALARM["features"]["bin_full_stop_plan"]))


def feature_cont_mix():
    """连续混料报警：默认关闭；连续混料产品数达到阈值(Pcs)即报警。"""
    return bool(ALARM["features"].get("cont_mix", DEFAULT_ALARM["features"]["cont_mix"]))


def cont_mix_threshold():
    """连续混料报警阈值（Pcs）。"""
    return int(ALARM["features"].get("cont_mix_pcs", DEFAULT_ALARM["features"]["cont_mix_pcs"]))


def feature_cont_tilt():
    """连续歪斜报警：默认关闭；连续歪斜产品数达到阈值(Pcs)即报警。"""
    return bool(ALARM["features"].get("cont_tilt", DEFAULT_ALARM["features"]["cont_tilt"]))


def cont_tilt_threshold():
    """连续歪斜报警阈值（Pcs）。"""
    return int(ALARM["features"].get("cont_tilt_pcs", DEFAULT_ALARM["features"]["cont_tilt_pcs"]))


def feature_cont_stick():
    """连续连料报警：默认关闭；连续连料产品数达到阈值(Pcs)即报警。"""
    return bool(ALARM["features"].get("cont_stick", DEFAULT_ALARM["features"]["cont_stick"]))


def cont_stick_threshold():
    """连续连料报警阈值（Pcs）。"""
    return int(ALARM["features"].get("cont_stick_pcs", DEFAULT_ALARM["features"]["cont_stick_pcs"]))


def cont_mix_plan():
    """连续混料报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("cont_mix_plan",
                                     DEFAULT_ALARM["features"]["cont_mix_plan"]))


def cont_tilt_plan():
    """连续歪斜报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("cont_tilt_plan",
                                     DEFAULT_ALARM["features"]["cont_tilt_plan"]))


def cont_stick_plan():
    """连续连料报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("cont_stick_plan",
                                     DEFAULT_ALARM["features"]["cont_stick_plan"]))


def feature_cont_fly():
    """连续飞料报警：默认关闭；连续飞料产品数达到阈值(Pcs)即报警。"""
    return bool(ALARM["features"].get("cont_fly", DEFAULT_ALARM["features"]["cont_fly"]))


def cont_fly_threshold():
    """连续飞料报警阈值（Pcs）。"""
    return int(ALARM["features"].get("cont_fly_pcs", DEFAULT_ALARM["features"]["cont_fly_pcs"]))


def cont_fly_plan():
    """连续飞料报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("cont_fly_plan",
                                     DEFAULT_ALARM["features"]["cont_fly_plan"]))


def feature_estop_alarm():
    """急停报警：默认开启；急停被按下（示例为极低概率随机触发）时状态灯红灯闪（+可选蜂鸣）。"""
    return bool(ALARM["features"].get("estop_alarm", DEFAULT_ALARM["features"]["estop_alarm"]))


def estop_mode():
    """急停报警提示方式：'blink'（红灯闪）或 'blink_buzzer'（红灯闪+蜂鸣）。默认红灯闪。"""
    return str(ALARM["features"].get("estop_mode", DEFAULT_ALARM["features"]["estop_mode"]))


# ------------------------------------------------------------------
# 电磁阀使用寿命：报警 / 停机（百分比，以使用寿命阈值为 100%）
# ------------------------------------------------------------------
def valve_alarm_pct():
    """电磁阀寿命报警阈值（%）：已用动作次数达到该百分比即按所选方案报警（默认 90%）。"""
    return int(ALARM["features"].get("valve_alarm_pct", DEFAULT_ALARM["features"]["valve_alarm_pct"]))


def valve_alarm_plan():
    """电磁阀寿命报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("valve_alarm_plan", DEFAULT_ALARM["features"]["valve_alarm_plan"]))


def valve_stop_pct():
    """电磁阀寿命停机阈值（%）：已用动作次数达到该百分比即触发停机（默认 100%）。"""
    return int(ALARM["features"].get("valve_stop_pct", DEFAULT_ALARM["features"]["valve_stop_pct"]))


def valve_stop_enabled():
    """电磁阀寿命停机使能开关：默认关闭（不启用）。"""
    return bool(ALARM["features"].get("valve_stop_enabled",
                                      DEFAULT_ALARM["features"]["valve_stop_enabled"]))


def feature_door_alarm_plan():
    """门打开报警（触发方式 = 报警）所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("door_alarm_plan", DEFAULT_ALARM["features"]["door_alarm_plan"]))


def feature_ion_fan_alarm():
    """离子风扇异常报警：默认开启；检测到离子风扇异常时按所选报警方案报警（不触发停机）。"""
    return bool(ALARM["features"].get("ion_fan_alarm",
                                      DEFAULT_ALARM["features"]["ion_fan_alarm"]))


def ion_fan_plan():
    """离子风扇异常报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("ion_fan_plan",
                                     DEFAULT_ALARM["features"]["ion_fan_plan"]))


def feature_glass_disk_jump_alarm():
    """玻璃盘上下跳动超限报警：默认开启；检测到玻璃盘上下跳动超限时按所选报警方案报警（不触发停机）。"""
    return bool(ALARM["features"].get("glass_disk_jump_alarm",
                                      DEFAULT_ALARM["features"]["glass_disk_jump_alarm"]))


def glass_disk_jump_plan():
    """玻璃盘上下跳动超限报警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("glass_disk_jump_plan",
                                     DEFAULT_ALARM["features"]["glass_disk_jump_plan"]))


def feature_glass_disk_jump_count():
    """玻璃盘上下跳动超限报警条件：连续超限次数（默认 10 次，达到该次数才触发报警）。"""
    return int(ALARM["features"].get("glass_disk_jump_count",
                                    DEFAULT_ALARM["features"]["glass_disk_jump_count"]))


def sq_plan(key):
    """速度 / 良率报警项（key）所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM.get("sq_plan", {}).get(key, DEFAULT_ALARM.get("sq_plan", {}).get(key, "方案 1")))


def item_yield_plan():
    """检测项良率预警所选报警方案（别名），默认取第一个方案。"""
    return str(ALARM["features"].get("item_yield_plan",
                                     DEFAULT_ALARM["features"]["item_yield_plan"]))


# ------------------------------------------------------------------
# 报警参数 - 状态方案
# ------------------------------------------------------------------
def state_plans_count():
    """状态方案数量（1-20）。"""
    return int(ALARM["state_plans"].get("count", DEFAULT_ALARM["state_plans"]["count"]))


def state_plans():
    """当前所有状态方案列表（深拷贝，防止外部修改影响运行时配置）。"""
    return copy.deepcopy(ALARM["state_plans"].get("plans", DEFAULT_ALARM["state_plans"]["plans"]))


def state_plan_aliases():
    """返回所有状态方案的「别名」列表，供下拉选择（如料盒满料停机页的报警方案选择）。"""
    return [p.get("alias", f"方案 {i + 1}") for i, p in enumerate(state_plans())]


def state_plan_by_alias(alias):
    """按别名查找某个状态方案（深拷贝）；找不到返回 None。运行时按报警方案显示时使用。"""
    for p in state_plans():
        if p.get("alias") == alias:
            return p
    return None


# 模块导入即加载一次（文件缺失时回退示例默认值）
load_alarm_config()
