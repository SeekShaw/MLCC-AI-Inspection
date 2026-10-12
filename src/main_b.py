import os

# 烘焙用户中心版本到本 exe：B = 左侧导航 + 右侧内容（设置面板式）
os.environ["USER_CENTER_VARIANT"] = "B"

from app import run

if __name__ == "__main__":
    run()
