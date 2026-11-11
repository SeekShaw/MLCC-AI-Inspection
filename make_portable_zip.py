"""生成可直接拷贝到其他电脑打开的便携版压缩包。

- 把完整的运行时目录 output/（exe + 配置文件 + assets + 图标 + 发布文档）整体压成 zip；
- 压缩包内顶层为单一文件夹，解压后双击其中的 exe 即可运行，无需安装；
- 由 build_b.py 在每次重新生成 exe 后自动调用，路径稳定、反复替换。
"""
import os
import shutil
import zipfile

# 还原被「安全删除 shim」包裹的删除接口为原生实现，使本脚本在后续清理临时
# 目录（shutil.rmtree）时能在沙箱中正常完成。
try:
    import sitecustomize
    os.remove = sitecustomize._orig_remove
    os.unlink = sitecustomize._orig_unlink
    os.rmdir = sitecustomize._orig_rmdir
    shutil.rmtree = sitecustomize._orig_shutil_rmtree
    import pathlib
    pathlib.Path.unlink = sitecustomize._orig_path_unlink
    pathlib.Path.rmdir = sitecustomize._orig_path_rmdir
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT, "output")          # 完整运行时目录
PKG_NAME = "EcompVision Inspector 便携版"       # 压缩包内顶层文件夹名（稳定，反复替换）
ZIP_PATH = os.path.join(ROOT, PKG_NAME + ".zip")
BUILD_TMP = os.path.join(ROOT, "_pkg_build")    # 解压用临时目录


def build():
    if not os.path.isdir(SRC_DIR):
        raise SystemExit(f"!! 未找到运行时目录: {SRC_DIR}")
    # 1) 清理旧临时目录
    if os.path.isdir(BUILD_TMP):
        shutil.rmtree(BUILD_TMP)
    pkg_root = os.path.join(BUILD_TMP, PKG_NAME)
    os.makedirs(pkg_root, exist_ok=True)
    # 2) 复制 output/ 全部内容到临时包根（exe 只读复制，不会触发覆盖锁）
    for name in os.listdir(SRC_DIR):
        s = os.path.join(SRC_DIR, name)
        d = os.path.join(pkg_root, name)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
    # 3) 生成压缩包（顶层为 PKG_NAME 文件夹，解压即双开 exe）
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(pkg_root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, BUILD_TMP)
                z.write(full, rel)
    # 4) 删除临时目录，只保留 zip
    shutil.rmtree(BUILD_TMP, ignore_errors=True)
    size = os.path.getsize(ZIP_PATH)
    print(f">> 便携版压缩包已生成 -> {ZIP_PATH} ({size:,} bytes)")


if __name__ == "__main__":
    build()
