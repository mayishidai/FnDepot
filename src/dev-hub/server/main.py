"""Dev Hub —— 飞牛 fnOS 应用导航与管理面板。

聚合管理自己开发的 GitHub 应用：代码更新、启动停止、日志查看、统一入口跳转。
所有子应用在面板容器内以子进程运行，经由内置反向代理 /p/<appid>/ 访问。
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import gitops, procs, proxy, store

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Dev Hub", docs_url="/api/docs", openapi_url="/api/openapi.json")

# 内存中的 git 状态缓存：app_id -> {checked_at, data}
_git_cache: dict[str, dict] = {}


# ------------------------------------------------------------------ 启动/关闭

@app.on_event("startup")
async def _startup() -> None:
    store.ensure_dirs()
    await asyncio.to_thread(gitops.init_safe_directory)
    store.append_event("面板启动")
    cfg = store.load_config()
    for item in cfg.get("apps", []):
        if item.get("auto_start"):
            ok, msg = await asyncio.to_thread(procs.start, item)
            if not ok:
                store.append_event(f"{item['id']}: 自启失败 - {msg}")
    app.state.scheduler = asyncio.create_task(_scheduler())


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "scheduler", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await asyncio.to_thread(procs.stop_all)
    store.append_event("面板关闭，已停止全部子应用")


async def _scheduler() -> None:
    """按设置的间隔对所有应用做一次 git fetch 检测。"""
    while True:
        cfg = store.load_config()
        minutes = int(cfg["settings"].get("poll_minutes") or 0)
        await asyncio.sleep((minutes or 30) * 60)
        if not minutes:
            continue
        try:
            await _check_all(cfg)
        except Exception as exc:  # noqa: BLE001 - 后台任务不允许因单次异常退出
            store.append_event(f"定时检测异常：{exc}")


# ------------------------------------------------------------------ 组装视图

async def _app_view(item: dict, cfg: dict) -> dict:
    app_id = item["id"]
    runtime = procs.status(app_id)
    git = _git_cache.get(app_id, {}).get("data")
    if git is None:
        git = await asyncio.to_thread(gitops.status, item)
        _git_cache[app_id] = {"checked_at": time.time(), "data": git}
    return {
        **item,
        "runtime": runtime,
        "git": git,
        "git_checked_at": _git_cache.get(app_id, {}).get("checked_at"),
        "url": f"/p/{app_id}/",
    }


def _require_app(cfg: dict, app_id: str) -> dict:
    item = store.find_app(cfg, app_id)
    if item is None:
        raise HTTPException(404, f"应用 {app_id} 不存在")
    return item


# ------------------------------------------------------------------ 健康检查

@app.get("/api/health")
async def health() -> dict:
    cfg = store.load_config()
    return {
        "ok": True,
        "apps": len(cfg["apps"]),
        "running": sum(1 for a in cfg["apps"] if procs.is_running(a["id"])),
    }


# ------------------------------------------------------------------ 应用 CRUD

@app.get("/api/apps")
async def list_apps() -> list[dict]:
    cfg = store.load_config()
    return [await _app_view(i, cfg) for i in cfg["apps"]]


@app.get("/api/apps/{app_id}")
async def get_app(app_id: str) -> dict:
    cfg = store.load_config()
    return await _app_view(_require_app(cfg, app_id), cfg)


@app.post("/api/apps")
async def create_app(payload: dict = Body(...)) -> dict:
    cfg = store.load_config()
    item = store.normalize_app(payload, cfg["settings"])
    if (err := store.validate_app(item, cfg)):
        raise HTTPException(400, err)
    cfg["apps"].append(item)
    store.save_config(cfg)
    store.append_event(f"{item['id']}: 新增应用")
    if payload.get("clone_now", True):
        await asyncio.to_thread(gitops.clone, item, cfg["settings"]["github_token"])
    return await _app_view(item, cfg)


@app.put("/api/apps/{app_id}")
async def update_app(app_id: str, payload: dict = Body(...)) -> dict:
    cfg = store.load_config()
    old = _require_app(cfg, app_id)
    merged = {**old, **{k: v for k, v in payload.items() if k != "id"}}
    merged["id"] = app_id
    item = store.normalize_app(merged, cfg["settings"])
    if (err := store.validate_app(item, cfg, allow_id=app_id)):
        raise HTTPException(400, err)
    cfg["apps"][cfg["apps"].index(old)] = item
    store.save_config(cfg)
    store.append_event(f"{app_id}: 配置已更新")
    return await _app_view(item, cfg)


@app.delete("/api/apps/{app_id}")
async def delete_app(app_id: str, purge: bool = False) -> dict:
    cfg = store.load_config()
    item = _require_app(cfg, app_id)
    await asyncio.to_thread(procs.stop, app_id)
    cfg["apps"].remove(item)
    store.save_config(cfg)
    _git_cache.pop(app_id, None)

    warning = ""
    if purge:
        ok, detail = await asyncio.to_thread(store.purge_dir, store.app_dir(app_id))
        if not ok:
            warning = f"应用已移除，但代码目录未能完全删除：{detail}"
            store.append_event(f"{app_id}: 代码目录删除不完整 - {detail}")

    store.append_event(
        f"{app_id}: 已移除{'并删除代码' if purge and not warning else '（保留代码目录）'}"
    )
    return {"ok": True, "warning": warning}


# ------------------------------------------------------------------ 运行控制

@app.post("/api/apps/{app_id}/start")
async def start_app(app_id: str, setup: bool = False) -> dict:
    cfg = store.load_config()
    item = _require_app(cfg, app_id)
    ok, msg = await asyncio.to_thread(procs.start, item, setup)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg, "runtime": procs.status(app_id)}


@app.post("/api/apps/{app_id}/stop")
async def stop_app(app_id: str) -> dict:
    cfg = store.load_config()
    _require_app(cfg, app_id)
    ok, msg = await asyncio.to_thread(procs.stop, app_id)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg, "runtime": procs.status(app_id)}


@app.post("/api/apps/{app_id}/restart")
async def restart_app(app_id: str, setup: bool = False) -> dict:
    cfg = store.load_config()
    item = _require_app(cfg, app_id)
    ok, msg = await asyncio.to_thread(procs.restart, item, setup)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg, "runtime": procs.status(app_id)}


# ------------------------------------------------------------------ Git

async def _refresh_git(item: dict, cfg: dict, do_fetch: bool) -> dict:
    token = cfg["settings"]["github_token"]
    if do_fetch:
        ok, out = await asyncio.to_thread(gitops.fetch, item, token)
        if not ok:
            store.append_event(f"{item['id']}: fetch 失败 - {out[:160]}")
    data = await asyncio.to_thread(gitops.status, item)
    _git_cache[item["id"]] = {"checked_at": time.time(), "data": data}
    return data


@app.post("/api/apps/{app_id}/check")
async def check_app(app_id: str) -> dict:
    cfg = store.load_config()
    item = _require_app(cfg, app_id)
    data = await _refresh_git(item, cfg, do_fetch=True)
    return {"ok": True, "git": data}


@app.post("/api/check-all")
async def check_all() -> dict:
    cfg = store.load_config()
    await _check_all(cfg)
    return {
        "ok": True,
        "results": {a["id"]: _git_cache.get(a["id"], {}).get("data") for a in cfg["apps"]},
    }


async def _check_all(cfg: dict) -> None:
    for item in cfg["apps"]:
        try:
            await _refresh_git(item, cfg, do_fetch=True)
        except Exception as exc:  # noqa: BLE001
            store.append_event(f"{item['id']}: 检测异常 - {exc}")


@app.post("/api/apps/{app_id}/update")
async def update_code(app_id: str, setup: bool = False, restart: bool = True) -> dict:
    """拉取代码 →（可选）执行 setup →（可选）重启。"""
    cfg = store.load_config()
    item = _require_app(cfg, app_id)
    token = cfg["settings"]["github_token"]

    was_running = procs.is_running(app_id)
    ok, msg = await asyncio.to_thread(gitops.pull, item, token)
    if not ok:
        raise HTTPException(400, f"更新失败：{msg}")

    steps = [msg]
    if setup:
        s_ok, s_msg = await asyncio.to_thread(procs.run_setup, item)
        steps.append(s_msg)
        if not s_ok:
            raise HTTPException(400, f"更新后执行 setup 失败：{s_msg}")

    if restart and (was_running or item.get("auto_start")):
        r_ok, r_msg = await asyncio.to_thread(procs.restart, item)
        steps.append(r_msg)
        if not r_ok:
            raise HTTPException(400, f"已更新，但重启失败：{r_msg}")

    git = await _refresh_git(item, cfg, do_fetch=False)
    return {"ok": True, "message": " · ".join(steps), "git": git, "runtime": procs.status(app_id)}


# ------------------------------------------------------------------ 日志

@app.get("/api/apps/{app_id}/logs")
async def get_logs(app_id: str, lines: int = procs.TAIL_DEFAULT) -> dict:
    cfg = store.load_config()
    _require_app(cfg, app_id)
    text = await asyncio.to_thread(procs.tail_log, app_id, lines)
    return {"ok": True, "log": text}


@app.delete("/api/apps/{app_id}/logs")
async def clear_logs(app_id: str) -> dict:
    cfg = store.load_config()
    _require_app(cfg, app_id)
    await asyncio.to_thread(procs.clear_log, app_id)
    return {"ok": True}


@app.get("/api/events")
async def get_events(lines: int = 200) -> dict:
    path = store.events_file()
    if not path.is_file():
        return {"ok": True, "log": ""}
    text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
    return {"ok": True, "log": "".join(text.splitlines(keepends=True)[-max(1, min(lines, 1000)):])}


# ------------------------------------------------------------------ 设置

@app.get("/api/settings")
async def get_settings() -> dict:
    s = dict(store.load_config()["settings"])
    s["github_token_set"] = bool(s.get("github_token"))
    s["github_token"] = ""      # 不回传明文
    return s


@app.put("/api/settings")
async def put_settings(payload: dict = Body(...)) -> dict:
    cfg = store.load_config()
    s = cfg["settings"]
    if "poll_minutes" in payload:
        s["poll_minutes"] = max(0, int(payload["poll_minutes"] or 0))
    if "port_start" in payload:
        s["port_start"] = max(1024, int(payload["port_start"] or 19100))
    if "proxy_timeout" in payload:
        s["proxy_timeout"] = max(5, int(payload["proxy_timeout"] or 30))
    if payload.get("github_token"):
        s["github_token"] = str(payload["github_token"]).strip()
    if payload.get("clear_token"):
        s["github_token"] = ""
    store.save_config(cfg)
    store.append_event("设置已更新")
    return await get_settings()


# ------------------------------------------------------------------ 反向代理

async def _do_proxy(request: Request, app_id: str, rest: str) -> Response:
    cfg = store.load_config()
    item = store.find_app(cfg, app_id)
    if item is None:
        return JSONResponse({"detail": f"应用 {app_id} 不存在"}, status_code=404)
    if not procs.is_running(app_id):
        return Response(
            content=proxy._error_page(f"/p/{app_id}", item["port"], "应用当前未运行"),
            status_code=503, media_type="text/html; charset=utf-8",
        )
    return await proxy.forward(
        request, f"/p/{app_id}", rest,
        item["port"], float(cfg["settings"].get("proxy_timeout", 30)),
    )


@app.api_route("/p/{app_id}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_root(request: Request, app_id: str) -> Response:
    return await _do_proxy(request, app_id, "")


@app.api_route("/p/{app_id}/{rest:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_path(request: Request, app_id: str, rest: str) -> Response:
    return await _do_proxy(request, app_id, rest)


# ------------------------------------------------------------------ 前端静态资源

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
