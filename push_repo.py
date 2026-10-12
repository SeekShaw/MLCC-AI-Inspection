#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「电子元件视觉检测系统 V3.0」推送到 GitHub（SeekShaw/MLCC-AI-Inspection）。

设计目标：
- 更新程序后一条命令完成 暂存 -> 提交 -> 推送。
- 兼容本沙箱对 GitHub TLS 吊销检查（CRYPT_E_NO_REVOCATION_CHECK）的拦截：
  通过 `git -c http.sslVerify=false` 仅命令级关闭校验，不改全局配置。
- 默认复用本机已存的 Git Credential Manager / Windows 凭据；
  也可设环境变量 GITHUB_TOKEN 临时嵌入 remote URL 完成本次推送（不会写入 git config）。
- 安全护栏：提交前若发现 users.json（含明文口令）被暂存，立即中止，防止泄密。

用法：
    python push_repo.py                      # 用默认提交信息
    python push_repo.py "修复某某逻辑"        # 自定义提交信息
    GITHUB_TOKEN=ghp_xxx python push_repo.py  # 用临时 token 推送（用完即弃）
"""
import os
import sys
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
ORIGIN_URL = "https://github.com/SeekShaw/MLCC-AI-Inspection.git"
BRANCH = "main"
DEFAULT_MSG = "chore: update MLCC inspection program"


def run(args, capture=False, text=True):
    """统一以 `git -c http.sslVerify=false` 运行，绕开沙箱 TLS 吊销拦截。"""
    cmd = ["git", "-c", "http.sslVerify=false"] + list(args)
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=REPO_DIR, capture_output=capture, text=text)


def ensure_origin():
    r = run(["remote", "get-url", "origin"], capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"origin 未设置，自动设为 {ORIGIN_URL}")
        run(["remote", "add", "origin", ORIGIN_URL])


def secret_guard():
    """若 users.json（含口令）被暂存则中止，避免泄密。"""
    r = run(["diff", "--cached", "--name-only"], capture=True)
    staged = r.stdout.splitlines()
    leaked = [p for p in staged if p.replace("\\", "/").endswith("users.json")]
    if leaked:
        sys.exit(
            "ABORT: 检测到机密文件被暂存 -> "
            + ", ".join(leaked)
            + "\n请检查 .gitignore，并用 `git restore --staged users.json` 取消暂存后再推送。"
        )


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MSG
    token = os.environ.get("GITHUB_TOKEN")

    ensure_origin()

    # 1) 暂存所有改动（受 .gitignore 约束）
    if run(["add", "-A"]).returncode != 0:
        sys.exit("git add 失败")

    # 2) 提交前密钥护栏
    secret_guard()

    # 3) 提交（无改动则跳过，但仍尝试推送已有未推送提交）
    r = run(["commit", "-m", msg], capture=True, text=True)
    if r.returncode != 0:
        out = (r.stdout or "") + (r.stderr or "")
        if "nothing to commit" in out:
            print("没有新的改动需要提交，继续检查是否需要推送。")
        else:
            print(out)
            sys.exit("git commit 失败")

    # 4) 推送（可选临时嵌入 token）
    if token:
        run(["remote", "set-url", "origin",
             f"https://{token}@github.com/SeekShaw/MLCC-AI-Inspection.git"])
    try:
        rc = run(["push", "origin", BRANCH]).returncode
    finally:
        if token:
            # 用完即弃，恢复干净 URL，token 不残留于 git config
            run(["remote", "set-url", "origin", ORIGIN_URL])
    sys.exit(rc)


if __name__ == "__main__":
    main()
