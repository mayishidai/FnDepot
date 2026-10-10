"""子应用进程管理：启动 / 停止 / 重启 / 日志。

每个应用作为面板容器内的一个子进程运行，监听各自的内部端口；
对外只通过面板的反向代理 /p/<appid>/ 访问，因此无需暴露额外端口。

跨平台：面板的正式运行环境是容器（Linux，见 src/dev-hub/Dockerfile），但为了能在
Windows 开发机上直接调试子应用，这里把「路径与 shell 的差异」全部收敛进占位符，
应用清单（catalog.py）只写平台无关命令：

    {venv}      主虚拟环境里可执行文件所在目录，**自带结尾分隔符** ——
                容器是 `.venv/bin/`，Windows 是 `.venv\\Scripts\\`。
                所以模板必须写成 `{venv}python`，不能写 `{venv}/python`：
                cmd.exe 把 `/` 当开关分隔符，`.venv\\Scripts/python` 会直接报
                「不是内部或外部命令」（实测 rc=1）。
    {venv:.uv}  同上，但指向另一套虚拟环境；冒号后面写的是**完整目录名**
                （Octop 用 .uv，所以是 {venv:.uv}，别漏了开头的点）
    {python}    新建虚拟环境用的解释器 → python3（容器）或面板自己的解释器
    {null}      空设备 → /dev/null（容器）或 NUL（Windows）
    {port}      应用端口
    {dir}       应用工作目录（= clone 下来的仓库根）
    {data}      面板数据目录（容器里是挂载卷 /data）。**用户数据要放这里，
                不要放 {dir} 里面** —— clone 会被「更新代码」改写，删应用时
                更是整个目录被抹掉。

占位符是裸的 `{xxx}` 写法，因此 shell 自己的 `${VAR}` 不受影响；但别把应用侧的
shell 变量取名成 port/dir/python/null/venv/data，那会被误替换。

多行命令的退出码只反映最后一行（POSIX sh 与 cmd.exe 都是如此），
所以多行 setup 会被 _prepare_setup 改造成「任一行失败即整体失败」。
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import store

MAX_LOG_BYTES = 5 * 1024 * 1024      # 单个日志文件上限，超出后轮转一次
TAIL_DEFAULT = 300

IS_WINDOWS = os.name == "nt"

# 应用清单里可用的占位符（见模块 docstring）
_PLACEHOLDER_RE = re.compile(r"\{(port|dir|python|null|data|venv(?::[\w.-]+)?)\}")

# Windows 上确实跑不起来的 POSIX 专有语法。只在「多行 setup」上判定。
_POSIX_ONLY_RE = re.compile(
    r"^\s*(if|then|elif|else|fi|for|while|do|done|case|esac)\b"
    r"|\btest\s+-"
    r"|/dev/urandom"
    r"|\$\("
    r"|\bod\s+-",
    re.M,
)

_procs: dict[str, subprocess.Popen] = {}
_proc_lock = threading.RLock()
_started_at: dict[str, float] = {}
_exit_code: dict[str, int | None] = {}
_stopped_by_user: set[str] = set()      # 区分「主动停止」与「异常退出」

# 依赖安装状态：idle（从没装过）/ running / ok / failed
# 结果落到 state.json，面板重启后不会重复安装。
_setup_state: dict[str, str] = {}


# ------------------------------------------------------------------ 输出解码

def _decode(raw: bytes | None) -> str:
    """解码子进程输出。

    容器里统一 UTF-8。Windows 上则混着两种来源：cmd.exe 自己的报错是 GBK
    （代码页 936），Python 子进程重定向后的中文输出也按本地代码页编码。
    所以先按 UTF-8 试，失败再退 GBK —— 比固定 errors="replace" 好，中文能正常显示。

    这里刻意不用 subprocess 的 text=True：它按 UTF-8 硬解，解码异常发生在读取线程
    内部、不会传播到调用方，只会把 stdout/stderr 双双变成 None。结果是报错信息
    全部丢失，日志里只剩一句「setup 失败（退出码 1）」，完全没法排查。
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


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


# ------------------------------------------------------------------ 依赖安装态

