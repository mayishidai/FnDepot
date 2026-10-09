"""Git 操作：克隆 / 拉取 / 状态比对。

只用命令行 git（镜像内已安装），不引入 GitPython 等重依赖。
所有对外函数都是同步阻塞实现，调用方用 asyncio.to_thread 包成异步。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import store

TIMEOUT = 300
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}


def _run(args: list[str], cwd: Path | None = None, token: str = "") -> tuple[int, str]:
    args = _inject_token(args, token)
    try:
        proc = subprocess.run(
            args, cwd=str(cwd) if cwd else None, env=_ENV,
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（>{TIMEOUT}s）：{' '.join(_mask(args))}"
    except FileNotFoundError as exc:
        return 127, f"命令不可用：{exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _inject_token(args: list[str], token: str) -> list[str]:
    """把 token 拼进 https 地址，用于私有仓库；不写盘、不落日志。"""
    if not token:
        return args
    out = []
    for a in args:
        if a.startswith("https://") and "@" not in a.split("//", 1)[1].split("/")[0]:
            a = a.replace("https://", f"https://x-access-token:{token}@", 1)
        out.append(a)
    return out


def _mask(args: list[str]) -> list[str]:
    return [re.sub(r"://[^@/]+@", "://***@", a) for a in args]


def _redact(text: str) -> str:
    return re.sub(r"://[^@/\s]+@", "://***@", text)


def is_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


def clone(app: dict, token: str = "") -> tuple[bool, str]:
    dest = store.app_dir(app["id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if is_repo(dest):
        return True, "已存在，跳过克隆"
    code, out = _run(
        ["git", "clone", "--branch", app["branch"], app["repo"], str(dest)],
        token=token,
    )
    if code != 0:
        # 分支不存在时退回默认分支再试一次
        code, out = _run(["git", "clone", app["repo"], str(dest)], token=token)
    if code != 0:
        return False, _redact(out)
    store.append_event(f"{app['id']}: 克隆完成 -> {app['repo']}")
    return True, "克隆完成"


def fetch(app: dict, token: str = "") -> tuple[bool, str]:
    path = store.app_dir(app["id"])
    if not is_repo(path):
        return False, "尚未克隆"
    code, out = _run(["git", "fetch", "--prune", "origin"], cwd=path, token=token)
    return code == 0, _redact(out)


def pull(app: dict, token: str = "") -> tuple[bool, str]:
    path = store.app_dir(app["id"])
    if not is_repo(path):
        ok, msg = clone(app, token)
        if not ok:
            return False, msg
    code, out = _run(
        ["git", "-c", "rebase.autoStash=true", "pull", "--ff-only", "origin", app["branch"]],
        cwd=path, token=token,
    )
    if code != 0:
        return False, _redact(out)
    store.append_event(f"{app['id']}: 已拉取最新代码")
    return True, "已更新到最新"


def current_branch(path: Path) -> str:
    code, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return out if code == 0 else ""


def status(app: dict) -> dict:
    """返回 {cloned, branch, head, dirty, ahead, behind, subject, error}。

    ahead/behind 以「本地分支 vs 远端同名分支」计算，未 fetch 过则为 None。
    """
    path = store.app_dir(app["id"])
    result: dict = {
        "cloned": is_repo(path), "branch": "", "head": "",
        "dirty": False, "ahead": None, "behind": None, "subject": "", "error": "",
    }
    if not result["cloned"]:
        return result

    code, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    result["branch"] = out if code == 0 else ""

    code, out = _run(["git", "rev-parse", "--short", "HEAD"], cwd=path)
    result["head"] = out if code == 0 else ""

    code, out = _run(["git", "log", "-1", "--pretty=%s"], cwd=path)
    result["subject"] = out[:120] if code == 0 else ""

    code, out = _run(["git", "status", "--porcelain"], cwd=path)
    result["dirty"] = code == 0 and bool(out)

    upstream = f"origin/{app['branch']}"
    code, out = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], cwd=path)
    if code == 0 and out:
        parts = out.split()
        if len(parts) == 2:
            result["ahead"], result["behind"] = int(parts[0]), int(parts[1])
    else:
        result["error"] = "无法与远端比对（可能尚未 fetch）"
    return result


def remote_head(app: dict, token: str = "") -> str:
    """不落地地查询远端分支最新提交短哈希（用于轻量检查）。"""
    code, out = _run(["git", "ls-remote", app["repo"], app["branch"]], token=token)
    if code != 0 or not out:
        return ""
    return out.split()[0][:7]


def init_safe_directory() -> None:
    """容器内以 root 运行、仓库属主可能不同，忽略所有权检查。"""
    _run(["git", "config", "--system", "--add", "safe.directory", "*"])
