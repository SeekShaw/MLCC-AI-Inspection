# -*- coding: utf-8 -*-
"""软件元信息：全项目唯一版本号来源。

各处显示与写入均以本文件为准，保证一致：
- exe 详细信息（文件属性）：build_b.py 构建时读取并写入版本资源；
- 启动画面版本行：startup_splash.py 读取；
- 「关于」页面版本：app.py APP_VERSION 读取。

版本号格式 major.minor.patch.build（2026-11-12 版本号规则，用户指定）：
- 仅修复 bug：第 4 位（build）+1（如 3.8.3.0 → 3.8.3.1），
  构建时用 `python build_b.py --bug`；
- 功能改善或新增：第 3 位（patch）+1，第 4 位重新从 0 计数
  （如 3.8.2.x → 3.8.3.0，此后 bug 修复从 3.8.3.1 开始递增）；
- **仅 UI 改善**（界面观感 / 布局调整，不含功能与数据逻辑变化，2026-11-12 补充）：
  第 4 位（build）+1，可递增到 99，满 100 向第 3 位进位归 0
  （如 3.8.5.0 → 3.8.5.1 → … → 3.8.5.99 → 3.8.6.0）；
- patch 到 10 时向第 2 位进位、patch 归 0（如 3.0.9.0 → 3.1.0.0）；
- exe 文件名：EcompVision Inspector（不含版本号）。
"""
APP_NAME_EN = "EcompVision Inspector"
APP_VERSION = "3.8.5.9"
