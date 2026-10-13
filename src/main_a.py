import os
import sys

# 烘焙用户中心版本到本 exe：A = 单栏卡片堆叠（沿用原设计）
os.environ["USER_CENTER_VARIANT"] = "A"

# 启动加载窗：先于 app 的重导入创建并显示「正在打开 + 进度」
from PyQt6.QtWidgets import QApplication
from startup_splash import StartupSplash

_qapp = QApplication(sys.argv)
_splash = StartupSplash()
_splash.show()
_splash.set_status("正在打开…")
_qapp.processEvents()

from app import run

if __name__ == "__main__":
    run(splash=_splash)
