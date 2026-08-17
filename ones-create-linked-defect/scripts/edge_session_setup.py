# -*- coding: utf-8 -*-
"""复制本机 Edge 登录态到独立会话目录（v20 Cookie 只能由 Edge 本体解密）。

用法:
    python edge_session_setup.py           # 幂等：会话目录已就绪则跳过
    python edge_session_setup.py --force   # 强制重新复制

复制内容（与 ONES / 飞书登录相关的文件）:
    Local State
    Default/Preferences
    Default/Secure Preferences
    Default/Network/Cookies (+ journal)
    Default/Network/Network Persistent State

注意:
    - 会话目录含敏感登录凭据，请勿提交到 git 或分享。
    - Windows 上若 Edge 正在运行，部分文件可能被锁定导致复制失败；
      建议先完全退出 Edge 再执行。
"""
import argparse
import shutil
import sys
from pathlib import Path

from ones_config import resolve_settings

COOKIE_FILES = [
    "Local State",
    Path("Default") / "Preferences",
    Path("Default") / "Secure Preferences",
    Path("Default") / "Network" / "Cookies",
    Path("Default") / "Network" / "Cookies-journal",
    Path("Default") / "Network" / "Network Persistent State",
    # macOS 变体：Edge 在 macOS 把 Cookies 放在 Default 根目录
    Path("Default") / "Cookies",
    Path("Default") / "Cookies-journal",
]


def _cookies_candidates(base):
    return [
        Path(base) / "Default" / "Network" / "Cookies",
        Path(base) / "Default" / "Cookies",
    ]


def session_ready(session_dir):
    """会话目录是否已包含可用的 Cookies。"""
    return any(p.exists() for p in _cookies_candidates(session_dir))


def ensure_session(force=False):
    """确保登录态会话目录就绪；返回 (session_dir, 复制的文件列表)。"""
    settings = resolve_settings()
    src = Path(settings["edge"]["user_data_source"])
    dst = Path(settings["edge"]["session_dir"])

    if not src.exists():
        raise SystemExit(
            f"未找到本机 Edge 用户数据目录：{src}\n"
            "请在 config/settings.yaml 设置 edge.user_data_source 或用环境变量 ONES_EDGE_USER_DATA 指定。"
        )

    if session_ready(dst) and not force:
        print(f"[edge_session_setup] 会话目录已就绪，跳过复制：{dst}")
        return dst, []

    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    missing = []
    for rel in COOKIE_FILES:
        source = src / rel
        if not source.exists():
            missing.append(str(rel))
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
            copied.append(str(rel))
        except OSError as exc:
            print(f"[edge_session_setup] 复制失败 {rel}: {exc}", file=sys.stderr)

    print(f"[edge_session_setup] 已复制 {len(copied)} 个文件到 {dst}")
    if copied:
        print("  " + "\n  ".join(copied))
    if missing:
        print(f"[edge_session_setup] 以下文件不存在（可忽略，不影响登录）:\n  " + "\n  ".join(missing), file=sys.stderr)
    if not session_ready(dst):
        raise SystemExit(
            "复制后仍未找到 Cookies 文件。\n"
            "可能原因：本机 Edge 从未登录过（先手动登录一次 ONES/飞书），"
            "或 Edge 正在运行导致文件被锁定（先完全退出 Edge 再重试）。"
        )
    return dst, copied


def main():
    parser = argparse.ArgumentParser(description="复制本机 Edge 登录态到 ONES 会话目录")
    parser.add_argument("--force", action="store_true", help="强制重新复制")
    args = parser.parse_args()
    ensure_session(force=args.force)


if __name__ == "__main__":
    main()
