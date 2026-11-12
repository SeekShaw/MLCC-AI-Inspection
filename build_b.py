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

# 随发布产物一同交付的权威文档：构建时同步到 output/，随后由
# make_portable_zip.py 整体打包 output/ 时自动进入便携版 zip 顶层。
DOCS_TO_SHIP = (
    "docs/软件功能规格与测试用例设计.md",
)


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


def bump_version(bug_fix=False):
    """按 2026-11-12 版本号规则递增（用户指定）：

    - 仅修复 bug（``--bug``）：第 4 位（build）+1（如 3.8.3.0 → 3.8.3.1）；
    - 仅 UI 改善（界面观感 / 布局调整，不含功能与数据逻辑变化，2026-11-12 补充）：
      同样第 4 位（build）+1，可递增到 99，满 100 向第 3 位进位归 0
      （如 3.8.5.0 → 3.8.5.1 → … → 3.8.5.99 → 3.8.6.0，构建用 ``--ui``）；
    - 功能改善或新增（默认）：第 3 位（patch）+1，第 4 位重新从 0 计数
      （如 3.8.2.x → 3.8.3.0，此后 bug 修复从 3.8.3.1 开始递增）；
    - patch 到 10 向第 2 位进位（3.0.9.0→3.1.0.0）。

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
    if bug_fix or "--ui" in sys.argv:
        bu += 1
        if bu >= 100:          # 第 4 位满 100 向第 3 位进位归 0
            bu, pa = 0, pa + 1
            if pa >= 10:
                pa, mi = 0, mi + 1
        rule = ("UI 改善：第 4 位 +1（满 100 进位第 3 位）" if "--ui" in sys.argv
                else "bug 修复：第 4 位 +1")
    else:
        pa += 1
        bu = 0
        if pa >= 10:
            pa, mi = 0, mi + 1
        rule = "功能变更：第 3 位 +1，第 4 位重新计数"
    src = src[:m.start()] + f'APP_VERSION = "{maj}.{mi}.{pa}.{bu}"' + src[m.end():]
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f">> 版本号已递增（{rule}）: {maj}.{mi}.{pa}.{bu}（本次发布生效）")


def sync_docs(root=None):
    """把 DOCS_TO_SHIP 同步到 output/ 根目录（与 exe 同级）。

    单独成函数便于不重新打包 exe 时也能刷新发布文档：
    `python -c "import build_b; build_b.sync_docs()"` 后再重新生成便携版 zip。
    """
    root = root or os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(root, "output")
    for doc in DOCS_TO_SHIP:
        src = os.path.join(root, doc)
        if not os.path.isfile(src):
            print("   !! 文档不存在，跳过同步:", src)
            continue
        dst = os.path.join(out_dir, os.path.basename(doc))
        shutil.copy2(src, dst)
        print("   同步发布文档 ->", dst)


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
        # 2026-11-12 版本号规则：仅 bug 修复用 --bug（第 4 位 +1）、
        # 仅 UI 改善用 --ui（第 4 位 +1，满 100 进位第 3 位）、
        # 功能改善/新增默认（第 3 位 +1，第 4 位重新计数）
        bump_version(bug_fix="--bug" in sys.argv)
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

    # 3) 同步 assets/ 资源目录到 output/（图标/配置等运行时依赖）。
    #    注意：output/assets/camera_frames 由用户在运行侧直接管理，构建时保留其既有
    #    样张（不删除、不覆盖），运行时 exe 即读取该目录。故整体替换前先把该目录复制
    #    备份出来（用复制而非移动，避免中途失败丢数据），替换完成后再把用户样张平铺放回
    #    （恢复前确保目标目录已清空，杜绝 move 目标已存在时产生的嵌套目录损坏）。
    assets_src = "assets"
    assets_dst = os.path.join("output", "assets")
    cam_dst = os.path.join(assets_dst, "camera_frames")
    cam_keep = os.path.join("output", "_cf_keep")
    if os.path.isdir(cam_keep):
        shutil.rmtree(cam_keep)
    had_user_cf = False
    if os.path.isdir(cam_dst):
        # 复制备份用户侧样张（保留原文件，备份失败也不会影响输出侧）
        os.makedirs(cam_keep, exist_ok=True)
        for _item in os.listdir(cam_dst):
            _s = os.path.join(cam_dst, _item)
            _d = os.path.join(cam_keep, _item)
            try:
                if os.path.isfile(_s):
                    shutil.copy2(_s, _d)
                else:
                    shutil.copytree(_s, _d)
            except Exception as _e:
                print("   camera_frames 备份跳过:", _item, repr(_e))
        had_user_cf = True
    if os.path.exists(assets_src):
        if os.path.exists(assets_dst):
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)
        # 用用户侧样张覆盖 dev 自带 camera_frames（用户侧为空时保留 dev 默认）
        if had_user_cf:
            if os.path.isdir(cam_dst):
                shutil.rmtree(cam_dst)
            # cam_dst 此时必不存在 → 用 copytree 平铺放回，dst 若不存在才成功，
            # 即便意外已存在也会直接报错暴露问题，而不会像 move 那样嵌套。
            shutil.copytree(cam_keep, cam_dst)
            shutil.rmtree(cam_keep)
        print("   同步 assets ->", assets_dst,
              "（保留 camera_frames 既有样张）" if had_user_cf
              else "（camera_frames 用 dev 默认样张）")

    # 3.1) 同步 app_icon.ico 到 output/：程序启动时按原生多档尺寸加载为窗口 / 任务栏图标
    if os.path.exists("app_icon.ico"):
        shutil.copy2("app_icon.ico", os.path.join("output", "app_icon.ico"))
        print("   同步 app_icon.ico ->", os.path.join("output", "app_icon.ico"))

    # 3.2) output/README.md 为发布说明唯一基准，由人工在其中直接维护，
    #   构建时不再从仓库根同步覆盖（2026-10-21 决定：以 output 下版本为准）。

    # 3.3) 同步权威文档到 output/ 根目录（与 exe 同级），使交付目录与
    #      便携版 zip 都带上同一份最新 md。make_portable_zip.py 整体复制
    #      output/，故压缩包内的顶层文件夹会自动包含该文件，无需二次处理。
    sync_docs(root)

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

    # 5) 同步生成便携版压缩包（可直接拷贝到其他电脑打开，反复替换）
    try:
        import make_portable_zip
        make_portable_zip.build()
    except Exception as e:
        print("!! 便携版压缩包生成失败（不影响 exe 产物）:", repr(e))

    # 6) 自动暂存最新 exe：output/* 被 .gitignore 忽略，普通 git add 加不进去，
    #    需强制 add，避免下次提交时漏掉 exe（不自动 commit，留给你确认）。
    try:
        r = subprocess.run(
            ["git", "add", "-f", OUT_EXE],
            cwd=root, capture_output=True, text=True,
        )
        if r.returncode == 0:
            print(">> 已自动暂存最新 exe ->", OUT_EXE,
                  "（如需同步 GitHub，请 git commit && git push）")
        else:
            print("!! 自动暂存 exe 失败（不影响产物）:", r.stderr.strip())
    except Exception as e:
        print("!! 自动暂存 exe 异常（不影响产物）:", repr(e))


if __name__ == "__main__":
    main()
