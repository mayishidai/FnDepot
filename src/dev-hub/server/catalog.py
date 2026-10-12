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
        #
        # ⚠️ 这里是**唯一**用 .uv 而不是 .venv 的应用（见下方 setup 里的说明）。
        # 所以 setup 与 run 必须**同时**写成 .uv，任何一方写错都会导致「装好了却起不来」。
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
            # 用 build:docker 而不是 build：后者是 `tsc -b && vite build`，会跑一遍全量
            # 类型检查（antd + monaco + mermaid 这套规模，慢且吃内存）；官方两个 Dockerfile
            # （docker/Dockerfile 与 fnos/docker/Dockerfile）用的都是 build:docker（只 vite build）。
            "NODE_ENV=production npm --prefix dashboard run build:docker\n"
            # Python：按仓库 uv.lock 锁定安装（uv 本身只装一次）。
            #
            # ⚠️ 这套环境叫 .uv 而不是 .venv，是刻意的：Octop 是 uv 项目（仓库带 uv.lock，
            # 243 个锁包），官方两个 Dockerfile 走的都是 uv 那条路。但面板的 {venv} 默认指
            # .venv —— 所以这里必须**整套**改用 {venv:.uv}，包括下面 run 那一行和 init 那行。
            # 曾经 setup 建 .uv、run 却从 .venv 起，结果是「包都装好了，一启动就
            # .venv/bin/octop: not found」：两个占位符指向不同目录，谁也没报错。
            "echo '==> 阶段 3/4：Python 依赖（uv sync --frozen，按 uv.lock 锁包）'\n"
            # uv 用 pip 装一次即可。之后所有 python 操作都走 uv（官方注释明说 pip 解析
            # octop-harness[all] 这棵依赖树会卡死）。
            "test -x {venv:.uv}uv || { {python} -m venv .uv && {venv:.uv}python -m pip install -q -U pip uv; }\n"
            # 镜像加速：uv.lock 里 243 个包合计约 620 MB（pymupdf 84MB / opencv 78MB /
            # playwright 45MB / pillow 45MB…），从 NAS 直连 files.pythonhosted.org 会慢到超时。
            # 照抄官方 fnos Dockerfile 的写法：阿里云源为主、PyPI 为兜底（新包镜像可能还没同步）。
            "UV_DEFAULT_INDEX=https://pypi.org/simple \\\n"
            "UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \\\n"
            "UV_INSECURE_HOST=mirrors.aliyun.com \\\n"
            "{venv:.uv}uv sync --frozen --no-dev\n"
            "# 首次初始化管理员；已有库则跳过，保证 setup 可重复执行（更新代码后会重跑）\n"
            "if [ ! -f \"$OCTOP_HOME/octop.db\" ]; then\n"
            "  echo '==> 阶段 4/4：初始化数据库与管理员账号'\n"
            "  PW=\"Oc1$(od -An -N8 -tx1 /dev/urandom | tr -d ' \\n')\"\n"
            "  {venv:.uv}octop init --yes --admin-username admin --admin-password \"$PW\"\n"
            "  printf '\\n============================================\\n"
            " Octop 初始账号：admin / %s\\n"
            " （登录后请尽快改密码，退出后再也看不到）\\n"
            "============================================\\n\\n' \"$PW\"\n"
            "fi"
        ),
        # 直连访问时来源在容器外，必须监听 0.0.0.0（不能像 AIVideoStudio 那样只绑 loopback）。
        # ⚠️ 必须用 {venv:.uv} 与上面的 setup 对齐：这是本仓库唯一不是 .venv 的应用。
        "run": "{venv:.uv}octop run --host 0.0.0.0 --port {port}",
        "auto_start": True,
        "enabled": True,
        # 数据落在面板的数据卷里：OCTOP_HOME 是 Octop 唯一认的安装根（~/.octop 的替代）。
        # 放在 /data 下而不是应用目录里，既随卷持久化，又不会把 git 工作区弄脏。
        "env": {"OCTOP_HOME": "/data/octop-home/.octop"},
    },
    {
        "id": "opencut",
        "name": "OpenCut",
        # 接入的是 **opencut-classic**，不是用户最初给的 OpenCut-app/OpenCut。
        # 那个仓库是「推倒重写中」的版本：README 自己写了 being rewritten from the
        # ground up，工具链要 proto + moon + bun + rust，apps/web 只有
        # dev(vite dev) / build / preview / deploy(wrangler) —— **没有任何生产常驻
        # 服务命令**，产物目标是 Cloudflare Workers。面板要的是「起一个进程占一个端口」，
        # 它提供不了，所以接不了。
        # classic 就是新版 README 里明确指向的「今天该用的版本」，Next.js 16，
        # build/start 齐全。代价：它已归档（2026-05 之后不再维护）。
        "repo": "https://github.com/OpenCut-app/opencut-classic.git",
        "branch": "main",
        "port": 19107,
        # 独立端口直连。Next 的 basePath 只能在 next.config.ts 里**构建期**指定
        # （全仓库都搜不到 basePath），而面板的反代是运行时往 HTML/JS 里注入前缀的 ——
        # 已经编进产物的 /_next/static/... 与 RSC 请求路径改不了，挂 /p/opencut/ 下必然 404。
        "expose_port": True,
        "desc": "免费的本地视频编辑器（CapCut 替代品，MIT）。预览与导出走 WASM 在浏览器里完成，"
                "项目数据存在浏览器 IndexedDB，不上传服务器。以独立端口直连：点「打开」跳 "
                "NAS:19107。首次安装要现场装依赖并构建，耗时约十几分钟。",
        # 这套 setup 是 POSIX shell 专有的（多行 + rm/cp + test -d），只能在 Linux 容器里跑。
        # 注意用的是 test -d 而不是别的写法：它正好命中 procs._POSIX_ONLY_RE，于是
        # Windows 上会被提前拦下并给出明确结论，而不是跑到 bun 那一步才报「找不到命令」。
        "setup": (
            "set -e\n"
            "# 仓库是 bun 工作区：只有 bun.lock，没有 npm/pnpm 的 lockfile。bun 由镜像提供\n"
            "# （见 Dockerfile），版本对齐它 package.json 里的 packageManager: bun@1.2.18。\n"
            "# 依赖树里有 sharp / @napi-rs/canvas / @huggingface/transformers 这类带原生二进制\n"
            "# 或体积很大的包，这一步偏慢；--frozen-lockfile 保证按仓库锁定的版本装。\n"
            "echo '==> 阶段 1/3：安装依赖（bun install --frozen-lockfile）'\n"
            "bun install --frozen-lockfile\n"
            "# 构建走仓库自己的脚本（turbo run build --filter=@opencut/web → next build），\n"
            "# next.config.ts 里 output: \"standalone\"。\n"
            "echo '==> 阶段 2/3：构建前端（turbo → next build）'\n"
            "bun run build:web\n"
            "# Next 的 standalone 产物**不会**自动带上 public/ 与 .next/static/，\n"
            "# 必须手工拷进去（上游 Dockerfile 的 runner 阶段也是这么拷的），否则页面能开、\n"
            "# 但 js/css 全 404，一片空白。standalone 里 server.js 的位置由 tracingRoot 决定，\n"
            "# 而 Next 认 bun.lock（dist/lib/find-root.js 里明确列了），所以 tracingRoot 是\n"
            "# 仓库根，路径是 .../standalone/apps/web/server.js。\n"
            "echo '==> 阶段 3/3：把 public 与 .next/static 补进 standalone'\n"
            "test -d apps/web/.next/standalone/apps/web || "
            "{ echo 'standalone 产物不存在，说明上一步 next build 没成功'; exit 1; }\n"
            "rm -rf apps/web/.next/standalone/apps/web/public "
            "apps/web/.next/standalone/apps/web/.next/static\n"
            "cp -r apps/web/public apps/web/.next/standalone/apps/web/public\n"
            "cp -r apps/web/.next/static apps/web/.next/standalone/apps/web/.next/static"
        ),
        # 用 node 而不是 bun 跑 Next 的 standalone 服务：server.js 就是给 node 写的
        # （模板见 next/dist/build/utils.js），node 22 也已随镜像装好，运行期少一个变量。
        # 不需要写 cd：模板里有 process.env.NODE_ENV='production' 与 process.chdir(__dirname)，
        # 所以 cwd 在哪都行、NODE_ENV 也不用我们注入（它的 zod 校验因此能过）。
        "run": "node apps/web/.next/standalone/apps/web/server.js",
        # 视频编辑器是可选工具，而且首次要装十几分钟，不做开机自动安装。
        "auto_start": False,
        "enabled": True,
        # 下面这些值在 apps/web/src/env/web.ts 里被 zod 于**模块加载时**就 parse，
        # 少一个 build 阶段就失败 —— 上游 Dockerfile 也是专门塞了一套 stub 值过校验的。
        # 好消息是它们基本用不到：项目数据在浏览器 IndexedDB；服务器侧只有
        # /api/auth/*（UI 里其实**没有任何登录入口**，auth/client 零引用）、
        # /api/feedback、/api/sounds/search（限流）会碰数据库/Redis。
        # 所以先给占位值就能正常用编辑器；哪天要接真实的 Postgres/Redis，
        # 把这两行改成自己的地址再点「重装依赖」即可。
        "env": {
            # NEXT_PUBLIC_* 会被**打进前端产物**，改了必须重装依赖才生效。
            # 它只影响 metadata/sitemap 这类展示，不影响编辑器；想显示成自己的地址就改这里。
            "NEXT_PUBLIC_SITE_URL": "http://localhost:19107",
            "NEXT_PUBLIC_MARBLE_API_URL": "https://api.marblecms.com",
            "DATABASE_URL": "postgresql://opencut:opencut@127.0.0.1:5432/opencut",
            "BETTER_AUTH_SECRET": "opencut-local-secret-change-me",
            "UPSTASH_REDIS_REST_URL": "http://127.0.0.1:8079",
            "UPSTASH_REDIS_REST_TOKEN": "example_token",
            "MARBLE_WORKSPACE_KEY": "placeholder",
            "FREESOUND_CLIENT_ID": "placeholder",
            "FREESOUND_API_KEY": "placeholder",
            # 必须钉成 0.0.0.0：standalone 的 server.js 读 process.env.HOSTNAME，
            # 缺省才回落到 0.0.0.0，而 Docker 默认会把 HOSTNAME 设成容器 ID
            # （解析得到容器 IP）—— expose_port 是让浏览器从容器外直连，绑错了连不上。
            "HOSTNAME": "0.0.0.0",
        },
    },
    {
        # 2026-10-12：按用户决定「先做成灰色占位」——条目进清单但置灰为「待启用」
        # （enabled=False）：不 clone、不装依赖、不参与自启与更新检测，点「启动」会被
        # main.py 拒掉，卡片上的「打开」也变成不可点的灰按钮。要真接的时候再补
        # setup/run 并在编辑弹窗里勾「启用」。
        #
        # —— 上游形态 ——
        # DramaClaw（Elastic-2.0）是 AI 短剧生产线。官方给的是 **Docker 三容器栈**：
        #     web(nginx，容器内 80 → 宿主 8080) → api(Python，容器内 8780) → newapi 网关(:3000)
        # 其中网关源码在**另一个仓库**（dramaclaw-gateway），api 的聊天后端还要一个
        # 预构建的 codex 运行时（它的 Dockerfile 用 `COPY --from=claymorelab/codex-dramaclaw`，
        # 且那个镜像只有 linux/amd64）。这几样面板都拿不到 —— 面板只 clone 一个仓库、
        # 只起一个进程，容器里也没有 docker。
        #
        # —— 面板能走的那条路（已核实，将来照此实现）——
        # 上游原生支持「无 nginx 的便携部署」：src/novelvideo/api/app.py 里判断
        # DRAMACLAW_FRONTEND_DIST 指向的目录存在就把 SPA 挂到 "/"（带 index.html 回落），
        # 于是**一个进程同时提供 UI 与接口**，正好合面板的模型。
        #   1) 装 uv：{venv}python -m pip install uv（镜像里没有 uv）
        #   2) uv sync --frozen --no-dev（242 个锁包）。不要装 world extra ——
        #      那是 3DGS/SHARP，要 GPU 与 rust 工具链，上游也标为可选。
        #   3) 前端：pnpm --dir frontend install --frozen-lockfile && pnpm --dir frontend run build
        #      （frontend/pnpm-lock.yaml 的 lockfileVersion 是 9.0，镜像里的 pnpm 9 正好能读，
        #        与 AIVideoStudio 同一情形；package.json 里写的 pnpm@11.5.0 只是 corepack 提示）
        #      构建时**不要**设 VITE_API_URL：留空时前端走同源相对路径 /api/...，而 api
        #      自己伺服 SPA 时天然同源，不需要 nginx 那层反代。
        #   4) 聊天后端：上游默认要 codex（拿不到），所以要显式
        #      DRAMACLAW_CHAT_BACKEND=hermes，并按 scripts/setup-hermes.sh 的做法装：
        #      clone dramaclaw/hermes-agent（**用 HTTPS** —— 容器里没有 SSH key，
        #      脚本默认走 git@ 会失败）→ 独立 venv → editable install "[acp]" →
        #      跑本仓库的 deploy/patch_hermes_acp_toolsets.py。这套只用 git+uv+pip，面板做得到。
        #      容器里没有 bubblewrap（Hermes 的 Linux 沙箱），需要 SUPERTALE_ALLOW_UNSANDBOXED=1。
        #   5) 数据目录必须重定向：上游默认 NOVELVIDEO_DATA_ROOT=/data，而面板的数据卷也是 /data，
        #      不覆盖就会写进面板自己的配置目录里。要写成 {data}。
        #
        # —— 为什么先不接 ——
        # ① 首次安装很重：242 个 PyPI 包 + 52 个 npm 包 + 再 clone 一个仓库 + vite 构建，
        #    面板的 setup 超时是 30 分钟，有触及上限的风险；
        # ② 装成也仍是残版：Freezone 无限画布是**另一个独立应用**（前端默认回落到
        #    <当前主机>:5175），面板里没有它；world/3DGS 要 GPU；
        # ③ 没有模型 key 时 UI 能开、但生成必失败 —— 它默认走官方网关 RelayClaw（要 DC key），
        #    自建网关则要再跑一个 dramaclaw-gateway 进程。
        # 结论：完整形态更适合发一个独立的 FPK 应用包（照上游 compose 跑三容器），
        # 面板这张卡先占位。
        "id": "dramaclaw",
        "name": "DramaClaw",
        "repo": "https://github.com/dramaclaw/dramaclaw.git",
        "branch": "main",
        # 直连段里当前空闲的下一个（19105/19106/19107 分别是 ai-image-studio / octop / opencut）。
        # 将来启用时也只能走独立端口：SPA 是前端路由 + 大量视频上传下载 + SSE 进度，
        # 挂 /p/<id>/ 路径前缀必然出问题。
        "port": 19108,
        "expose_port": True,
        "desc": "AI 短剧生产线（脚本→分镜→素材→成片，Elastic-2.0）。暂为待启用占位："
                "它完整形态是 Docker 三容器栈（api + 网关 + web），面板单进程只能跑残缺版；"
                "接入方案与取舍见 README。",
        # setup/run 故意留空：留空正是「占位」语义（store._backfill_placeholder）——
        # 将来把命令补进清单后，已经部署的面板会自动把这两条补齐，不用手工改 config.json。
        # 反过来说，只要这里写了任意一条命令，那条自动补齐逻辑就再也不会碰它。
        "setup": "",
        "run": "",
        "auto_start": False,
        "enabled": False,
        "env": {},
    },
]
