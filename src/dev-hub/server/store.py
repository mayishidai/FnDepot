"""配置与运行状态的持久化。

数据目录结构（容器内 /data，由 $TRIM_PKGVAR 挂载）：
    /data/config.json        面板设置 + 应用清单（唯一事实来源）
    /data/state.json         运行态快照（重启后用于恢复卡片状态、依赖是否装过）
    /data/apps/<id>/         各应用 clone 的代码
    /data/logs/<id>.log      各应用运行日志
    /data/logs/events.log    面板自身的操作记录
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import catalog

DATA_DIR = Path(os.environ.get("DEVHUB_DATA", "/data"))
APPS_DIR = DATA_DIR / "apps"
LOGS_DIR = DATA_DIR / "logs"
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

DEFAULT_SETTINGS: dict[str, Any] = {
    "poll_minutes": 30,      # 0 = 关闭定时检测
    "github_token": "",      # 私有仓库 / 提高 API 限额时填写
    "port_start": 19100,     # 子应用内部端口起始值
    "proxy_timeout": 30,     # 反向代理超时（秒）
}

_lock = threading.RLock()


def ensure_dirs() -> None:
    for d in (DATA_DIR, APPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ 读写

def _read_json(path: Path, fallback: dict) -> dict:
    if not path.is_file():
        return json.loads(json.dumps(fallback))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 损坏时保留现场再返回默认值，避免面板整体不可用
        try:
            path.rename(path.with_suffix(path.suffix + f".broken.{int(time.time())}"))
        except OSError:
            pass
        return json.loads(json.dumps(fallback))
    return data if isinstance(data, dict) else json.loads(json.dumps(fallback))


def _write_json(path: Path, data: dict) -> None:
    """原子写入：先写临时文件再 rename，避免断电/重启写坏配置。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_config() -> dict:
    with _lock:
        cfg = _read_json(CONFIG_FILE, {"settings": DEFAULT_SETTINGS, "apps": []})
        settings = dict(DEFAULT_SETTINGS)
        settings.update(cfg.get("settings") or {})
        apps = cfg.get("apps")
        cfg["settings"] = settings
        cfg["apps"] = apps if isinstance(apps, list) else []
        removed = cfg.get("removed")
        cfg["removed"] = [str(x) for x in removed] if isinstance(removed, list) else []
        if _seed_builtins(cfg):
            save_config(cfg)
        return cfg


def _seed_builtins(cfg: dict) -> bool:
    """把 catalog 里尚未登记的预置应用补进配置；返回是否发生改动。

    只做「补缺」：已存在的 id 一律不动（用户改过的字段不能被覆盖），
    被用户在面板里删掉的 id 记在 cfg["removed"]，也不再补回。
    """
    apps: list[dict] = cfg["apps"]
    existing = {a.get("id") for a in apps}
    removed = set(cfg.get("removed") or [])
    changed = False
    for raw in catalog.BUILTIN_APPS:
        if raw["id"] in existing or raw["id"] in removed:
            continue
        apps.append(normalize_app(dict(raw), cfg["settings"], apps, reassign_port=True))
        existing.add(raw["id"])
        changed = True
    return changed


def is_builtin(app_id: str) -> bool:
    return any(item["id"] == app_id for item in catalog.BUILTIN_APPS)


def save_config(cfg: dict) -> None:
    with _lock:
        ensure_dirs()
        _write_json(CONFIG_FILE, cfg)


def load_state() -> dict:
    with _lock:
        st = _read_json(STATE_FILE, {"apps": {}})
        if not isinstance(st.get("apps"), dict):
            st["apps"] = {}
        return st


def save_state(st: dict) -> None:
    with _lock:
        ensure_dirs()
        _write_json(STATE_FILE, st)


# ------------------------------------------------------------------ 应用条目

