import sys

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
