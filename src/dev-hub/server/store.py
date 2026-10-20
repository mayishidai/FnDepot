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

# 容器对宿主机发布的「直连端口段」，必须与 packages/dev-hub/app/docker/docker-compose.yaml
# 里的 ports 映射逐字对应。expose_port=True 的应用在容器内监听这段端口，
# 只有落在这个区间里，浏览器才能从宿主机直接访问到。
#
# 面板只能读到自己的「容器内」端口（8890），读不到应用中心分配的宿主机端口，
# 所以这里没法自动推导，只能靠这份常量 + compose 双向对齐；不一致时
# _app_view 会把 expose_port_published 置 False，界面上给出醒目提示。
EXPOSE_PORT_START = 19100
EXPOSE_PORT_END = 19119


def in_expose_range(port: int) -> bool:
    return EXPOSE_PORT_START <= int(port or 0) <= EXPOSE_PORT_END


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
        # 顺序是有讲究的：先补全老条目的新字段，再播种缺失的内置应用（播种依赖归一化
        # 后的清单），然后把内置命令升到 catalog 声明的 cmd_rev（我们修正过自己的内置
        # 命令时，只有这一步能把新命令推到**已经存在**的老配置上），最后把已下架的内置
        # 应用从配置里摘掉（见 _drop_archived_builtins）。
        # 注意四步都要跑，别用 `a() or b()` 短路——前一步为真时后面就再也不会执行了。
        migrated = _normalize_existing(cfg)
        seeded = _seed_builtins(cfg)
        upgraded = _upgrade_builtin_cmds(cfg)
        dropped = _drop_archived_builtins(cfg)
        if migrated or seeded or upgraded or dropped:
            save_config(cfg)
        return cfg


def _backfill_placeholder(raw: dict, entry: dict) -> dict:
    """把「还没配置过」的内置占位条目按清单补齐。

    判据是 `run` 与 `setup` **同时为空**：只有「代码还没推上来、先占个位」的
    卡片才会这样（catalog 里就是拿空命令当占位）。用户只要能写出任意一条命令，
    这条路径就再也不会碰它 —— 所以不存在覆盖用户配置的风险。

    典型场景：AIImageStudio 空仓库期间占位、代码推上来后要让老配置也能开箱即用。
    端口不在这里补（占位期间可能已被重排过），交给 normalizer 保留原值。
    """
    if raw.get("run") or raw.get("setup"):
        return raw
    fixed = dict(raw)
    for key in ("name", "repo", "branch", "desc", "setup", "run",
                "enabled", "auto_start", "expose_port", "prefix_api", "env"):
        if key in entry and fixed.get(key) != entry[key]:
            fixed[key] = entry[key]
    return fixed


def _normalize_existing(cfg: dict) -> bool:
    """把 config.json 里的既有条目过一遍 normalize_app，返回是否发生改动。

    升级迁移用：老版本写下的条目不含 expose_port 等后加的键，直接按新 schema
    读取会 KeyError。这里只补字段、不动端口（reassign_port=False），
    保证「用户改过的配置不被覆盖」这条约定依然成立。

    唯一的例外是**空占位条目**（run 与 setup 都为空），它会被清单补齐 ——
    见 _backfill_placeholder 的说明。
    """
    apps: list[dict] = cfg["apps"]
    builtin = {a["id"]: a for a in catalog.BUILTIN_APPS}
    changed = False
    for idx, raw in enumerate(list(apps)):
        base = dict(raw)
        entry = builtin.get(raw.get("id"))
        if entry is not None:
            base = _backfill_placeholder(base, entry)
        fixed = normalize_app(base, cfg["settings"], apps)
        if fixed != raw:
            apps[idx] = fixed
            changed = True
    return changed


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


def _upgrade_builtin_cmds(cfg: dict) -> bool:
    """把内置应用的 run/setup 升级到 catalog 当前声明的 cmd_rev；返回是否发生改动。

    补的是「播种只补缺、不覆盖」这条契约的盲区：我们**修正自己写的内置命令**时
    （例如修掉 setup 与 run 指向了不同虚拟环境目录这种真故障），老配置里那条旧命令永远优先，修复根本到不了
    已经部署过的环境 —— _backfill_placeholder 只在 run/setup 同时为空时才覆盖，
    非空的老条目永远走不到那条路径。

    两道闸门：
    * cmd_rev：配置里的值（缺省 0）必须小于 catalog 的，才会有升级动作；
    * cmd_prev_run：配置里的 run 还必须**恰好等于** catalog 记下的上一版命令原文，
      才认定「这条是我们播种下去的」并覆盖。用户自己改过的 run 对不上指纹 → 跳过，
      只把 cmd_rev 标记成“已评估”。

    两者结合后，**只有我们自己播种的旧命令**会被升级，用户的自定义依旧不被覆盖。
    每次动作都会往事件日志记一条，用户在「事件」里能看到是哪条被换成了哪一版。
    """
    builtin = {a["id"]: a for a in catalog.BUILTIN_APPS}
    changed = False
    for item in cfg["apps"]:
        entry = builtin.get(item.get("id"))
        if entry is None:
            continue
        want = int(entry.get("cmd_rev") or 0)
        have = int(item.get("cmd_rev") or 0)
        if want <= have:
            continue
        # 指纹闸门：只有配置里的 run **恰是上一版播种下去的那条**才覆盖，
        # 于是用户自己改过的启动命令永远不会被这个闸门刷掉。
        # （catalog 没声明 cmd_prev_run 时才退化成无条件覆盖。）
        prev = entry.get("cmd_prev_run")
        if prev is not None and (item.get("run") or "").strip() != str(prev).strip():
            item["cmd_rev"] = want      # 标记已评估，免得每次加载都重判
            changed = True
            append_event(
                f"{item['id']}: 启动命令是自定义的，跳过内置命令升级（cmd_rev→{want}）")
            continue
        item["cmd_rev"] = want
        for key in ("run", "setup"):
            new = entry.get(key)
            if new is not None and item.get(key) != new:
                item[key] = new
        changed = True
        append_event(f"{item['id']}: 内置命令已升级到 cmd_rev={want}")
    return changed


