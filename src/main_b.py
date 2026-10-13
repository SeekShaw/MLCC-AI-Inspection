import os
import sys

# 烘焙用户中心版本到本 exe：B = 左侧导航 + 右侧内容（设置面板式）
os.environ["USER_CENTER_VARIANT"] = "B"

# 启动加载窗：先于 app 的重导入（production_view / debug_view 等）创建并显示，
# 使双击 exe 后立即出现「正在打开 + 进度」反馈，覆盖导入与主界面构建全过程。
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