def setup_state(app_id: str) -> str:
    """返回该应用的依赖安装状态。首次访问时从 state.json 恢复。"""
    with _proc_lock:
        cached = _setup_state.get(app_id)
    if cached is not None:
        return cached
    entry = (store.load_state().get("apps") or {}).get(app_id) or {}
    saved = entry.get("setup_state")
    if saved == "ok":
        state = "ok"
    elif saved == "failed":
        state = "failed"      # 保留上次的失败结论，界面才会提示「依赖安装失败」
    else:
        # 面板在安装中途重启会留下悬挂的 running，按「待重装」处理
        state = "ok" if entry.get("setup_ok") else "idle"
    with _proc_lock:
        return _setup_state.setdefault(app_id, state)


def _set_setup_state(app_id: str, state: str) -> None:
    with _proc_lock:
        _setup_state[app_id] = state
    st = store.load_state()
    entry = st.setdefault("apps", {}).setdefault(app_id, {})
    entry["setup_ok"] = state == "ok"
    entry["setup_state"] = state
    entry["setup_at"] = time.time()
    store.save_state(st)


def needs_setup(app: dict) -> bool:
    """配置了安装命令、且还没有成功执行过。"""
    if not (app.get("setup") or "").strip():
        return False
    return setup_state(app["id"]) != "ok"


def setup_running(app_id: str) -> bool:
    return setup_state(app_id) == "running"


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


def _venv_bin(name: str) -> str:
    """虚拟环境里可执行文件所在目录，含结尾分隔符（见模块 docstring）。"""
    return f"{name}\\Scripts\\" if IS_WINDOWS else f"{name}/bin/"


def _venv_python() -> str:
    """新建虚拟环境用的解释器。

    容器里固定 python3；Windows 上不保证有 python3.exe，直接用面板自身的解释器
    最稳，也免得依赖 PATH 里有没有 python。路径含空格时加引号。
    """
    if not IS_WINDOWS:
        return "python3"
    exe = sys.executable or "python"
    return f'"{exe}"' if " " in exe else exe


def _render(app: dict, text: str) -> str:
    """展开命令 / 环境变量里的占位符（清单见模块 docstring）。"""
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "port":
            return str(app["port"])
        if key == "dir":
            return str(store.work_dir(app))
        if key == "python":
            return _venv_python()
        if key == "null":
            return "NUL" if IS_WINDOWS else "/dev/null"
        if key == "data":
            # 面板数据目录（容器里是挂载卷 /data）。给「数据要放持久目录、不能放在
            # clone 里」的应用用 —— clone 是会被「更新代码」改写、甚至被删应用时
            # 整个抹掉的，用户数据放里面迟早出事。
            return str(store.DATA_DIR)
        # venv 或 venv:<名称>
        return _venv_bin(key.split(":", 1)[1] if ":" in key else ".venv")

    return _PLACEHOLDER_RE.sub(repl, text)


def _child_env(app: dict) -> dict:
    env = {**os.environ}
    env["PORT"] = str(app["port"])
    env["HOST"] = "0.0.0.0"
    env["DEVHUB_APP_ID"] = app["id"]
    env["DEVHUB_APP_DIR"] = str(store.app_dir(app["id"]))
    # 自定义环境变量同样展开占位符：把 `API_PORT={port}` 写进 env，比在命令前拼
    # `API_PORT=19104 node ...` 可靠得多 —— 那是 POSIX 专有语法，cmd.exe 不认
    # （实测报「'API_PORT' 不是内部或外部命令」）。
    env.update({k: _render(app, str(v)) for k, v in (app.get("env") or {}).items()})
    return env


