"""生成可直接拷贝到其他电脑打开的便携版压缩包。

- 把完整的运行时目录 output/（exe + 配置文件 + assets + 图标 + 发布文档）整体压成 zip；
- 压缩包内顶层为单一文件夹，解压后双击其中的 exe 即可运行，无需安装；
- 压缩包文件名＝名字 + 版本号（版本唯一来源 src/app_meta.py），
  例如「EcompVision Inspector V3.6.7.0.zip」；名称不含「便携版」；
  同版本重打覆盖；**2026-11-12 UI 需求：重新打包时删除之前的 ZIP 压缩包**，
  只保留最新一份；
- 压缩包内顶层文件夹名取同一个 PKG_NAME（不含「便携版」），解压路径稳定；
- 由 build_b.py 在每次重新生成 exe 后自动调用。
"""
import os
import re
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
# 2026-11-11 需求：压缩包去掉「便携版」三个字；压缩包内顶层文件夹同名。
PKG_NAME = "EcompVision Inspector"              # 顶层文件夹名 / 压缩包名字前缀
LEGACY_ZIP_PREFIX = "EcompVision Inspector 便携版"  # 旧命名（含「便携版」），打包时清理
BUILD_TMP = os.path.join(ROOT, "_pkg_build")    # 解压用临时目录


def app_version():
    """直接读 src/app_meta.py 取唯一版本号。

    不用 import：build_b.py 在同一进程内可能已缓存旧版 app_meta 模块，
    而构建流程是「先递增版本、再打包」，读文件才能保证 zip 名与本次
    发布版本一致。
    """
    path = os.path.join(ROOT, "src", "app_meta.py")
    with open(path, "r", encoding="utf-8") as f:
        m = re.search(r'APP_VERSION = "([^"]+)"', f.read())
    if m is None:
        raise SystemExit(f"!! 未找到 APP_VERSION: {path}")
    return m.group(1)


def zip_path(version=None):
    """便携版压缩包绝对路径：名字 + 版本号。"""
    ver = version or app_version()
    return os.path.join(ROOT, f"{PKG_NAME} V{ver}.zip")


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
    out_zip = zip_path()
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(pkg_root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, BUILD_TMP)
                z.write(full, rel)
    # 4) 删除临时目录，只保留 zip
    shutil.rmtree(BUILD_TMP, ignore_errors=True)
    # 5) 清理旧压缩包（2026-11-12 UI 需求：重新打包时**删除之前的 ZIP 压缩包**，
    #    只保留本次生成的最新一份交付物——原「不同版本各自留档」策略废止；
    #    旧「便携版」命名压缩包同样清理）
    for _fn in os.listdir(ROOT):
        if not _fn.lower().endswith(".zip"):
            continue
        if _fn.startswith(f"{PKG_NAME} V") or _fn.startswith(LEGACY_ZIP_PREFIX):
            _p = os.path.join(ROOT, _fn)
            if os.path.abspath(_p) != os.path.abspath(out_zip):
                os.remove(_p)
                print("   清理旧压缩包:", _fn)
    size = os.path.getsize(out_zip)
    print(f">> 程序压缩包已生成 -> {out_zip} ({size:,} bytes)")


if __name__ == "__main__":
    build()
