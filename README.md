# FnOS 应用渠道包仓库（FnDepot 兼容）

本仓库集中存放面向 **飞牛 fnOS** 的第三方应用渠道包，供用户在飞牛「应用中心 → 外部应用源」中添加使用。
格式遵循 [FnDepot](https://github.com/EWEDLCM/FnDepot) 的 V2 规范（GitHub 仓库即一个外部源）。

> 飞牛第三方源为去中心化机制：用户自行添加本仓库地址即可，无需官方审核。

## 目录结构

```
FnDepot/
├── fnpack.json                 # 主索引（source_info + apps 索引，客户端读取）
├── apps/
│   └── <appid>.json            # 各应用详情（拆分模式，含 releases/packages 元数据）
├── packages/
│   └── <appid>/                # FPK 打包工程（manifest + cmd/ + config/ + app/docker/ + wizard/）
├── src/
│   └── <appid>/                # 需要自建镜像的应用的源码（CI 构建推送 GHCR，不进 FPK）
├── assets/
│   └── icons/<appid>.png       # 应用图标
├── scripts/
│   ├── new-app.sh              # 多应用脚手架（一键生成详情 + FPK 工程 + 图标并写回索引）
│   ├── update_release_meta.py  # 发布时回填 download_url / sha256 / size（CI 调用）
│   └── verify_source.py        # 按 FnDepot V2 规范做发布前检查（--remote 校验实链）
└── .github/workflows/
    ├── release-fpk.yml         # 发布 CI：打 v* tag 构建/回填/校验/发 Release
    └── build-dev-hub-image.yml # Dev Hub 面板镜像构建（推送到 ghcr.io）
```

> ⚠️ **仓库名必须恰为 `FnDepot`**（大小写敏感）—— 这是 FnDepot 客户端识别 GitHub 源的唯一信标。
> 仓库曾用名 `fnos-app-depot`，改名后旧地址依赖 GitHub 的 301 跳转才能生效；
> 因此**所有 URL 已统一改为 `FnDepot`**，且图标改用仓库相对路径，避免再次改名后失效。

## 已收录应用

| 应用 | 分类 | 说明 |
|---|---|---|
| Agnes AI Studio | AI赋能 | 文生图 / 图生图 / 文生视频 / 图文生视频，调用 Agnes AI 免费模型 |
| Dev Hub 应用导航台 | 系统工具 | 聚合管理自建 GitHub 应用：更新检查、启停控制、日志、统一跳转 |

> Dev Hub 的面板镜像由 `.github/workflows/build-dev-hub-image.yml` 自动构建，
> 改 `src/dev-hub/` 下的代码并推送到 `main` 即会重建镜像；
> 其 FPK 走与其他应用相同的打 tag 发布流程（见下文）。

## Dev Hub 应用导航台

面板把你自己开发的 GitHub 应用聚合到一个界面里，每个应用在**面板容器内以子进程运行**，
因此不需要 docker.sock、也不需要给每个应用单独映射端口。

- **统一入口**：面板本身只占一个端口（默认 `8890`），应用默认经内置反向代理
  `/p/<appid>/` 访问，点卡片上的「打开」即可跳转；少数写死根路径的应用改用
  **独立端口直连**（见下文），卡片「打开」会直接跳到它的专属端口。
- **代码更新**：面板定时对每个应用 `git fetch`，落后远端时卡片标黄提示；
  点「更新代码」才执行 `git pull`（连同重装依赖与重启）。
- **启动停止**：面板直接管理子进程，支持启动 / 停止 / 重启，可配置随面板自启。
- **日志**：实时查看每个应用的运行输出，支持自动刷新与清空。
- **操作记录**：克隆、拉取、启停等面板侧动作单独留痕，便于排查。

> ⚠️ **反向代理只映射一个端口**，所以「浏览器要打开的东西」必须监听该应用的
> `port`。需要同时跑多个进程的应用要拆成多张卡片——`mini-games`（H5 静态预览）
> 与 `mini-games-api`（后端接口）就是这么拆的。
>
> ⚠️ 反代是**按路径前缀改写**的，对「根路径依赖」分三档处理，按代价从低到高：
>
> 1. **HTML 里写死的根相对 `href`/`src`** —— 反代直接改写属性，无需配置（默认行为）；
> 2. **运行时就地拼出来的根相对接口地址** —— 改写不了（服务端只能看到一堆 JS），
>    需要在编辑弹窗里勾上 **「路径前缀 API 重写」**（`prefix_api`，见下）；
> 3. **连上面都不够**（还有 WebSocket 等非 HTTP 流量，或地址来自 `window.location.host`）
>    —— 勾 **「独立端口直连」**（`expose_port`，见下）。

### 内置应用（预置清单）

`src/dev-hub/server/catalog.py` 里维护了一份预置清单，面板启动时会自动补进配置，
**开箱即有卡片，不用手工录入**：

| 应用 ID | 仓库 | 分支 | 端口 | 说明 |
|---|---|---|---|---|
| `ai-video-studio` | AIVideoStudio | `master` | 19101 | AI 视频工作台。只认 loopback 监听，故启动命令**不加** `--host`；**路径前缀 API 重写**，且前端要现场用 pnpm 构建 |
| `fund` | fund | `main` | 19102 | 韭菜盒子。依赖含 akshare + pandas，首次启动装得比较久 |
| `mini-games` | mini_games | `main` | 19103 | 用 esbuild 打包 `games/sheep` 并托管 H5 |
| `mini-games-api` | mini_games | `main` | 19104 | 羊了个羊后端（Node 内置 sqlite） |
| `ai-image-studio` | AIImageStudio | `main` | 19105 | 照片精修工作台（批次/版本/对比图）。**独立端口直连**；静态前端已入库，无需构建 |
| `octop` | Octop | `main` | 19106 | 腾讯 Octop 多智能体助手。**独立端口直连**，首次启动现场构建前端 + 装 243 个锁包 |

播种规则：**只补缺、不覆盖**——已存在的条目（含你改过的字段）一律不动；
在面板里删掉某个内置条目会记进 `config.removed`，之后不再自动补回。

两个例外，都是「补齐空位」而不是「覆盖你写的东西」：

- 旧版本留下的配置在加载时会被补上新字段（例如 `expose_port`、`prefix_api`），
  一律取默认值 `false`，**不会**自动跟随清单翻成 `true`；
- **空占位条目**（`run` 与 `setup` 都为空）会被清单整体补齐（命令、说明、启用状态）。
  判据只看「两条命令是否都为空」——你只要能写出任意一条命令，这条规则就再也不会碰它。
  所以仓库还没代码时占的位，等代码推上来后不需要手工填命令。

### 路径前缀 API 重写（`prefix_api`）

**症状**：`/p/<id>/` 打开后不是白屏，但界面只显示一句错误文案 / 一直转圈。
打开 F12 的 Network 会看到关键线索——**js、css 全是 200，而接口 404**：
请求打到了面板根路径（`http://<面板主机>/api/...`）而不是 `/p/<id>/api/...`。

**原因**：前端把接口地址写成根相对，交给 `fetch` 时又被浏览器按**当前页面的 origin** 解析。
页面挂在 `/p/<id>/` 下时 origin 是**面板**的，于是路径前缀整个丢了：

```ts
// AIVideoStudio 前端 frontend/src/api/client.ts
new URL('/api/v2/capabilities', location.origin).toString()
// → http://面板主机/api/v2/capabilities   ← 前缀没了，面板没有这个路由 → 404
```

服务端改写不了它——地址是 JS 运行时拼出来的，反代只看得见一串压缩过的脚本。

**修法**：勾上编辑弹窗里的 **「路径前缀 API 重写」**。反代会在 HTML 的 `<head>` 里注入一个
同源脚本 `__devhub/prefix-shim.js`，它在请求真正发出前把前缀补回去，覆盖：

- 根相对串：`fetch('/api/x')`
- **同源绝对地址**：`new URL('/api/x', location.origin).toString()` ← 最常见、也最容易漏
- `XMLHttpRequest.prototype.open`
- `Request` 对象形式的 `fetch`

跨源地址、协议相对 `//host`、`data:`、以及**已经带了前缀**的地址一律原样放行，重复注入也不会叠加。

**为什么是独立文件而不是内联 `<script>`**：这类应用的 CSP 通常是
`script-src 'self'`（不含 `'unsafe-inline'`），内联脚本会被浏览器干脆拒掉；
同源外部文件则放行。选中该应用时能看到它的 CSP 就是这样。

**什么时候仍然要用「独立端口直连」**：

1. 应用还有 **WebSocket / SSE** 流量，或地址取自 `window.location.host` ——
   shim 只拦 HTTP（`fetch` / `XHR`），这些它管不到（例如 `octop` 的聊天与终端走 WS）。
2. 应用**在运行时用 `innerHTML` 往页面里塞根绝对地址**（缩略图 `src`、
   下载 `href`）—— 这类节点既不在初始 HTML 里（`_ATTR_RE` 看不到），
   也不经过 `fetch`/`XHR`（shim 拦不到）。**`ai-image-studio` 就是这种**：
   实测走 `/p/` 时接口（走 fetch）全部正常，但照片缩略图 `src="/api/photos/..."`
   3 张全 404，页面能打开、图全是破的。
3. 应用有大流量传输（上传/下载整文件）—— 反代是整包缓冲的，不适合。

后两条同时命中时（照片工作台天然如此），直连端口是更合适的形态，不是绕路。

### 独立端口直连（`expose_port`）

给应用勾上编辑弹窗里的「独立端口直连」后：

- 卡片上出现蓝色 `独立端口直连` 徽章，按钮「打开」直跳 `http://<面板主机>:<端口>/`，
  **不再**走 `/p/<id>/`；
- 直接访问 `/p/<id>/` 会得到一张引导页（写明该走哪个地址），而不是反代结果——
  这个属性跟应用运行与否无关，没运行时引导页会多一句「请先启动」；
- 面板照旧负责 clone、更新检测、启停、日志，只是浏览器绕开了路径前缀。

**代价：必须自己保证端口已发布。** 面板容器只发布了一段固定端口：

```yaml
# packages/dev-hub/app/docker/docker-compose.yaml
ports:
  - "{host_port}:8890"
  - "19100-19119:19100-19119"   # ← 直连段
```

面板会把 `expose_port` 应用的端口限制在 `19100-19119` 内
（`store.EXPOSE_PORT_START` / `EXPOSE_PORT_END`，与上面这行**必须逐字对齐**）。
两道保险：

- 端口落在区间外时，卡片徽章会变成红色的 `直连端口未发布`，提示你去改配置；
- 若应用中心把面板本身分配到了 `19100-19119` 之间，会与这一段冲突导致容器起不来，
  此时请在应用设置页把面板端口改到该区间之外。

> 直连应用必须监听 `0.0.0.0`（访问来源在容器外），不能像 `ai-video-studio`
> 那样只绑 loopback。


### 启用 / 待启用

每个应用都有「启用」开关（编辑弹窗里）。取消勾选后卡片置灰、
不参与自启与更新检测、启动按钮不可点、反代返回 503 提示页。

**空占位条目**（`run` 与 `setup` 都为空）是另一种状态：内置清单里用它来占位
「仓库还没代码」，等代码推上来后，加载配置时会自动按清单补齐命令并启用
（见下文「内置应用」的播种规则）。

### 添加一个应用

在面板里点「＋ 添加应用」，填写：

| 字段 | 说明 |
|---|---|
| 应用 ID | 唯一标识，同时作为目录名与访问路径 `/p/<id>/` |
| GitHub 仓库地址 | `https://github.com/<你>/<repo>.git` |
| 分支 | 默认 `main`；注意部分仓库默认分支是 `master` |
| 端口 | 容器内监听端口，留空自动从 19100 起分配；手填冲突会直接报错 |
| 启动命令 | 在工作目录下执行，支持 `{port}` / `{venv}` 等占位符（见下文） |
| 安装/构建命令 | 可选。**首次启动时自动执行**，更新代码后也会重跑；同样支持占位符 |
| 子目录 | 可选，仓库内相对路径（单仓多应用时用） |
| 环境变量 | 每行 `KEY=VALUE`，会注入子进程；值里也支持占位符，如 `API_PORT={port}` |
| 路径前缀 API 重写 | 勾选框。前端把接口地址写成根相对、挂 `/p/<id>/` 下接口 404（js/css 却正常）时勾上（见上文） |
| 独立端口直连 | 勾选框。上面这招也兜不住（还有 WebSocket / SSE 等非 HTTP 流量）时才勾（见上文） |

**依赖是首次启动时装的**：点了「启动」之后，面板会先在后台跑安装命令
（卡片显示「安装依赖中」，日志可实时看进度），装完再自动拉起进程。
安装在应用目录内建独立 venv，因此不会和面板自己的依赖打架；
结果落在 `state.json`，面板重启不会重复安装。安装失败时卡片标红，
修好后点「重装依赖」再试，或用「更新代码」连带重装。

安装的输出是**边产生边写进应用日志**的，不是等命令跑完才一次性落盘 ——
打开日志抽屉勾上「跟随」，pip / npm 的进度会一屏一屏往上走。这条不只是好看：
akshare / pandas / opencv 这类首次安装真的会被网络读取拖到十几分钟，
而旧实现要等命令整条跑完才有输出，期间界面看着和死了没区别（实测踩过一次
14 分钟空白，最后发现只是网络读取卡住、前台重跑 90 秒就装完）。
针对同一个痛点还有两条兜底：

- **心跳**：输出静默超过 30 秒，面板会补一行
  `setup 仍在运行（已 N 秒，暂无新输出）` —— 一眼区分「慢」和「挂」。
- **超时 30 分钟**：超时按进程组整组终止并标为失败，不会让界面永远停在「安装中」。
  这个上限对 pip / npm 首次安装绰绰有余。

### 命令里的占位符（跨平台）

启动命令 / 安装命令 / 环境变量值里都可以写占位符，由面板在运行时展开，
所以**不要在清单里写死平台路径**：

| 占位符 | 展开为 |
|---|---|
| `{port}` | 应用端口 |
| `{dir}` | 应用工作目录（= clone 下来的仓库根） |
| `{data}` | 面板数据目录（容器里是挂载卷 `/data`）。**用户数据放这里，不要放 `{dir}` 里** —— clone 会被「更新代码」改写，删应用时整个目录直接抹掉 |
| `{venv}` | 主虚拟环境的可执行文件目录，**自带结尾分隔符**：容器 `.venv/bin/`、Windows `.venv\Scripts\` |
| `{venv:名称}` | 同上但指向另一套虚拟环境，例如 `{venv:.uv}` → `.uv/bin/`、`.uv\Scripts\` |
| `{python}` | 建虚拟环境用的解释器：容器 `python3`、Windows 上面板自身的解释器 |
| `{null}` | 空设备：容器 `/dev/null`、Windows `NUL` |

写法是 `{venv}python`，**不是** `{venv}/python` —— cmd.exe 把 `/` 当开关分隔符，
`.venv\Scripts/python` 会直接报「不是内部或外部命令」（实测）。

面板正式跑在 Linux 容器里，这些占位符在容器中的展开结果与旧写法逐字一致；
Windows 分支只是为了让面板能在这台开发机上直接调试子应用。

### 写安装命令时容易踩的三个坑

这三条都真实发生过，而且都属于「看起来成功、其实没装」的静默失败：

1. **多行命令的退出码只反映最后一行。** `sh -c 'false\ntrue'` 返回 0，
   `cmd.exe` 的等价写法同样如此 —— 中间某行失败会被吞掉，面板还会把 `setup_ok`
   记成 `true`，之后**永远不会再重装**。面板现在自动加固：容器里前置 `set -e`，
   Windows 上改用 `&&` 串联；对确实跑不了的 POSIX 专有语法（`if/fi`、`test -`、
   `/dev/urandom` 等）直接给出明确结论，而不是跑到一半才炸。
2. **装 pip 必须走 `python -m pip`。** 新版 pip 拒绝通过 `pip` 这个控制台脚本改装
   自己，会报 `ERROR: To modify pip, please run the following command: ...`。
   配合第 1 条，这条报错以前被完全吞掉 —— 依赖从来没装上，界面却显示「已安装」。
3. **命令前缀式的环境变量赋值是 POSIX 专有语法。** `API_PORT=19104 node ...`
   在 cmd.exe 下报「'API_PORT' 不是内部或外部命令」，请改用环境变量字段。

**容器里没有 `HOME`，面板已经替你兜住（`HOME=/data`）。** 镜像基于官方
`python:3.12-slim`，而飞牛以 `run-as: package` 的非 root uid 启动容器，该 uid 在
镜像的 `/etc/passwd` 里**没有条目** —— npm / uv / pip / git 于是全部定位不到「家目录」：
Node 在这种情况下会以 `uv_os_homedir` ENOENT 直接抛错（`npm` 连 `npm ci` 都进不去），
uv 也拿不到缓存目录。
面板在给子进程注入环境时统一兜底成数据卷 `/data`（镜像的 `ENV` 和 compose 里也各写了
一遍），顺带还让 uv 的缓存与 `.venv` 落在同一文件系统上 —— 默认的硬链接模式才走得通，
缓存放容器可写层、venv 放挂载卷是会跨文件系统报错的。Octop 官方自己的 fnOS 包同样钉了
`HOME=/data`，是同一处坑。

> 这条的判据是：官方 Octop 的 fnOS 包基于**同一个** `python:3.12-slim`，却要在
> Dockerfile 和 compose 里各写一遍 `HOME`；再加上 Node/libuv 的家目录回退链
> （`$HOME` → `getpwuid`）。开发机上没有 Linux 容器，**未能实机复现**，所以按
> 「兜住它不会有任何副作用」处理 —— 已有 `HOME` 时不覆盖，Windows 上完全不碰。

排查时先看应用日志：子进程的 stdout/stderr 会原样落进去
（非 UTF-8 的中文报错自动按 GBK 回退解码），失败时给出真实退出码与报错原文。
安装期间每行输出都带时间戳和 `[setup]` 标记，与面板自己写的 `[dev-hub]` 行区分开，
所以「卡在哪一行之后」可以直接从时间戳的间隔看出来。
内置应用（如 Octop）的安装命令里还前置了几行 `==> 阶段 N/M` 标记，失败时能一眼
定位是卡在下载、构建还是初始化，而不是只看到一句「安装失败」。
单次安装落盘的上限是 1 MB，超出后只排空管道、不再记录（进程照常跑完），
避免一个话痨的构建脚本把日志刷爆。

### 已知限制

- **旧配置不会自动刷新成新的命令写法。** 加载配置只「补缺失的内置应用」和
  「补齐空占位条目」，已有条目（包括用户改过的、有命令的）一律不覆盖。
  所以升级面板后，原有应用仍执行旧的命令字符串 —— 结果等价，
  但不会自动换成新的占位符写法。需要的话删掉 `config.json` 里对应条目
  按新清单重新播种，或在界面上手改。
  具体到今天这件事：Octop 的安装命令新增了 `==> 阶段 N/M` 标记，**已有的
  `config.json` 不会自动带上** —— 想看到阶段标记，得先删掉 `config.json` 里的
  `octop` 条目再重启面板，让它按新清单重新播种。`HOME` 那条兜底在代码与镜像里，
  与 `config.json` 无关，更新镜像即生效。
- **新开关不会自动打开。** `prefix_api` / `expose_port` 都是补默认值 `false`，
  老配置升级上来后需要在编辑弹窗里手动勾一次（勾一次即落库，之后不再需要动）。
- **shim 只拦 HTTP。** 「路径前缀 API 重写」覆盖 `fetch` 与 `XMLHttpRequest`；
  应用的 WebSocket / SSE、以及 `window.location.host` 拼出来的地址它管不到，
  这类应用仍需「独立端口直连」。
- **反代是整包缓冲的。** 上游响应会被完整读进内存再返回（`httpx` 非流式），
  因此**流式响应（SSE、大文件下载、进度条）在 `/p/<id>/` 下不可用**，
  需要这类能力请改用独立端口直连。
- **Octop 只能在容器里安装。** 它的脚本用了 `if/fi`、`test -x`、`/dev/urandom`，
  在 Windows 上会被面板提前拦下并提示，而不是跑到一半才失败。
- **被弄坏的虚拟环境不会自愈。** 安装中途被打断（容器重启等）可能留下半成品 venv，
  而 `python -m venv` 对已存在的 venv 只补写不修复、`ensurepip` 见 dist-info 还在
  也会跳过。此时需手动删掉应用目录下的 `.venv` 再点「重装依赖」。
  （面板现在会明确报失败并打出真实报错，不会静静地装不上。）

数据都保存在飞牛的 `dev-hub` 应用共享目录下（`/vol{n}/@appdata/.../shares/data`）：
`config.json` 是配置，`apps/<id>/` 是 clone 的代码，`logs/` 是日志。
卸载应用不会删除该目录。

> 面板镜像内置 `git`、`python3`、**Node 22**、`esbuild` 与 `ffmpeg`——前两者供
> Python/JS 子应用使用，Node 22 是 `mini_games` 后端（`node:sqlite`）的硬要求，
> `esbuild` 用于打包 H5，`ffmpeg` 供 `AIVideoStudio` 合成成片。
> 若某个应用需要其他运行时，编辑 `src/dev-hub/Dockerfile` 后推送到 `main` 即会自动重建镜像。

## GitHub 用户名

仓库内镜像地址（`ghcr.io/mayishidai/...`）使用 GitHub 用户名 `mayishidai`（与 `fnpack.json` 的 `source_info.author` 一致）。若你 fork 到自己的账号发布，全局替换即可：

```bash
find . -type f \( -name '*.json' -o -name '*.yml' -o -name '*.sh' \) -exec sed -i 's/mayishidai/你的用户名/g' {} +
```

> 脚手架脚本 `scripts/new-app.sh` 会从 `source_info.author` 自动读取此用户名，无需手改模板。

## 发布应用（CI 自动化流程）

1. **发布应用镜像**：应用主仓库 push 到 `main` 自动构建并推送 `ghcr.io/<user>/<appid>:latest`
   （Dev Hub 的源码在本仓库 `src/dev-hub/`，由本仓库的 workflow 负责构建）。
2. **准备源文件**：确保 `apps/<appid>.json` 与 `packages/<appid>/`（fnpack 工程）齐全。
3. **本地预检**：`python3 scripts/verify_source.py`。
4. **打 tag 触发发布**：
   ```bash
   git tag v1.1.0 && git push origin v1.1.0
   ```
   CI 自动完成：构建 FPK → 计算 sha256/size → 回填 `apps/<appid>.json` → 规范校验 → 提交元数据 → 发 GitHub Release。

> **只构建有改动的应用**：CI 会比较「上一个 tag → 当前 tag」的改动，
> `packages/<appid>/` 或 `src/<appid>/` 没动过的应用会被跳过，不会平白多出一个版本。
> 需要全量重建时，用 Actions 页面的手动触发并勾选 `force_all`。
>
> **新增应用**：`packages/<appid>/` 与 `apps/<appid>.json` 建好后**不要**手工登记进
> `fnpack.json`（此时还没有 releases 元数据，校验会失败）；首次打 tag 时 CI 会自动把它登记进索引。
>
> 已发布的「版本号 + 架构」FPK **不可变**（客户端做 sha256 强校验），改内容必须发新版本号。

## 飞牛用户如何使用

1. 飞牛 fnOS → 应用中心 → 设置 → 外部应用源
2. 添加源，填写本仓库地址：`https://github.com/mayishidai/FnDepot`
3. 应用中心即可看到应用，点击安装
4. 安装后在浏览器打开（Agnes AI Studio 默认端口 5000），在设置页填入 Agnes AI API Key 即可使用

## 扩展更多应用

推荐用脚手架一键生成（免去手写多个文件与维护索引）：

```bash
./scripts/new-app.sh <appid> <display_name> <category> [port] [platform]
# 例：./scripts/new-app.sh comfyui "ComfyUI" "AI赋能" 8188 "x86"
```

脚本会自动校验 appid 与分类，生成 `apps/<id>.json`、完整 `packages/<id>/` fnpack 打包工程（含 manifest、cmd/、config/、app/docker/docker-compose.yaml、占位图标）及 `assets/icons/<id>.png`，并写回 `fnpack.json` 索引（GitHub 用户名从 `source_info.author` 自动读取）。

也可完全手动新增一个应用：

1. 在 `fnpack.json` 的 `apps` 中加一个键：
   ```json
   "my-new-app": { "details_url": "apps/my-new-app.json", "details_updated_at": "2026-08-08T22:00:00+08:00" }
   ```
2. 新建 `apps/my-new-app.json`（必填字段同 Agnes，见 FnDepot V2 规范）
3. 如需 FPK，新建 `packages/my-new-app/` 打包工程（最快方式：参考 `packages/agnes-ai-studio/` 结构，或直接跑一次上面的脚手架再改名）
4. 提交即可

分类九选一：`影音娱乐、系统工具、编程开发、AI赋能、生活服务、智能智控、教育学习、游戏地带、硬件驱动`（最多填 2 个，首项为主分类）。

## 发布前检查

提交前务必跑一遍规范校验（对应 FnDepot V2 规范第 12 节「发布前检查清单」）：

```bash
python3 scripts/verify_source.py            # 本地校验
python3 scripts/verify_source.py --remote   # 额外下载远程 FPK，核对 sha256/size
```

校验内容：

- 严格 JSON、无 BOM、`schema_version` 为字符串 `"2"`
- `source_info.name`/`author` 非空；源级不得出现 `details_updated_at`
- 拆分模式下详情文件的 `app_name` 必须与 `fnpack.json` 索引键**完全一致**
- `categories` 仅限九大固定分类；`platform` 仅限 `all`/`x86`/`arm`
- `run_as`/`install_type`/`is_docker` 类型与取值正确
- `icon_url` 相对详情 JSON 解析后必须命中真实文件
- 每个 `packages` 分支的 `sha256` 为 64 位小写十六进制、`size` 为非负整数
- `platform` 与 `packages` 架构键是否对齐（避免语义歧义）
- `packages/<appid>/manifest` 的 `appname` 与源键一致，且 `platform` 未填多个值

CI 已在打 tag 时自动执行该脚本，校验不通过会中断发布。

## 规范要点备忘

- **仓库名必须恰为 `FnDepot`**（大小写敏感）+ Public + 根目录 `fnpack.json`，客户端才按 GitHub 源识别。
- 图标用**仓库相对路径**（相对详情 JSON 所在目录解析），不要写 `raw.githubusercontent.com` 绝对 URL。
- `manifest` 的 `platform` **只能填一个值**；要同时支持 x86 与 arm 必须分别打两个包。
- 已发布的「版本号 + 架构」FPK 视为**不可变**，改内容必须发新版本号或新地址。
- `source_info.author`(源维护者) / `maintainer`(开发者) / `distributor`(发布者) 三者职责不同，不要混用。
