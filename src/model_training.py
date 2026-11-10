"""「模型训练助手」外部程序启动器。

点击左侧导航或顶部标题栏「模型训练助手」时，以**独立进程**启动另一套模型训练软件：
不阻塞本程序界面、不等待子进程、本程序退出也不影响外部软件继续运行。

目标程序路径优先级：
1) exe 同级 ``model_training.json`` 的 ``exe_path``（用户首次选择后记住）
2) exe 同级 / 项目根下的常见候选文件名
3) 都找不到时弹出文件选择框，由用户指定一次并记住，之后直接启动
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = "model_training.json"

# 现场部署时把模型训练软件放在本程序 exe 同级目录即可自动识别
CANDIDATES = (
    "模型训练助手.exe",
    "ModelTrainingAssistant.exe",
    "ModelTraining.exe",
    "ModelTrainer.exe",
    "模型训练.exe",
    "模型训练助手/模型训练助手.exe",
    "ModelTraining/ModelTraining.exe",
)


def base_dir() -> Path:
    """打包后取 exe 所在目录；源码运行取项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return base_dir() / CONFIG_NAME


def read_target() -> str:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        return str(data.get("exe_path") or "")
    except Exception:
        return ""


def write_target(path: str) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"exe_path": str(path)},
                            ensure_ascii=False, indent=2), encoding="utf-8")


def clear_target() -> None:
    try:
        config_path().unlink(missing_ok=True)
    except Exception:
        pass


def resolve_target() -> Path | None:
    cfg = read_target()
    if cfg and Path(cfg).is_file():
        return Path(cfg)
    base = base_dir()
    for name in CANDIDATES:
        p = base / name
        if p.is_file():
            return p
    return None


def spawn_detached(target: os.PathLike | str, args=None) -> tuple[bool, str]:
    """以独立进程启动外部程序：不等待、不继承控制台、主程序退出不影响它。"""
    path = str(target)
    if not os.path.isfile(path):
        return False, f"目标程序不存在：{path}"
    try:
        kwargs = {"cwd": str(Path(path).parent), "close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([path, *[str(a) for a in (args or [])]], **kwargs)
        return True, path
    except Exception as exc:
        return False, str(exc)


def open_model_training(parent=None) -> tuple[bool, str]:
    """UI 入口：解析目标 → 必要时让用户选择 → 独立启动 → 返回结果。

    返回 ``(是否启动成功, 说明文字)``。取消选择返回 ``(False, "已取消")``，
    不抛异常，保证本程序始终可继续运行。
    """
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    target = resolve_target()
    if target is None:
        chosen, _ = QFileDialog.getOpenFileName(
            parent, "选择模型训练助手程序", str(base_dir()),
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if not chosen:
            return False, "已取消"
        if not Path(chosen).is_file():
            QMessageBox.warning(parent, "模型训练助手", "所选程序不存在，未启动。")
            return False, "所选程序不存在"
        # 记住选择，下次点击直接启动（无需重复选择）
        try:
            write_target(chosen)
        except Exception:
            pass
        target = Path(chosen)

    ok, msg = spawn_detached(target)
    if not ok:
        # 目标已失效：清掉旧配置并提示重新选择，避免每次都启动失败
        clear_target()
        QMessageBox.warning(
            parent, "模型训练助手",
            f"未能启动模型训练助手：\n{msg}\n\n请重新点击并选择正确的程序路径。")
    return ok, msg
