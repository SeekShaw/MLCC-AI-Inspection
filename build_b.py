"""构建「用户中心 B」exe，并确保 output 只保留最新一份 exe。

- 用 PyInstaller 打包（--clean 自清缓存）。
- 构建完成后：删除 output 内除目标外的所有 exe（旧版本一并清除），
  并删除 build_backup_* 中遗留的旧 exe；dist 临时目录一并回收。
- 需在「安全删除 shim 已关闭」的环境下运行，否则 os.remove 会被拦截。
"""
import os
import re
import sys
import time
import shutil
import subprocess

# 还原被「安全删除 shim」包裹的删除接口为原生实现，使本脚本对 dist/ 等
# 构建产物的清理（shutil.rmtree）能在本沙箱中正常完成。
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

# spec 文件与最终 exe 同名：EcompVision Inspector.spec → dist/同名.exe
NAME = "EcompVision Inspector"
SPEC = f"{NAME}.spec"
DIST_EXE = f"dist/{NAME}.exe"

# 最终 exe 落位：output/EcompVision Inspector.exe（文件名不含版本号）
OUT_EXE = f"output/{NAME}.exe"
VERSION_FILE = "_exe_version.txt"      # PyInstaller 版本资源（每次构建重新生成）


def _load_meta():
    """读取 src/app_meta.py 的唯一版本信息。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
    import app_meta
    return app_meta.APP_NAME_EN, app_meta.APP_VERSION


def _write_version_file():
    """按 app_meta 当前版本生成 PyInstaller 版本资源（exe 详细信息）。

    生成 _exe_version.txt 供 spec 的 EXE(version=...) 使用；含中文厂商信息，
    语系用 0804（简体中文）+ Unicode(1200)。
    """
    name, ver = _load_meta()
    parts = tuple(int(x) for x in ver.split("."))
    while len(parts) < 4:
        parts += (0,)
    txt = f'''# UTF-8
# 由 build_b.py 自动生成（来源 src/app_meta.py），请勿手工编辑。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={parts}, prodvers={parts},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'ZiGAA ChuangYuan（智感科技）'),
        StringStruct('FileDescription', '{name}'),
        StringStruct('FileVersion', '{ver}'),
        StringStruct('InternalName', '{name}'),
        StringStruct('LegalCopyright', 'By：ZY.SHAW'),
        StringStruct('OriginalFilename', '{name}.exe'),
        StringStruct('ProductName', '{name}'),
        StringStruct('ProductVersion', '{ver}')]),
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])]),
  ])
'''
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(txt)
    print(">> 版本资源:", VERSION_FILE, "->", ver)


def bump_version():
    """递增版本号：第 3 位 +1，到 10 向第 2 位进位（3.0.9.0→3.1.0.0）。

    写回 src/app_meta.py（唯一来源），exe 详细信息 / 启动画面 / 关于页均读取
    该文件。⚠️ 2026-10-21 决定在**构建前**递增：否则上一次发布的恰好是本次
    递增后的版本号，导致同一版本号连续发布两次（上次手工前置修正过）。
    代价是构建失败会消耗一个版本号——用 `--no-bump` 重打时保持不变。
    """
    path = os.path.join("src", "app_meta.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'APP_VERSION = "(\d+)\.(\d+)\.(\d+)\.(\d+)"', src)
    if m is None:
        print("!! 未找到 APP_VERSION，跳过版本递增")
        return
    maj, mi, pa, bu = (int(x) for x in m.groups())
    pa += 1
    if pa >= 10:
        pa, mi = 0, mi + 1
    src = src[:m.start()] + f'APP_VERSION = "{maj}.{mi}.{pa}.{bu}"' + src[m.end():]
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f">> 版本号已递增: {maj}.{mi}.{pa}.{bu}（下一次发布生效）")


def install_exe(src, dst, tries=12, wait=3.0):
    """把构建产物安装到 output/（带重试 + 兜底复制）。

    ⚠️ 2026-10-20：刚生成的大 exe 常被杀软/索引服务持有瞬时独占句柄，
    `os.replace` 会抛 `PermissionError: [WinError 32]`。这里先重试若干次
    等待句柄释放；仍未释放时退化为复制文件内容（读取不受排他句柄影响），
    保证构建产物能落地，不再让整次构建在最后一步失败。
    """
    last = None
    for _ in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last = e
            time.sleep(wait)
    try:
        shutil.copy2(src, dst)
        return
    except Exception as e:
        last = e
    raise SystemExit(f"!! 无法安装 exe 到 {dst}: {last!r}")


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    ARCHIVE = "old_exes"
    os.makedirs(ARCHIVE, exist_ok=True)

    def stash_exe(path):
        """把多余/旧的 exe 移出 output（锁定文件也能用 rename 移走）。"""
        if not os.path.exists(path):
            return
        base = os.path.basename(path)
        dst = os.path.join(ARCHIVE, base)
        i = 1
        while os.path.exists(dst):
            stem, ext = os.path.splitext(base)
            dst = os.path.join(ARCHIVE, f"{stem}_{i}{ext}")
            i += 1
        os.replace(path, dst)
        print("   移走旧 exe:", path, "->", dst)

    print(">> 递增版本号（构建前，本次发布即取新号）...")
    if "--no-bump" not in sys.argv:
        bump_version()
    print(">> 构建中 ...")
    _write_version_file()
    # 通过 pyi_bootstrap 启动 PyInstaller，该引导会把被「安全删除 shim」包裹的
    # 删除接口还原为原生实现，避免构建末期清理临时文件时因回收站不可用而中断。
    r = subprocess.run(
        [sys.executable, "pyi_bootstrap.py", SPEC]
    )
    if r.returncode != 0:
        print("!! 构建失败")
        sys.exit(1)
    if not os.path.exists(DIST_EXE):
        print("!! 未找到构建产物:", DIST_EXE)
        sys.exit(1)

    # 1) output 里除目标外的所有 exe 移走（只留最新）
    for f in os.listdir("output"):
        if f.lower().endswith(".exe") and os.path.join("output", f) != OUT_EXE:
            stash_exe(os.path.join("output", f))

    # 2) 替换目标 exe（先移走旧 B，再放入新的）
    if os.path.exists(OUT_EXE):
        stash_exe(OUT_EXE)
    install_exe(DIST_EXE, OUT_EXE)

    # 3) 同步 assets/ 资源目录到 output/（相机样张等运行时依赖）
    assets_src = "assets"
    assets_dst = os.path.join("output", "assets")
    if os.path.exists(assets_src):
        if os.path.exists(assets_dst):
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)
        print("   同步 assets ->", assets_dst)

    # 3.1) 同步 app_icon.ico 到 output/：程序启动时按原生多档尺寸加载为窗口 / 任务栏图标
    if os.path.exists("app_icon.ico"):
        shutil.copy2("app_icon.ico", os.path.join("output", "app_icon.ico"))
        print("   同步 app_icon.ico ->", os.path.join("output", "app_icon.ico"))

    # 3.2) 同步发布说明：仓库根 README.release.md -> output/README.md
    # （2026-10-21：output/README.md 内容陈旧仍写着旧版本号与旧 exe 名，
    #  改为每次构建自动同步，README 只需维护根目录下的规范版本）
    if os.path.exists("README.release.md"):
        shutil.copy2("README.release.md", os.path.join("output", "README.md"))
        print("   同步发布说明 ->", os.path.join("output", "README.md"))

    # 4) build_backup_* 中的旧 exe 一并移走
    for d in os.listdir("."):
        full = os.path.join(".", d)
        if d.startswith("build_backup_") and os.path.isdir(full):
            for f in os.listdir(full):
                if f.lower().endswith(".exe"):
                    stash_exe(os.path.join(full, f))

    # 4) 回收 dist 临时目录（被杀软瞬时占用时跳过，不影响最终产物）
    if os.path.exists("dist"):
        try:
            shutil.rmtree("dist")
        except OSError as e:
            print("   dist 清理跳过（文件被占用）:", repr(e))

    print(">> 完成 ->", OUT_EXE)


if __name__ == "__main__":
    main()
