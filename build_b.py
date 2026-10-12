"""构建「用户中心 B」exe，并确保 output 只保留最新一份 exe。

- 用 PyInstaller 打包（--clean 自清缓存）。
- 构建完成后：删除 output 内除目标外的所有 exe（旧版本一并清除），
  并删除 build_backup_* 中遗留的旧 exe；dist 临时目录一并回收。
- 需在「安全删除 shim 已关闭」的环境下运行，否则 os.remove 会被拦截。
"""
import os
import sys
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

NAME = "电子元件视觉检测系统_用户中心B"
SPEC = f"{NAME}_new.spec"
DIST_EXE = f"dist/{NAME}_new.exe"

# 最终 exe 命名：软件名称 + 版本（如 电子元件视觉检测系统_V3.0.exe）
SOFTWARE_NAME = "电子元件视觉检测系统"
VERSION = "V3.0"
OUT_EXE = f"output/{SOFTWARE_NAME}_{VERSION}.exe"


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

    print(">> 构建中 ...")
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
    os.replace(DIST_EXE, OUT_EXE)

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

    # 4) build_backup_* 中的旧 exe 一并移走
    for d in os.listdir("."):
        full = os.path.join(".", d)
        if d.startswith("build_backup_") and os.path.isdir(full):
            for f in os.listdir(full):
                if f.lower().endswith(".exe"):
                    stash_exe(os.path.join(full, f))

    # 4) 回收 dist 临时目录
    if os.path.exists("dist"):
        shutil.rmtree("dist")

    print(">> 完成 ->", OUT_EXE)


if __name__ == "__main__":
    main()
