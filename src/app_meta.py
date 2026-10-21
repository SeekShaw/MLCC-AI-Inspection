# -*- coding: utf-8 -*-
"""软件元信息：全项目唯一版本号来源。

各处显示与写入均以本文件为准，保证一致：
- exe 详细信息（文件属性）：build_b.py 构建时读取并写入版本资源；
- 启动画面版本行：startup_splash.py 读取；
- 「关于」页面版本：app.py APP_VERSION 读取。

版本号格式 major.minor.patch.build（当前 3.0.0.0）：
- 每次运行 build_b.py 发布成功后，自动把第 3 位（patch）+1；
- patch 到 10 时向第 2 位进位、patch 归 0（如 3.0.9.0 → 3.1.0.0）；
- exe 文件名：EcompVision Inspector（不含版本号）。
"""
APP_NAME_EN = "EcompVision Inspector"
APP_VERSION = "3.0.5.0"
