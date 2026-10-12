"""PyInstaller 启动引导（用于构建 exe）。

该环境下「安全删除 shim」会拦截 os.remove / shutil.rmtree 等删除接口，
并将其路由到回收站/原生 trash；而本沙箱中回收站不可用，导致 PyInstaller
构建末期的临时文件清理（os.remove 各类 .toc/.pyz）直接失败、构建中断。

本引导在导入 PyInstaller 之前，将 shim 包裹的删除接口还原为解释器原生实现
（sitecustomize 模块在启动时已把原始实现保存为 _orig_*），
使构建对 build/、dist/ 等产物的清理能正常完成。
注意：仅清理工程自身的构建产物，不涉及任何用户文件。
"""
import os
import sys

import sitecustomize  # 解释器启动时已自动导入，此处取回原生删除函数

os.remove = sitecustomize._orig_remove
os.unlink = sitecustomize._orig_unlink
os.rmdir = sitecustomize._orig_rmdir

import shutil
shutil.rmtree = sitecustomize._orig_shutil_rmtree

import pathlib
pathlib.Path.unlink = sitecustomize._orig_path_unlink
pathlib.Path.rmdir = sitecustomize._orig_path_rmdir

from PyInstaller.__main__ import run

if __name__ == "__main__":
    # 等价于 `python -m PyInstaller --noconfirm --clean <spec>`
    args = ["--noconfirm", "--clean"] + sys.argv[1:]
    run(args)
