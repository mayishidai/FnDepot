"""面板内置应用清单（预置条目）。

面板加载配置时会把这里「缺失」的条目补进 config.json：
- 全新安装：开箱就有这些卡片；
- 已有配置：只补缺失的 id，用户改过的条目一律不覆盖；
- 用户在面板里删掉某个内置条目：该 id 会写入 config.removed，之后不再补回。

字段含义与 store.normalize_app 一致。run / setup 中的 {port} 在启动时替换为实际端口。

注意：这些子应用都在面板容器内以子进程运行，因此
- 端口必须是容器内空闲端口（面板从 settings.port_start 起分配，默认 19100）；
- 默认浏览器经面板反代 /p/<id>/ 访问，子应用无需对外暴露端口；
- 反向代理只映射「一个」端口，所以需要多进程的应用要拆成多张卡片
  （典型的 mini_games：H5 静态预览与后端 API 就是两张卡）；
- 少数应用的仪表盘把资源/API/WebSocket 地址写死成「根路径」，挂在路径前缀下必然
  404，这类应用要置 expose_port=True 让它独占一个对外端口（见 compose 里发布的
  端口段），卡片上的「打开」会直接跳到 http://<面板主机>:<port>/。
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
    {
        "id": "octop",
        "name": "Octop",
        "repo": "https://github.com/TencentCloud/Octop.git",
        "branch": "main",
        "port": 19106,
        # 独立端口直连：它的仪表盘把资源与 API 地址写死成根路径
        # （window.location.host + /api/...，前端源码 dashboard/src/api/config.ts
        #  里的 BASE_URL 只覆盖了一部分，聊天/终端/远程桌面的 WebSocket 仍走根路径），
        # 挂在 /p/octop/ 下面必然全部 404，只能让它独占一个对外端口。
        "expose_port": True,
        "desc": "腾讯开源的多用户多智能体 AI 助手（Web 控制台 / CLI / IM / 定时任务）。"
                "仪表盘写死根路径，故以独立端口直连：点「打开」跳 NAS:19106。"
                "首次启动要现场构建前端并装 243 个 Python 锁包，耗时约十几分钟。",
        "setup": (
            "set -e\n"
            "# 前端：仓库刻意不提交构建产物（src/octop/dashboard/** 在 .gitignore 里），\n"
            "# 必须现场 npm ci + vite build；产物直接落到 src/octop/dashboard，不影响 git 状态。\n"
            "npm --prefix dashboard ci\n"
            "NODE_ENV=production npm --prefix dashboard run build\n"
            "# Python：按仓库 uv.lock 锁定安装（uv 本身只装一次）\n"
            "test -x .uv/bin/uv || { python3 -m venv .uv && .uv/bin/pip install -q -U pip uv; }\n"
            ".uv/bin/uv sync --frozen --no-dev\n"
            "# 首次初始化管理员；已有库则跳过，保证 setup 可重复执行（更新代码后会重跑）\n"
            "if [ ! -f \"$OCTOP_HOME/octop.db\" ]; then\n"
            "  PW=\"Oc1$(od -An -N8 -tx1 /dev/urandom | tr -d ' \\n')\"\n"
            "  .venv/bin/octop init --yes --admin-username admin --admin-password \"$PW\"\n"
            "  printf '\\n============================================\\n"
            " Octop 初始账号：admin / %s\\n"
            " （登录后请尽快改密码，退出后再也看不到）\\n"
            "============================================\\n\\n' \"$PW\"\n"
            "fi"
        ),
        # 直连访问时来源在容器外，必须监听 0.0.0.0（不能像 AIVideoStudio 那样只绑 loopback）。
        "run": ".venv/bin/octop run --host 0.0.0.0 --port {port}",
        "auto_start": True,
        "enabled": True,
        # 数据落在面板的数据卷里：OCTOP_HOME 是 Octop 唯一认的安装根（~/.octop 的替代）。
        # 放在 /data 下而不是应用目录里，既随卷持久化，又不会把 git 工作区弄脏。
        "env": {"OCTOP_HOME": "/data/octop-home/.octop"},
    },
]
