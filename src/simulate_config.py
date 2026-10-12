"""模拟生产配置：开关 + 各相机模拟图片来源路径。

落盘为 `simulate_production_config.json`（与 exe 或脚本同目录）。
沿用项目既有约定（见 `ImageSaveDialog._cfg_path`）：优先跟随可执行文件目录，
否则用脚本所在目录，保证开发机与打包后行为一致。
"""
import json
import os

CAM_NAMES = [f"相机{i}" for i in range(1, 9)]
CFG_NAME = "simulate_production_config.json"


def cfg_path():
    """配置落盘路径：与 exe 或脚本同目录（优先跟随可执行文件所在目录）。"""
    import sys
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, CFG_NAME)


def default_cfg():
    """默认配置：开关默认**关闭**，各相机图片路径为空。"""
    return {"enabled": False, "paths": {cam: "" for cam in CAM_NAMES}}


def load_cfg():
    """读取配置；文件缺失或损坏时返回默认配置（不抛异常）。"""
    try:
        with open(cfg_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_cfg()
    if not isinstance(data, dict):
        return default_cfg()
    cfg = default_cfg()
    cfg["enabled"] = bool(data.get("enabled", False))
    paths = data.get("paths")
    if isinstance(paths, dict):
        for cam in CAM_NAMES:
            cfg["paths"][cam] = str(paths.get(cam, "") or "")
    return cfg


def save_cfg(cfg):
    """写回配置；失败静默（演示功能不应因落盘异常打断界面）。"""
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass