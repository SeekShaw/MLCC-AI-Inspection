import os

# 烘焙用户中心版本到本 exe：A = 单栏卡片堆叠（沿用原设计）
os.environ["USER_CENTER_VARIANT"] = "A"

from app import run

if __name__ == "__main__":
    run()
