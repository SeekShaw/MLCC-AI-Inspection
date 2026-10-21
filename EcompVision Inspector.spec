# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（用户中心 B 版：左侧导航 + 右侧内容）。

由 build_b.py 调用：
    python pyi_bootstrap.py "EcompVision Inspector.spec"

产物：dist/EcompVision Inspector.exe
     （单文件、无控制台窗口、使用 app_icon.ico 作为 exe 图标；
       spec 文件名与最终 exe 同名：EcompVision Inspector）

exe 详细信息（文件属性里的产品名 / 版本号）由 build_b.py 依据
src/app_meta.py 生成的 _exe_version.txt 注入；版本号唯一来源
app_meta.APP_VERSION，与启动画面 / 关于页保持一致。

说明：运行期所需的 assets/（相机样张）与各配置文件（device_config.json /
alarm_config.json / users.json / theme.json 等）均由程序在 exe 同级目录
生成或由 build_b.py 复制，故此处无需打包 datas。
"""

import os

NAME = "EcompVision Inspector"
_verfile = os.path.join(SPECPATH, "_exe_version.txt")

a = Analysis(
    ["src/main_b.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    # simulate_config 在 SimulateProductionDialog.__init__ 内按需 import，
    # PyInstaller 的静态分析通常能扫到函数内 import，但显式列出更保险
    # （漏掉会在打包后运行时报 ModuleNotFoundError，且只在点击按钮时才暴露）。
    hiddenimports=["simulate_config", "app_meta"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app_icon.ico",
    version=_verfile if os.path.exists(_verfile) else None,
)
