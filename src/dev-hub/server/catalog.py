"""面板内置应用清单（预置条目）。

面板加载配置时会把这里「缺失」的条目补进 config.json：
- 全新安装：开箱就有这些卡片；
- 已有配置：只补缺失的 id，用户改过的条目一律不覆盖；
- 用户在面板里删掉某个内置条目：该 id 会写入 config.removed，之后不再补回。

字段含义与 store.normalize_app 一致。run / setup 中的 {port} 在启动时替换为实际端口。

注意：这些子应用都在面板容器内以子进程运行，因此
- 端口必须是容器内空闲端口（面板从 settings.port_start 起分配，默认 19100）；
- 浏览器只通过面板反代 /p/<id>/ 访问，子应用无需对外暴露端口；
- 反向代理只映射「一个」端口，所以需要多进程的应用要拆成多张卡片
  （典型的 mini_games：H5 静态预览与后端 API 就是两张卡）。
"""
from __future__ import annotations

BUILTIN_APPS: list[dict] = [
    {
        "id": "ai-video-studio",
        "name": "AI Video Studio",
        "repo": "https://github.com/mayishidai/AIVideoStudio.git",
        "branch": "master",          # 注意：该仓库默认分支是 master，不是 main
        "port": 19101,
        "desc": "AI 视频生成工作台（FastAPI）。首次启动会自动建 venv 装依赖，媒体合成依赖镜像内的 ffmpeg。",
        # 只装 requirements.lock（uv 生成、带 hash）；不用 requirements.txt，因为仓库里没有这个文件。
        "setup": (
            "python3 -m venv .venv\n"
            ".venv/bin/pip install -q -U pip\n"
            ".venv/bin/pip install --require-hashes -r requirements.lock"
        ),
        # 刻意不传 --host：run.py 会强制校验必须是 loopback，
        # 传 0.0.0.0 会直接报错退出；而面板代理连的正是容器内 127.0.0.1，恰好匹配。
        "run": ".venv/bin/python run.py --no-browser --port {port}",
        "auto_start": True,
        "enabled": True,
        "env": {},
    },
    {
        "id": "fund",
        "name": "韭菜盒子 LeekFund",
        "repo": "https://github.com/mayishidai/fund.git",
        "branch": "main",
        "port": 19102,
        "desc": "基金/股票自选与盈亏看板（FastAPI）。依赖 akshare + pandas，首次安装较慢。",
        "setup": (
            "python3 -m venv .venv\n"
            ".venv/bin/pip install -q -U pip\n"
            ".venv/bin/pip install -r requirements.txt"
        ),
        # --no-reload：关掉热重载，避免 watchfiles 再起一层子进程导致停止时收不干净。
        "run": ".venv/bin/python main.py --no-reload --port {port}",
        "auto_start": True,
        "enabled": True,
        "env": {},
    },
    {
        "id": "mini-games",
        "name": "小游戏合集 · H5 预览",
        "repo": "https://github.com/mayishidai/mini_games.git",
        "branch": "main",
        "port": 19103,
        "desc": "打包 games/sheep 为单文件 bundle 并起静态服务，点开即可玩。注意：此卡片不含后端 API，游戏走本地模式。",
        # esbuild 已装在镜像里，这里只是兜底（换镜像/自建镜像时自愈）。
        "setup": "command -v esbuild >/dev/null 2>&1 || npm i -g esbuild",
        "run": "node tools/build-sheep.mjs games/sheep {port}",
        "auto_start": True,
        "enabled": True,
        "env": {},
    },
    {
        "id": "mini-games-api",
        "name": "小游戏合集 · 后端 API",
        "repo": "https://github.com/mayishidai/mini_games.git",
        "branch": "main",
        "port": 19104,
        "desc": "羊了个羊后端（零外部依赖，Node 内置 sqlite）。浏览器打开是 JSON 接口，仅用于接口联调。",
        "setup": "",
        # 该服务读 API_PORT（不是泛用的 PORT），所以这里显式注入；--experimental-sqlite 必需且要求 Node >= 22.5。
        "run": "API_PORT={port} node --experimental-sqlite server/index.mjs",
        "auto_start": True,
        "enabled": True,
        "env": {},
    },
    {
        "id": "ai-image-studio",
        "name": "AI Image Studio",
        "repo": "https://github.com/mayishidai/AIImageStudio.git",
        "branch": "main",
        "port": 19105,
        "desc": "仓库目前还没有任何提交，先在面板占个位。代码推上来后，编辑此卡片填好启动命令并勾选「启用」即可。",
        "setup": "",
        "run": "",
        "auto_start": False,
        "enabled": False,            # 空仓库，先禁用，避免自启时报错刷日志
        "env": {},
    },
]