def _drop_archived_builtins(cfg: dict) -> bool:
    """把 catalog.ARCHIVED_BUILTINS 里登记的下架应用从配置移除；返回是否发生改动。

    补的是「只补缺、不覆盖」这条契约的**另一头**：从 BUILTIN_APPS 删掉一个条目只能
    让新装的面板不再播种它，已经部署的 config.json 里那条还挂着，照样能启动。
    要真正下架，必须在这里把它摘掉。

    同样守着「不覆盖用户配置」：只有配置里的 run **恰好等于** catalog 记下的某一版
    播种命令（last_runs 指纹）时才删；用户改过命令的条目原样保留 —— 那说明他自己
    接过手了，替他删掉等于丢数据。空命令的占位条目算我们的，一并摘掉。

    每次动作都会在事件日志留一条，用户在「事件」里能看到是哪条被下架了。
    """
    archived = {a["id"]: a for a in getattr(catalog, "ARCHIVED_BUILTINS", [])}
    if not archived:
        return False
    kept: list = []
    removed: list = []
    for item in cfg["apps"]:
        entry = archived.get(item.get("id"))
        if entry is None:
            kept.append(item)
            continue
        known = [str(r).strip() for r in (entry.get("last_runs") or [])]
        have = (item.get("run") or "").strip()
        if have and have not in known:
            # 命令对不上任何一版指纹 → 用户自己改过，保留
            kept.append(item)
            append_event(f"{item['id']}: 该内置应用已下架，但启动命令是自定义的，保留条目")
            continue
        removed.append(item["id"])
    if not removed:
        return False
    cfg["apps"] = kept
    for appid in removed:
        append_event(f"{appid}: 内置应用已下架，条目已从配置移除")
    return True


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
        # 独立端口直连：应用自己占一个对外端口，卡片「打开」直接跳过去，
        # 不走 /p/<id>/ 路径前缀反代。有些应用的仪表盘把资源与 API 地址写死成
        # 根路径（典型写法是 window.location.host + /api/...），
        # 挂在路径前缀下必然 404，只能让它独占一个端口。
        "expose_port": bool(raw.get("expose_port", False)),
        # 路径前缀 API 重写：应用前端把接口地址写成根相对（例如 AIVideoStudio 里的
        # `new URL(path, location.origin)` + '/api/v2/...'），挂在 /p/<id>/ 下会被解析到
        # **面板根路径**而 404。它的静态资源能靠 HTML 属性重写正常加载，所以症状很有
        # 迷惑性：页面骨架出来了、js/css 也 200，但接口全 404，界面是一片错误文案。
        # 勾上后反代会往页面注入一段同源脚本（proxy.SHIM_PATH），把运行时的 fetch/XHR
        # 根相对请求补回前缀。只能走独立端口的应用（expose_port，比如还有
        # WebSocket 流量、shim 兜不住的那些）不要勾这一项。
        "prefix_api": bool(raw.get("prefix_api", False)),
        "env": {str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        # 内置命令修订版：仅供 _upgrade_builtin_cmds 判断「catalog 的命令是否比配置里的新」。
        # 本函数是**显式枚举键**的白名单，不在这里列出来的字段会在读写配置时被丢掉，
        # 闸门就永远打不开 —— 以后加新字段时务必同步这里。
        "cmd_rev": int(raw.get("cmd_rev") or 0),
    }
    used = {a["port"] for a in apps if a.get("id") != app["id"]}
    if not app["port"] or (reassign_port and app["port"] in used):
        within = (EXPOSE_PORT_START, EXPOSE_PORT_END) if app["expose_port"] else None
        app["port"] = next_free_port(settings, exclude=app["id"], apps=apps, within=within)
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
                   apps: list[dict] | None = None,
                   within: tuple[int, int] | None = None) -> int:
    """挑一个空闲端口号。

    within=(lo, hi) 时只在区间内挑 —— expose_port 应用必须落在容器已发布的端口段
    里，否则直连地址从宿主机根本连不上。区间被占满时退化为从 port_start 起找：
    宁可给出一个区间外的端口（界面上会挂醒目提示），也不要抛异常让播种整个失败。
    """
    if apps is None:
        apps = load_config().get("apps", [])
    used = {a["port"] for a in apps if a.get("id") != exclude}
    if within:
        port = within[0]
        while port <= within[1] and port in used:
            port += 1
        if port <= within[1]:
            return port
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

