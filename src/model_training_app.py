# -*- coding: utf-8 -*-
"""「模型训练助手」独立进程入口（2026-11-12 修订：改为独立进程页面）。

由主程序 `app._open_model_training` 以 **独立分离进程** 启动（subprocess，独立 PID），
与主程序 MLCC Visual inspection software 互不干扰：主程序崩溃/退出均不影响本窗口，
本窗口可独立最小化 / 隐藏 / 关闭。当前页面为占位页（`model_training_page`），
后续各训练模块真实功能落地后再替换或改为启动外部专业软件。

直接运行 `python model_training_app.py` 亦可独立调试本页面。
"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from model_training_page import ModelTrainingPage


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("模型训练助手")
    win = ModelTrainingPage()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