def normalize_app(raw: dict, settings: dict, apps: list[dict],
                  reassign_port: bool = False) -> dict:
    """把前端提交的原始对象规范化成配置条目（补默认值、去多余键）。

    apps 必须显式传入当前应用清单：本函数可能在端口缺省时分配端口，
    而它同时被 load_config 的播种流程调用，不能反过来再去 load_config（会递归）。

    reassign_port 只给内置应用播种用：预置端口可能被用户自己的应用先占了，
    这时要自动改到空闲端口。用户在界面上手填的端口一律不改，
    撞了就让 validate_app 报「端口已被 xxx 占用」——静默改端口比报错更难排查。
    """
    app = {
        "id": str(raw.get("id", "")).strip(),
        "name": str(raw.get("name", "")).strip(),
        "repo": str(raw.get("repo", "")).strip(),
        "branch": str(raw.get("branch", "")).strip() or "main",
        "subdir": str(raw.get("subdir", "")).strip().strip("/"),
        "port": int(raw.get("port") or 0),
        "run": str(raw.get("run", "")).strip(),
        "setup": str(raw.get("setup", "")).strip(),
        "icon": str(raw.get("icon", "")).strip(),
        "desc": str(raw.get("desc", "")).strip(),
        "auto_start": bool(raw.get("auto_start", True)),
        "enabled": bool(raw.get("enabled", True)),
        "env": {str(k): str(v) for k, v in (raw.get("env") or {}).items()},
    }
    used = {a["port"] for a in apps if a.get("id") != app["id"]}
    if not app["port"] or (reassign_port and app["port"] in used):
        app["port"] = next_free_port(settings, exclude=app["id"], apps=apps)
    return app


def validate_app(app: dict, cfg: dict, allow_id: str | None = None) -> str | None:
    """返回错误信息；None 表示通过。"""
    if not ID_RE.match(app["id"]):
        return "应用 ID 只能包含字母、数字、点、下划线、短横线，且以字母或数字开头（最长 64）"
    if not app["name"]:
        return "应用名称不能为空"
    if not app["repo"]:
        return "GitHub 仓库地址不能为空"
    if not (app["repo"].startswith(("http://", "https://", "git@"))):
        return "仓库地址需为 http(s) 或 git@ 形式"
    if app["port"] and not (1024 <= app["port"] <= 65535):
        return "端口需在 1024-65535 之间"
    for other in cfg.get("apps", []):
        if other["id"] == app["id"] and other["id"] != allow_id:
            return f"应用 ID {app['id']} 已存在"
        if other["port"] == app["port"] and other["id"] != app["id"]:
            return f"端口 {app['port']} 已被应用 {other['id']} 占用"
    return None


def next_free_port(settings: dict, exclude: str | None = None,
                   apps: list[dict] | None = None) -> int:
    if apps is None:
        apps = load_config().get("apps", [])
    used = {a["port"] for a in apps if a.get("id") != exclude}
    port = int(settings.get("port_start", 19100))
    while port in used:
        port += 1
    return port


def find_app(cfg: dict, app_id: str) -> dict | None:
    for a in cfg.get("apps", []):
        if a["id"] == app_id:
            return a
    return None


def app_dir(app_id: str) -> Path:
    return APPS_DIR / app_id


def work_dir(app: dict) -> Path:
    base = app_dir(app["id"])
    return base / app["subdir"] if app["subdir"] else base


def log_file(app_id: str) -> Path:
    return LOGS_DIR / f"{app_id}.log"


def events_file() -> Path:
    return LOGS_DIR / "events.log"


def append_event(message: str) -> None:
    """记录面板自身操作（clone/pull/启停等），便于事后排查。"""
    ensure_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with events_file().open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")


def purge_dir(path: Path) -> tuple[bool, str]:
    """删除应用代码目录。

    不用 shutil.rmtree：git 仓库里常有只读文件（.git/objects）会导致删除失败，
    这里逐个文件先改权限再删，并收集失败项，保证「尽力而为、不阻断主流程」。
    """
    if not path.exists():
        return True, ""
    errors: list[str] = []

    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            target = Path(root) / name
            try:
                if not target.is_symlink():
                    target.chmod(0o700)
                target.unlink()
            except OSError as exc:
                errors.append(f"{target.name}: {exc}")
        for name in dirs:
            target = Path(root) / name
            try:
                if target.is_symlink():
                    target.unlink()
                else:
                    target.rmdir()
            except OSError as exc:
                errors.append(f"{target.name}: {exc}")

    try:
        path.rmdir()
    except OSError as exc:
        errors.append(str(exc))

    if errors:
        return False, "; ".join(errors[:3])
    return True, ""

