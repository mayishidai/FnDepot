"""子应用进程管理：启动 / 停止 / 重启 / 日志。

每个应用作为面板容器内的一个子进程运行，监听各自的内部端口；
对外只通过面板的反向代理 /p/<appid>/ 访问，因此无需暴露额外端口。
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import store

MAX_LOG_BYTES = 5 * 1024 * 1024      # 单个日志文件上限，超出后轮转一次
TAIL_DEFAULT = 300

_procs: dict[str, subprocess.Popen] = {}
_proc_lock = threading.RLock()
_started_at: dict[str, float] = {}
_exit_code: dict[str, int | None] = {}
_stopped_by_user: set[str] = set()      # 区分「主动停止」与「异常退出」


# ------------------------------------------------------------------ 日志

def _rotate_if_needed(path: Path) -> None:
    try:
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            os.replace(path, backup)
    except OSError:
        pass


def log_line(app_id: str, message: str) -> None:
    """向应用日志写入面板侧的操作记录行。"""
    store.ensure_dirs()
    path = store.log_file(app_id)
    with _proc_lock:
        _rotate_if_needed(path)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] [dev-hub] {message}\n")


def tail_log(app_id: str, lines: int = TAIL_DEFAULT) -> str:
    path = store.log_file(app_id)
    if not path.is_file():
        return ""
    lines = max(1, min(int(lines), 5000))
    with _proc_lock:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                buf = fh.readlines()
        except OSError as exc:
            return f"读取日志失败：{exc}"
    return "".join(buf[-lines:])


def clear_log(app_id: str) -> None:
    path = store.log_file(app_id)
    with _proc_lock:
        if path.is_file():
            path.write_text("", encoding="utf-8")


# ------------------------------------------------------------------ 运行态

def _popen(app_id: str) -> subprocess.Popen | None:
    with _proc_lock:
        return _procs.get(app_id)


def is_running(app_id: str) -> bool:
    proc = _popen(app_id)
    return proc is not None and proc.poll() is None


def status(app_id: str) -> dict:
    proc = _popen(app_id)
    if proc is None:
        return {"status": "stopped", "pid": None, "started_at": None, "exit_code": _exit_code.get(app_id)}
    code = proc.poll()
    if code is None:
        return {
            "status": "running", "pid": proc.pid,
            "started_at": _started_at.get(app_id), "exit_code": None,
        }
    # 主动停止的正常退出码在不同平台可能是 0 / -15 / 1，用停止意图判定
    intended = app_id in _stopped_by_user
    return {
        "status": "stopped" if intended else "exited",
        "pid": None,
        "started_at": _started_at.get(app_id),
        "exit_code": code,
    }


def _render_cmd(app: dict, cmd: str) -> str:
    """把命令里的 {port} / {dir} 占位符替换成实际值，避免依赖 shell 变量语法。"""
    return (cmd.replace("{port}", str(app["port"]))
               .replace("{dir}", str(store.work_dir(app))))


def _child_env(app: dict) -> dict:
    env = {**os.environ}
    env["PORT"] = str(app["port"])
    env["HOST"] = "0.0.0.0"
    env["DEVHUB_APP_ID"] = app["id"]
    env["DEVHUB_APP_DIR"] = str(store.app_dir(app["id"]))
    env.update({k: v for k, v in (app.get("env") or {}).items()})
    return env


def run_setup(app: dict) -> tuple[bool, str]:
    """执行应用的依赖安装/构建命令，输出写入日志。"""
    cmd = (app.get("setup") or "").strip()
    if not cmd:
        return True, "无需执行"
    cmd = _render_cmd(app, cmd)
    cwd = store.work_dir(app)
    if not cwd.is_dir():
        return False, f"工作目录不存在：{cwd}"
    log_line(app["id"], f"开始执行 setup：{cmd}")
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(cwd), env=_child_env(app),
            capture_output=True, text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        log_line(app["id"], "setup 超时（>30min）")
        return False, "setup 超时"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        for line in out.splitlines()[-200:]:
            log_line(app["id"], line)
    if proc.returncode != 0:
        log_line(app["id"], f"setup 失败（退出码 {proc.returncode}）")
        return False, f"setup 失败（退出码 {proc.returncode}）"
    log_line(app["id"], "setup 完成")
    return True, "setup 完成"


def start(app: dict, run_setup_first: bool = False) -> tuple[bool, str]:
    app_id = app["id"]

    if is_running(app_id):
        return True, "已在运行"

    if not store.app_dir(app_id).is_dir():
        log_line(app_id, "应用目录不存在，先执行克隆")
        from . import gitops
        ok, msg = gitops.clone(app)
        if not ok:
            log_line(app_id, f"克隆失败：{msg}")
            return False, f"克隆失败：{msg}"

    if run_setup_first:
        ok, msg = run_setup(app)
        if not ok:
            return False, msg

    cmd = (app.get("run") or "").strip()
    if not cmd:
        log_line(app_id, "未配置启动命令")
        return False, "未配置启动命令"
    cmd = _render_cmd(app, cmd)

    cwd = store.work_dir(app)
    if not cwd.is_dir():
        return False, f"工作目录不存在：{cwd}"

    store.ensure_dirs()
    path = store.log_file(app_id)
    with _proc_lock:
        _rotate_if_needed(path)
        fh = path.open("a", encoding="utf-8")
        fh.write(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] [dev-hub] "
            f"启动：{cmd}（端口 {app['port']}）\n"
        )
        fh.flush()
        try:
            proc = subprocess.Popen(
                cmd, shell=True, cwd=str(cwd), env=_child_env(app),
                stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,       # 独立进程组，便于整组终止
            )
        except OSError as exc:
            fh.close()
            log_line(app_id, f"启动失败：{exc}")
            return False, f"启动失败：{exc}"
        fh.close()
        _procs[app_id] = proc
        _started_at[app_id] = time.time()
        _exit_code[app_id] = None
        _stopped_by_user.discard(app_id)

    store.append_event(f"{app_id}: 已启动（pid {proc.pid}，端口 {app['port']}）")
    return True, f"已启动（pid {proc.pid}）"


def _terminate(proc: subprocess.Popen, force: bool) -> None:
    """终止子进程。Linux 下按进程组整组终止，其他平台退回单进程终止。"""
    sig = signal.SIGKILL if force else signal.SIGTERM
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill() if force else proc.terminate()
    except OSError:
        pass


def stop(app_id: str) -> tuple[bool, str]:
    with _proc_lock:
        proc = _procs.get(app_id)
    if proc is None or proc.poll() is not None:
        return True, "已停止"

    _terminate(proc, force=False)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _terminate(proc, force=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return False, "进程无法终止"

    with _proc_lock:
        _exit_code[app_id] = proc.returncode
        _stopped_by_user.add(app_id)
    log_line(app_id, f"已停止（退出码 {proc.returncode}）")
    store.append_event(f"{app_id}: 已停止")
    return True, "已停止"


def restart(app: dict, run_setup_first: bool = False) -> tuple[bool, str]:
    stop(app["id"])
    time.sleep(0.5)
    return start(app, run_setup_first=run_setup_first)


def stop_all() -> None:
    with _proc_lock:
        ids = list(_procs.keys())
    for app_id in ids:
        stop(app_id)