def _prepare_setup(cmd: str) -> tuple[str, str | None]:
    """把多行 setup 改造成「任一行失败就整体失败」，返回 (改写后的命令, 错误说明)。

    多行命令的退出码只反映最后一行（POSIX sh 如此，cmd.exe 也一样），中间某行失败
    会被静默吞掉：面板于是把 setup_ok 记成 true，needs_setup 之后恒为 False，
    用户再也等不到重装，界面上还显示「依赖已安装」。这是实测踩到的真缺陷。
    两种平台的加固方式不同：
    - POSIX：前置 `set -e`（Octop 的脚本自己已经写了，这里做兜底）；
    - Windows：cmd.exe 没有等价开关，改用 `&&` 串联（跳过空行与注释）。
      带 if/fi、test、/dev/urandom 这类语法的脚本本机确实跑不了，提前给出明确结论，
      免得用户在 `npm ci` 跑到一半才看到一堆语法报错。
    """
    if "\n" not in cmd:
        return cmd, None
    if not IS_WINDOWS:
        if re.match(r"\s*set\s+-e\b", cmd):
            return cmd, None
        return "set -e\n" + cmd, None
    if _POSIX_ONLY_RE.search(cmd):
        return cmd, ("该应用的安装脚本用了 POSIX shell 语法（if/fi、test、/dev/urandom 等），"
                     "只能在 Linux 容器里执行；本机 Windows 不支持。")
    lines = [
        line.strip() for line in cmd.splitlines()
        if line.strip() and not line.strip().startswith(("#", "::", "REM ", "rem "))
    ]
    return " && ".join(lines), None


def run_setup(app: dict) -> tuple[bool, str]:
    """执行应用的依赖安装/构建命令，输出写入日志，并记录安装状态。"""
    app_id = app["id"]
    cmd = (app.get("setup") or "").strip()
    if not cmd:
        return True, "无需执行"
    cmd = _render(app, cmd)
    cmd, prep_err = _prepare_setup(cmd)
    if prep_err:
        _set_setup_state(app_id, "failed")
        log_line(app_id, f"setup 无法执行：{prep_err}")
        return False, prep_err
    cwd = store.work_dir(app)
    if not cwd.is_dir():
        # 强调失败：否则界面上会一直停在「未安装依赖」，看不出是被什么卡住的
        _set_setup_state(app_id, "failed")
        msg = f"工作目录不存在：{cwd}（先克隆代码）"
        log_line(app_id, f"setup 无法执行：{msg}")
        return False, msg
    _set_setup_state(app_id, "running")
    log_line(app_id, f"开始执行 setup：{cmd}")
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(cwd), env=_child_env(app),
            capture_output=True, timeout=3600,
        )
    except subprocess.TimeoutExpired:
        _set_setup_state(app_id, "failed")
        log_line(app_id, "setup 超时（>60min）")
        return False, "setup 超时"
    out = (_decode(proc.stdout) + _decode(proc.stderr)).strip()
    if out:
        for line in out.splitlines()[-200:]:
            log_line(app_id, line)
    if proc.returncode != 0:
        _set_setup_state(app_id, "failed")
        log_line(app_id, f"setup 失败（退出码 {proc.returncode}）")
        return False, f"setup 失败（退出码 {proc.returncode}）"
    _set_setup_state(app_id, "ok")
    log_line(app_id, "setup 完成")
    store.append_event(f"{app_id}: 依赖安装完成")
    return True, "setup 完成"


def ensure_cloned(app: dict) -> tuple[bool, str]:
    """确保代码已在本地；没克隆过就先克隆。启动与安装依赖前都要先过这一步。"""
    app_id = app["id"]
    if store.app_dir(app_id).is_dir():
        return True, ""
    log_line(app_id, "应用目录不存在，先执行克隆")
    from . import gitops
    ok, msg = gitops.clone(app)
    if not ok:
        log_line(app_id, f"克隆失败：{msg}")
        return False, f"克隆失败：{msg}"
    return True, ""


def start(app: dict, run_setup_first: bool = False) -> tuple[bool, str]:
    app_id = app["id"]

    if is_running(app_id):
        return True, "已在运行"

    ok, msg = ensure_cloned(app)
    if not ok:
        return False, msg

    if run_setup_first:
        ok, msg = run_setup(app)
        if not ok:
            return False, msg

    cmd = (app.get("run") or "").strip()
    if not cmd:
        log_line(app_id, "未配置启动命令")
        return False, "未配置启动命令"
    cmd = _render(app, cmd)

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
    """终止子进程。

    Linux 下按进程组整组终止；Windows 下 shell=True 起的只是 cmd.exe，真正干活的
    python/node 是它的子进程，proc.terminate() 收不掉，会留下孤儿进程继续占着端口
    （本机反复点启动就攒了一堆），所以改用 taskkill /T 连整棵树一起收。
    """
    if IS_WINDOWS:
        try:
            done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                  capture_output=True, timeout=15)
            if done.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass

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
