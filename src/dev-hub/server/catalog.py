"""面板内置应用清单（预置条目）。

面板加载配置时会把这里「缺失」的条目补进 config.json：
- 全新安装：开箱就有这些卡片；
- 已有配置：只补缺失的 id，用户改过的条目一律不覆盖；
- 用户在面板里删掉某个内置条目：该 id 会写入 config.removed，之后不再补回。

字段含义与 store.normalize_app 一致。

run / setup / env 的值里可以写占位符，启动或安装时由 procs._render 展开，
因此这里一律不写死平台相关的路径：

    {venv}       主虚拟环境里可执行文件所在目录，**自带结尾分隔符** ——
                 `.venv/bin/`（容器）或 `.venv\\Scripts\\`（Windows）。
                 写法是 `{venv}python` / `{venv}pip`，**不能**写 `{venv}/python`：
                 cmd.exe 把 `/` 当开关分隔符，会报「不是内部或外部命令」。
    {venv:.uv}   同上，但指向另一套虚拟环境；冒号后写完整目录名（Octop 用 .uv，
                 所以是 {venv:.uv}，别漏了开头的点）
    {python}     新建虚拟环境用的解释器 → python3（容器）/ 面板自己的解释器（Windows）
    {null}       空设备 → /dev/null（容器）或 NUL（Windows）
    {port}       应用端口；{dir} 是应用工作目录

也可以反过来，把「只在命令前缀里写一次的变量」放进 env —— 例如
`API_PORT={port}`，因为命令前缀那种 `VAR=值 cmd` 是 POSIX 专有语法，cmd.exe 不认。

装 Python 包一律写 `{venv}python -m pip ...`，**不要**写 `{venv}pip ...`：新版 pip 拒绝
通过控制台脚本改装自己，会报
    ERROR: To modify pip, please run the following command: ... -m pip install ...
而多行命令的退出码只反映最后一行，这条报错曾经被静默吞掉 —— 界面显示「依赖安装完成」，
实际什么都没装上（详见 procs._prepare_setup 的注释）。

注意：这些子应用都在面板容器内以子进程运行，因此
- 端口必须是容器内空闲端口（面板从 settings.port_start 起分配，默认 19100）；
- 默认浏览器经面板反代 /p/<id>/ 访问，子应用无需对外暴露端口；
- 反向代理只映射「一个」端口，所以需要多进程的应用要拆成多张卡片
  （典型的 mini_games：H5 静态预览与后端 API 就是两张卡）；
- 少数应用的仪表盘把资源/API/WebSocket 地址写死成「根路径」，挂在路径前缀下必然
  404，按严重程度分两档处理：
  * 只是「运行时由 JS 拼出来的接口地址」写死根路径 → 置 prefix_api=True，
    反代会注入一段同源脚本把 fetch/XHR 的前缀补回去（见 proxy.SHIM_PATH）；
  * 连 shim 也兜不住（还有 WebSocket 等非 HTTP 流量）→ 置 expose_port=True，
    让它独占一个对外端口（见 compose 里发布的端口段），卡片「打开」直接跳
    http://<面板主机>:<port>/。
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
        # 装 pip 一律走 `{venv}python -m pip`，不要用 `{venv}pip`：新版 pip 拒绝通过控制台脚本
        # 改装自己，会直接报「ERROR: To modify pip, please run ... -m pip install ...」。
        "setup": (
            "{python} -m venv .venv\n"
            "{venv}python -m pip install -q -U pip\n"
            "{venv}python -m pip install --require-hashes -r requirements.lock\n"
            # 前端必须现场构建：仓库只提交了 app/web/dist/index.html（里面是对「带内容哈希的
            # 构建产物」的引用），而 assets/ 是 Vite 的产物、被 .gitignore 忽略 —— 不构建就是
            # 白屏（js/css 全 404，页面上一片空白，控制台报 404）。用仓库自带的 pnpm-lock.yaml
            # 锁版本（镜像里已装 pnpm 9，与 lockfileVersion 9.0 对得上）。
            "pnpm --dir frontend install --frozen-lockfile\n"
            "pnpm --dir frontend run build"
        ),
        # 刻意不传 --host：run.py 会强制校验必须是 loopback，
        # 传 0.0.0.0 会直接报错退出；而面板代理连的正是容器内 127.0.0.1，恰好匹配。
        "run": "{venv}python run.py --no-browser --port {port}",
        # 前端把接口写成根相对再交给 fetch（frontend/src/api/client.ts 里的
        # `new URL(path, location.origin)`，path 形如 /api/v2/capabilities）。
        # 页面挂在 /p/ai-video-studio/ 下时 location.origin 是面板的源，请求会打到
        # 面板根路径 /api/v2/capabilities → 404，界面只剩一句「尚未取得服务能力声明」。
        # js/css 能被 HTML 属性重写救回来，运行时的 fetch 只能靠注入的 shim 兜住。
        # 它的路由是纯哈希路由（#/projects/...）且 vite base 是 /static/dist/，
        # 都不会动 URL 路径，所以 shim 这一层就够了，不需要 expose_port。
        "prefix_api": True,
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
        # 同样必须用 `python -m pip`，理由见 ai-video-studio 的注释。
        "setup": (
            "{python} -m venv .venv\n"
            "{venv}python -m pip install -q -U pip\n"
            "{venv}python -m pip install -r requirements.txt"
        ),
        # --no-reload：关掉热重载，避免 watchfiles 再起一层子进程导致停止时收不干净。
        "run": "{venv}python main.py --no-reload --port {port}",
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
        # 判断方式用 npm 自己的全局清单而不是 `command -v`（后者是 POSIX 专有），
        # 空设备走 {null} 占位符，这样一条命令两个平台都成立。
        "setup": "npm ls -g --depth=0 esbuild >{null} 2>{null} || npm i -g esbuild",
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
        # 该服务读 API_PORT（不是泛用的 PORT），所以显式注入 —— 写进 env 而不是写成
        # 命令前缀 `API_PORT={port} node ...`，后者是 POSIX 专有语法，cmd.exe 不认。
        # --experimental-sqlite 必需且要求 Node >= 22.5。
        "run": "node --experimental-sqlite server/index.mjs",
        "auto_start": True,
        "enabled": True,
        "env": {"API_PORT": "{port}"},
    },
    {
        "id": "ai-image-studio",
        "name": "AI Image Studio",
        "repo": "https://github.com/mayishidai/AIImageStudio.git",
        "branch": "main",
        "port": 19105,
        # 独立端口直连。两个理由，任一条都足以定这个决定：
        # 1) 前端把根绝对地址**在运行时注入 HTML**：照片缩略图走
        #    `innerHTML` 拼出的 `src="/api/photos/<id>/asset/<v>"`，还有
        #    「下载 Markdown 记录」「导出批次 ZIP」的 `href="/api/batches/..."`
        #    （app/static/app.js）。这类地址既不在初始 HTML 里（_ATTR_RE 看不到），
        #    也不经过 fetch/XHR（prefix_api 的 shim 也拦不到）——挂 /p/<id>/ 下
        #    必然 404，页面能开、图全是破的。
        # 2) 它是**照片**工作台：整张原图上传/下载、批次 ZIP 导出都是大流量，
        #    而面板反代是整包缓冲的（httpx 非流式），本来就不适合走代理。
        "expose_port": True,
        "desc": "照片精修工作台（FastAPI）：批次管理、多版本回溯、原图对比、Markdown 版本记录。"
                "Video2X 超分是可选外部依赖（需要可用的 Vulkan 设备），没装不影响常规精修。"
                "以独立端口直连：点「打开」跳 NAS:19105。",
        # 静态前端（app/static/）已入库，不需要构建步骤 —— 与 ai-video-studio 不同。
        "setup": (
            "{python} -m venv .venv\n"
            "{venv}python -m pip install -q -U pip\n"
            "{venv}python -m pip install -r requirements.txt"
        ),
        # 必须监听 0.0.0.0：expose_port 是让浏览器从**容器外**直连已发布的
        # 19105，绑 127.0.0.1 的话容器外连不上（README「独立端口直连」有说明）。
        "run": "{venv}python -m uvicorn app.main:app --host 0.0.0.0 --port {port}",
        # 用户数据（照片、SQLite、版本记录、缩略图）必须放持久目录：{dir} 是 clone，
        # 「更新代码」会改写它、删应用时整个目录直接抹掉，照片放里面迟早丢。
        # 应用默认落在 {dir}/data，这里显式改到面板数据目录下。
        "env": {"PHOTO_WORKBENCH_DATA": "{data}/photo-workbench"},
        "auto_start": True,
        "enabled": True,
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
        # 注意：这套 setup 是 POSIX shell 专有的（if/fi、test、/dev/urandom、`VAR=值 cmd`
        # 前缀），只能在 Linux 容器里跑。在 Windows 上 procs._prepare_setup 会提前拦下并
        # 明确告知，不会跑到一半才炸。
        "setup": (
            "set -e\n"
            "# 每步先打一行阶段标记。这套 setup 只可能在 Linux 容器里跑（Windows 上会被\n"
            "# procs._prepare_setup 提前拦下），失败时用户往往只能把日志贴回来 —— 有阶段\n"
            "# 标记才能一眼定位是卡在下载、构建还是初始化，而不是只看到一句「安装失败」。\n"
            "echo '==> 阶段 1/4：前端依赖（npm ci，1000+ 包，通常最慢）'\n"
            "# 前端：仓库刻意不提交构建产物（src/octop/dashboard/** 在 .gitignore 里），\n"
            "# 必须现场 npm ci + vite build；产物直接落到 src/octop/dashboard，不影响 git 状态。\n"
            "npm --prefix dashboard ci\n"
            "echo '==> 阶段 2/4：前端构建（vite build，antd 模块极多，要够内存）'\n"
            "NODE_ENV=production npm --prefix dashboard run build\n"
            "# Python：按仓库 uv.lock 锁定安装（uv 本身只装一次）\n"
            "echo '==> 阶段 3/4：Python 依赖（uv sync --frozen，按 uv.lock 锁包）'\n"
            "test -x {venv:.uv}uv || { {python} -m venv .uv && {venv:.uv}python -m pip install -q -U pip uv; }\n"
            "{venv:.uv}uv sync --frozen --no-dev\n"
            "# 首次初始化管理员；已有库则跳过，保证 setup 可重复执行（更新代码后会重跑）\n"
            "if [ ! -f \"$OCTOP_HOME/octop.db\" ]; then\n"
            "  echo '==> 阶段 4/4：初始化数据库与管理员账号'\n"
            "  PW=\"Oc1$(od -An -N8 -tx1 /dev/urandom | tr -d ' \\n')\"\n"
            "  {venv}octop init --yes --admin-username admin --admin-password \"$PW\"\n"
            "  printf '\\n============================================\\n"
            " Octop 初始账号：admin / %s\\n"
            " （登录后请尽快改密码，退出后再也看不到）\\n"
            "============================================\\n\\n' \"$PW\"\n"
            "fi"
        ),
        # 直连访问时来源在容器外，必须监听 0.0.0.0（不能像 AIVideoStudio 那样只绑 loopback）。
        "run": "{venv}octop run --host 0.0.0.0 --port {port}",
        "auto_start": True,
        "enabled": True,
        # 数据落在面板的数据卷里：OCTOP_HOME 是 Octop 唯一认的安装根（~/.octop 的替代）。
        # 放在 /data 下而不是应用目录里，既随卷持久化，又不会把 git 工作区弄脏。
        "env": {"OCTOP_HOME": "/data/octop-home/.octop"},
    },
]
