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
├── vendored/
│   └── <repo>/                 # 面板托管的应用（git 子仓库，只读快照，**不参与构建**）
├── upstream/
│   └── <name>.json             # 上游同步目标（「作者自己发 FPK、我们只转发」的应用）
├── assets/
│   └── icons/<appid>.png       # 应用图标
├── scripts/
│   ├── new-app.sh              # 多应用脚手架（一键生成详情 + FPK 工程 + 图标并写回索引）
│   ├── update_release_meta.py  # 发布时回填 download_url / sha256 / size（CI 调用）
│   ├── sync_upstream.py        # 定时同步上游已发布的 FPK（cron 调用）
│   └── verify_source.py        # 按 FnDepot V2 规范做发布前检查（--remote 校验实链）
└── .github/workflows/
    ├── release-fpk.yml         # 发布 CI：打 v* tag 构建/回填/校验/发 Release
    ├── sync-upstream.yml       # 上游同步 CI：cron 每 6 小时跟着作者更新
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
| 飞牛影视在线扩展 | 影音娱乐 | 给官方影视加在线搜索/播放，轻量版，每 6 小时自动跟随上游更新 |
| 飞牛影视在线扩展（全功能版） | 影音娱乐 | 同上，额外含加固源并发解析等增强，安装包较大，同样自动跟随 |
| iPTV 直播源管理 | 影音娱乐 | 自托管 IPTV：800+ 频道聚合、EPG 节目单、可视化后台，跑官方 Docker 镜像 |
| fnMusic 音源扩展 | 影音娱乐 | 给官方音乐加在线音源（musicdl/网易云/洛雪），引用上游 FPK，每 6 小时自动跟随 |
| fnMusic 音源扩展（预览版） | 影音娱乐 | 同上，但只收上游 Pre-release；**与稳定版是同一 appid，二选一** |

> 上表中「飞牛影视在线扩展 /（全功能版）」与「fnMusic 音源扩展 /（预览版）」是两组
> **同一个 appid 拆成的两个条目**，本仓库**不打包、只转发**：
> 两枚包装进去是同一个应用（装了其一就不能再装其二），列表里会看到两张卡片，按需要二选一。
> 详见下方「自动跟随上游更新」与「预览版通道」。

### ⚠️ 收录前的安全审查结论（fnmedia-ext）

解包审计过两份 FPK 的全部内容，**这个应用是有实质权限的，装之前请知悉**：

| 项 | 事实 |
|---|---|
| 运行身份 | 包内 `config/privilege` 声明 **`run-as: root`**，并在 `/etc/systemd/system/` 装 `fnmedia-ext.service` |
| 接管方式 | 把官方影视的 `/var/run/trim_media.sock` 原子换名成自己的，官方原 socket 挪到 `trim_media_upstream.sock` → **官方影视的全部 API 流量都经过这个第三方进程** |
| 内置资源站 | `providers.py` 内置 **10 个第三方苹果 CMS 采集站且默认 `enabled: True`**（暴风/非凡/量子/无尽/优酷/光速/如意/极速/新狼/电影天堂/360）→ 涉及**版权与合规风险**，请自行判断 |
| TLS | 代码里 **10 处 `verify=False`**（`app.py` 1、`catalog.py` 4、`subfetch.py` 5），即部分请求不校验证书，存在被中间人的可能 |
| 自更新 | 应用可从自己的 GitHub Release 拉 FPK 热替换升级。设计上克制（**只在管理页手动点击**才装、强制 sha256 校验、只认自己仓库），但 root 进程 + 网络更新本身是供应链风险面 |
| 依赖安装 | 安装时联网 `pip install fastapi uvicorn httpx`，**无版本锁定、无 hash 校验** |
| 订阅功能 | 可下载并执行第三方 **spider jar / DRPY 规则脚本**，以及 GitHub 加速代理（`ghproxy.net`/`ghfast.top`/`raw.gitmirror.com`）取源 |
| 全功能版额外 | 多带一个 `spider-runner`：会在机器上起 **Android（redroid）容器 + jar 桥接**执行爬虫，攻击面与资源占用都更大 |

做得好的地方（客观说）：接管前会**校验目标进程确实是官方 trim-media**、健康检查失败就不接管、
用原子换名（可回滚）、停止与卸载时还原官方 socket；`config/resource` 的 `api-scope` 为空，没申请额外 API。

**结论**：技术上是「可逆、克制」的实现，不是恶意软件；但它是 root 的中间人 + 聚合盗版源的工具。
要不要装取决于你对上游 `yujian0815` 的信任程度和当地法律环境。不确定就别装，或装了也别导入第三方源。

### fnmusic-ext 的审查结论（对比参照）

同样解包审计过。**工程质量与安全性明显好于 fnmedia-ext**：

| 项 | fnmusic-ext | fnmedia-ext |
|---|---|---|
| `verify=False`（关 TLS 校验） | **0 处** | 10 处 |
| `eval` / `exec` / `os.system` / `curl\|bash` | **0 处** | 有 subprocess 与网络自更新 |
| 预置大产物的完整性 | **有 sha256 锁定且实测一致**（26MB 的 lx-music-sync-server 与 native 包） | 无 |
| 安全边界声明 | **有 `SECURITY.md`**：不改 nginx、不改官方二进制、不写官方 `music.db`、失败必须能回退 | 无 |
| `cmd/` 脚本权限 | **0755** | 644 |

仍然存在的风险（同类应用绕不开）：`run-as: root` + 装 systemd unit + 接管官方音乐
`/var/run/trim_music.socket`（官方音乐流量过它）；`config/resource` 申请了
**`trim.file.userAccess`（用户文件访问）**；安装需要 Docker（它会起一个音源容器）；
网易云音源要**扫码登录**（账号凭据交给本地服务）；洛雪音源属第三方源。

### 预览版通道（`fnmusic-ext-preview`）

上游 `javycoder` 会把「修了正式版 bug、但还没完整测试」的版本标成 Pre-release
（如 `v2.11.0d`，作者自己写了「追求稳定性请下载正式版」）。这类版本**单独开一个条目**收录，
不混进稳定版的版本列表 —— 否则同一个列表里既有 `2.10.2` 又有 `2.11.0-3`，用户很难判断谁更新、
哪个能装。

区分办法是三条一起上：

| 位置 | 标记 |
|---|---|
| `display_name` | 后缀「（预览版）」，列表里一眼能分 |
| 每个版本的 `changelog` | 开头固定加 **`[预览版]`**（前缀在 500 字截断之外，不会被正文挤掉） |
| `desc` | 同步时**自动算出与稳定版的版本关系**，见下 |

desc 里那段说明是同步脚本按当前数据生成的，例如现在写的是：

> 本条目只收录上游标记为 Pre-release 的版本，与「稳定版」是**同一个 appid**（装了其一就不能
> 再装其二）。当前基线稳定版 **2.10.2**，上游已有 **1 个预发布迭代**在其之后（v2.11.0d），
> 即本条目比稳定版新。版本号带 `-N` 后缀即预发布（如 `2.11.0-3`），按 SEMVER 语义它**小于**
> 对应的正式版 `2.11.0`；一旦上游把 `2.11.0` 转为正式版，稳定版条目会收录它，届时请以稳定版为准。

也就是说：**`-N` 后缀 = 预发布**，且 `2.11.0-3 < 2.11.0`（SEMVER 规定）。上游哪天把预发布转正，
稳定版条目会收到 `2.11.0`，那时预览版条目就落后了 —— desc 里的基线文案会自动跟着改。

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
| `opencut` | opencut-classic | `main` | 19107 | OpenCut 视频编辑器（CapCut 替代品）。**独立端口直连**；项目数据在浏览器 IndexedDB，服务器侧基本不需数据库 |
| `dramaclaw` | dramaclaw | `main` | 19108 | AI 短剧生产线（Elastic-2.0）。**待启用占位**（灰色卡片，暂不接入，见下） |

> **`opencut` 为什么接的是 `opencut-classic` 而不是 `OpenCut-app/OpenCut`？**
> 后者是**推倒重写中**的版本：README 自陈 being rewritten from the ground up，
> 工具链要 proto + moon + bun + rust，`apps/web` 只有 `dev`(`vite dev`) / `build` /
> `preview` / `deploy`(`wrangler deploy`) —— **没有任何生产常驻服务命令**，
> 产物目标是 Cloudflare Workers。面板要的是「起一个进程占一个端口」，它提供不了。
> `opencut-classic` 就是新版 README 明确指向的「今天该用的版本」，Next.js 16、
> `build`/`start` 齐全；代价是它**已归档**（2026-05 后不再维护）。

> **`opencut` 的数据库/Redis 基本用不到。** 项目数据存在浏览器 IndexedDB；
> 服务器侧只有 `/api/auth/*`（UI 里其实**没有任何登录入口**，`auth/client.ts` 零引用）、
> `/api/feedback`、`/api/sounds/search`（限流）会碰它。
> 但 `apps/web/src/env/web.ts` 的 zod 是在**模块加载时**就 `parse(process.env)` 的，
> 少一个变量 `next build` 就失败（上游 Dockerfile 也是专门塞了一套 stub 值过校验）。
> 所以清单里先给的是占位值 —— 编辑器照常能用；要接真实 Postgres/Redis，
> 改 `config.json` 里 `opencut` 的 `DATABASE_URL` 与 `UPSTASH_REDIS_REST_*` 再点「重装依赖」。
> 注意 `NEXT_PUBLIC_*` 会被**打进前端产物**，改了必须重装依赖才生效。

> **怎么把 `opencut` 卡片拿到手？** 拉新镜像重启面板就行，不用手工改配置。
> 它属于「上次加载配置时还不存在」的内置应用，下次加载会被自动补进 `config.json`。
> 已对本机 `store.load_config()` 实测过 NAS 的处境（既有配置 + 用户改过某个内置应用）：
> `opencut` 被追加、拿到空闲端口，那个被改过的应用的自定义 `desc`/`run`/`env` 与端口
> 原样保留，用户自建条目不动，二次加载幂等。判据与例外见下文「播种规则」。

> **`dramaclaw` 为什么是一张灰卡片？** 它是**待启用占位**（`enabled: false`）：
> 卡片出现在面板里但置灰、按钮禁用、状态显示「待启用」，不 clone、不装依赖、
> 不参与自启与更新检测，点「启动」会被拒 —— `main.py` 里待启用的应用连 clone 都跳过
> （那里的注释原文是「免得白白拉几 G 代码」，而这个仓库有 248MB）。
> 原因：上游 DramaClaw 的完整形态是 **Docker 三容器栈**（`web`/nginx → `api` → `newapi` 网关），
> 而面板只 clone 一个仓库、只起一个进程、容器里也没有 docker。网关源码在**另一个仓库**，
> api 的聊天后端还要一个预构建的 codex 运行时（它的 Dockerfile 用
> `COPY --from=claymorelab/codex-dramaclaw`，且那个镜像只有 linux/amd64）——
> 这几样面板都拿不到。所以面板最多只能得到残版：缺 Freezone 画布（那是另一个独立应用）、
> 缺 GPU 相关特性，且没有模型 key 时生成必失败（它默认走官方网关，要 DC key）。
> 将来要真接，路子已经查明、写在 `server/catalog.py` 该条目的注释里：上游原生支持
> 「无 nginx 的便携部署」—— 设 `DRAMACLAW_FRONTEND_DIST` 指向前端产物目录，
> api 就把 SPA 挂到 `/`，**一个进程同时提供 UI 与接口**；聊天后端改用 hermes 即可
> （`scripts/setup-hermes.sh` 只用 git + uv + pip，面板做得到）。
> ⚠️ 一个交互细节：该条目的 `run` 与 `setup` 现在都留空，正好命中「空占位」规则 ——
> 所以**只在编辑弹窗里勾「启用」而不填启动命令，下次加载配置会被清单重置回「待启用」**
> （已实测）。要真正启用，必须同时把启动命令填上；一旦填了，这条规则就再也不会碰它。

播种规则：**只补缺、不覆盖**——已存在的条目（含你改过的字段）一律不动；
在面板里删掉某个内置条目会记进 `config.removed`，之后不再自动补回。

**例外一、二都是「补齐空位」**，而不是「覆盖你写的东西」：

- 旧版本留下的配置在加载时会被补上新字段（例如 `expose_port`、`prefix_api`），
  一律取默认值 `false`，**不会**自动跟随清单翻成 `true`；
- **空占位条目**（`run` 与 `setup` 都为空）会被清单整体补齐（命令、说明、启用状态）。
  判据只看「两条命令是否都为空」——你只要能写出任意一条命令，这条规则就再也不会碰它。
  所以仓库还没代码时占的位，等代码推上来后不需要手工填命令。

**例外三：修正过的内置命令会自动升级到老配置。** 光改 catalog 到不了已经写进
`config.json` 的条目（那就是「只补缺、不覆盖」的代价），所以我们修正自己的内置命令时
会顺手把该条目的 `cmd_rev` 加一；加载配置时
`store._upgrade_builtin_cmds` 据此把老配置里的 `run`/`setup` 换成新的，并在「事件」里
记一条 `xxx: 内置命令已升级到 cmd_rev=N`。
两道闸门保证它只动**我们自己播种的那份**：除了 `cmd_rev` 必须更大，配置里的 `run`
还必须**恰好等于** catalog 里 `cmd_prev_run` 记下的上一版原文 —— 对不上就说明是你自己
改过的，直接跳过（只把 `cmd_rev` 标记为已评估）。所以**你自定义的启动命令永远不会被覆盖**。

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
   shim 只拦 HTTP（`fetch` / `XHR`），这些它管不到（聊天、终端这类走 WS 的都在此列）。
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
缓存放容器可写层、venv 放挂载卷是会跨文件系统报错的。

> 这条的判据是：第三方的 fnOS 应用包基于**同一个** `python:3.12-slim`，却要在
> Dockerfile 和 compose 里各写一遍 `HOME`；再加上 Node/libuv 的家目录回退链
> （`$HOME` → `getpwuid`）。开发机上没有 Linux 容器，**未能实机复现**，所以按
> 「兜住它不会有任何副作用」处理 —— 已有 `HOME` 时不覆盖，Windows 上完全不碰。

排查时先看应用日志：子进程的 stdout/stderr 会原样落进去
（非 UTF-8 的中文报错自动按 GBK 回退解码），失败时给出真实退出码与报错原文。
安装期间每行输出都带时间戳和 `[setup]` 标记，与面板自己写的 `[dev-hub]` 行区分开，
所以「卡在哪一行之后」可以直接从时间戳的间隔看出来。
内置应用的安装命令里还前置了几行 `==> 阶段 N/M` 标记，失败时能一眼
定位是卡在下载、构建还是初始化，而不是只看到一句「安装失败」。
单次安装落盘的上限是 1 MB，超出后只排空管道、不再记录（进程照常跑完），
避免一个话痨的构建脚本把日志刷爆。

### 已知限制

- **等价改写不会自动刷新，但「修正」会。** 加载配置只「补缺失的内置应用」和
  「补齐空占位条目」，已有条目的命令一律不覆盖 —— 所以**只换占位符写法、不改行为**
  的等价改写不会同步到老配置（结果也等价，无妨）。但一旦是**修正**（会真出故障的
  bug，比如 setup 与 run 指向了不同的虚拟环境目录），我们会在清单里把该条目的 `cmd_rev` 加一，
  加载配置时自动把老配置的命令换成新的，并在「事件」里留一条
  `xxx: 内置命令已升级到 cmd_rev=N`：**拉新镜像重启面板即可，不用手动删条目**。
  判据见上文「播种规则」的例外三（`cmd_rev` + `cmd_prev_run` 指纹，你自己改过的
  启动命令不受影响）。`HOME` 那条兜底在代码与镜像里，与 `config.json` 无关，
  更新镜像即生效。
- **新开关不会自动打开。** `prefix_api` / `expose_port` 都是补默认值 `false`，
  老配置升级上来后需要在编辑弹窗里手动勾一次（勾一次即落库，之后不再需要动）。
- **shim 只拦 HTTP。** 「路径前缀 API 重写」覆盖 `fetch` 与 `XMLHttpRequest`；
  应用的 WebSocket / SSE、以及 `window.location.host` 拼出来的地址它管不到，
  这类应用仍需「独立端口直连」。
- **反代是整包缓冲的。** 上游响应会被完整读进内存再返回（`httpx` 非流式），
  因此**流式响应（SSE、大文件下载、进度条）在 `/p/<id>/` 下不可用**，
  需要这类能力请改用独立端口直连。
- **用 POSIX shell 语法写的安装命令只能在容器里跑。** 脚本里出现 `if/fi`、`test -x`、
  `/dev/urandom` 这类写法时，在本机（Windows）上面板会提前拦下并明确提示，
  而不是跑到一半才失败。
- **虚拟环境目录名可以换（`{venv:名称}`），但一处改就得处处改。** `{venv}` 默认指
  `.venv/`，冒号后给完整目录名即可换（例如 uv 项目用 `{venv:.uv}`）。
  同一个应用的 `setup`、`run` 以及任何直接调可执行文件的命令必须用**同一个**占位符 ——
  曾经 setup 建一套、run 却从另一套起，结果「依赖装好了、一启动就 not found」，
  而两边都不报错、日志里一片正常。
  `verify_render.py` 有一条断言专门盯着「setup 与 run 必须指向同一套环境」。
- **被弄坏的虚拟环境不会自愈。** 安装中途被打断（容器重启等）可能留下半成品 venv，
  而 `python -m venv` 对已存在的 venv 只补写不修复、`ensurepip` 见 dist-info 还在
  也会跳过。此时需手动删掉应用目录下的 `.venv` 再点「重装依赖」。
  （面板现在会明确报失败并打出真实报错，不会静静地装不上。）

数据都保存在飞牛的 `dev-hub` 应用共享目录下（`/vol{n}/@appdata/.../shares/data`）：
`config.json` 是配置，`apps/<id>/` 是 clone 的代码，`logs/` 是日志。
卸载应用不会删除该目录。

> 面板镜像内置 `git`、`python3`、**Node 22**、`esbuild`、`pnpm 9`、**`bun`** 与 `ffmpeg`——
> 前两者供 Python/JS 子应用使用，Node 22 是 `mini_games` 后端（`node:sqlite`）的硬要求，
> `esbuild` 用于打包 H5、`pnpm` 给 `AIVideoStudio` 构建前端、
> `bun` 是 `opencut-classic` 的包管理器（该仓库只有 `bun.lock`），`ffmpeg` 供合成成片。
> 这些运行时都是**以 root 装进镜像**的：面板本身以非 root 的 `package` 用户运行，
> 装不了全局包（`npm i -g` 会 EACCES），所以子应用「缺什么运行时就在镜像里加」。
> `bun` 特意选 baseline 构建：普通 x64 构建要求 CPU 支持 AVX2，
> 而不少飞牛设备是老的 Celeron/Atom，跑起来会直接「Illegal instruction」。
> 装进镜像这件事本身可查：CI 构建日志里有 `#10 0.927 1.2.18`，
> 那就是 `bun --version` 的实际输出（与仓库钉的 `packageManager: bun@1.2.18` 一致）；
> 已发布镜像的 `config.history` 里也有这条 `RUN`，且不是 empty layer。
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

### 不构建、只引用上游已发布的 FPK

上游自己就在发 FPK 时，不必在本仓库重复打包：直接把 `download_url` 指向上游 Release
资产，填好 `sha256` / `size` 并登记索引即可。

- **不要**再建 `packages/<appid>/`：CI 的发现逻辑是「`packages/<id>/` 有 `manifest`
  且 `apps/<id>.json` 存在」，留着目录会让它**每次打 tag 都额外构建一枚我们自己的 FPK**，
  还往 `releases` 里塞一条 tag 版本号的记录，和引用版打架。
- 版本号键要跟 **FPK 内部 `manifest` 的 `version`** 一致（不要照抄上游 Release 的 tag，
  两者经常不是同一个数）。解包看：
  `python -c "import tarfile;print(tarfile.open('<x>.fpk').extractfile('manifest').read().decode())"`
- 多架构（x86 + arm64 两枚包）**不是两个版本**，而是同一个版本节点下的两个架构键，
  同时 `platform` 写 `["x86","arm"]`。
  ⚠️ 键名以**实际产物架构**为准，别照抄包内 manifest 的 `platform` ——
  曾经见过 x86 包里写 `all`、arm 包里才写 `arm` 的。
- `sha256` / `size` 这里**只能手工填**（没有 CI 构建可回填），所以务必跑
  `python3 scripts/verify_source.py --remote` —— 它会真下载并比对，填错当场报错。
- 校验会提示 `未找到 packages/<appid>/manifest`，这条警告是**预期的**。
- 代价：上游删资产/改文件名会导致本源失效，且上游包自身的缺陷我们改不了。
>
> 已发布的「版本号 + 架构」FPK **不可变**（客户端做 sha256 强校验），改内容必须发新版本号。

### 自动跟随上游更新

有些上游发版极勤（`yujian0815/fnmedia-ext` 一天能发 3~4 个版本），人手同步根本跟不上。
这类应用交给 `.github/workflows/sync-upstream.yml`：cron 每 6 小时跑一次
`scripts/sync_upstream.py`，查上游有没有新 Release，有就自动下载、算 sha256/size、
写进 `apps/<appid>.json` 并提交。

要接一个新上游，加一份 `upstream/<name>.json` + 建一个 `apps/<appid>.json`
（首版只填静态字段即可，`releases` 交给同步脚本补）：

```json
{
  "repo": "yujian0815/fnmedia-ext",
  "keep_versions": 10,
  "variants": [
    {
      "appid": "fnmedia-ext",
      "asset": "fnmedia-ext-{version}.fpk",
      "arch": "all",
      "categories": ["影音娱乐"],
      "icon": "../assets/icons/fnmedia-ext.png",
      "display_name": "{manifest}",
      "changelog_from": "plain"
    }
  ]
}
```

一个上游同时发多枚包时，用多个 `variants` 产出多个条目（我们就是这么把「轻量版」和
「全功能版」分成 `fnmedia-ext` / `fnmedia-ext-full` 的）。`display_name` 里的
`{manifest}` 会在同步时替换成包内 manifest 的值；`desc_suffix` 可给描述追加本地说明。

同一个上游还可以按**发布通道**拆条目 —— 用 `channel` 指定：

```json
{ "appid": "fnmusic-ext",         "channel": "stable",     "keep_versions": 10 },
{ "appid": "fnmusic-ext-preview", "channel": "prerelease", "keep_versions": 3,
  "display_name": "{manifest}（预览版）", "changelog_prefix": "[预览版] ",
  "baseline_app": "fnmusic-ext" }
```

- `channel`：`stable`（默认，只收正式版）/ `prerelease`（只收预发布）/ `all`。
- `keep_versions` 可以写在 variant 上覆盖顶层值（预览版迭代快、留 3 个够了）。
- `changelog_prefix`：给每个版本的 changelog 加固定前缀。
- `baseline_app`：指向另一个条目，同步时**自动把两者的版本关系写进 desc**
  （基线是哪个版本、上游已有几个预发布迭代在其之后），避免用户面对两条目不知道谁更新。

预发布版本节点会额外记一个 `upstream_tag`（值如 `v2.11.0d`）：因为版本键取的是包内
manifest（`2.11.0-3`），与 tag 对不上，靠版本键判断「收过没有」会重复收录，得认 tag。

同步脚本的几条行为约定：

- **资产没传完的 Release 会跳过，等下一轮再试**。上游确实存在「`.sha256` 已上传、
  `.fpk` 还没传完」的中间态（v0.2.22 就撞上了），写进源会让客户端点到下载不到的包。
- **与上游同名 `.sha256` 交叉校验**，算出来的哈希对不上就跳过并报警，不收疑似传坏的包。
- **版本键取包内 manifest 的 `version`**，不取 Release tag（两者经常不是同一个数）。
- **裁剪到 `keep_versions`**：V2 规范单应用上限 100 个版本，上游这个发版速度几十天就撑爆。
- **版本号排序按 SEMVER**：带 `-N` 预发布后缀的版本**小于**对应的正式版（`2.11.0-3 < 2.11.0`）。
  早期实现把 `-` 当普通分隔符，会得出预发布反而更新的结论，与规范相反，已修正。
- **已收录的版本节点不改写**，同步只做追加与裁剪。
- 头部元数据分两类：`display_name`/`desc`/`maintainer` 每次跟包内 manifest 刷新
  （作者改描述能自动跟上）；`platform`/`categories`/`icon_url` 等本源自定的字段只在
  缺失时补，不会被上游冲掉。

手工触发：Actions → **Sync upstream FPK** → Run workflow，可勾 `dry_run` 只看不动。

> ⚠️ GitHub 会在仓库**连续 60 天无任何活动**后自动停用 `schedule` 触发器。
> 哪天发现不再自动更新了，先确认是不是这个原因（推个提交即可恢复）。
> 另外 cron 只是「大约」每 6 小时，拥堵时会延迟，不是准点调度。

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
- `manifest` 的 `platform` **只能填一个值**；要同时支持 x86 与 arm 必须分别打两个包
  （`platform=all` 只在**产物本身与架构无关**时可用，例如 Docker 应用跑多架构官方镜像）。
- 已发布的「版本号 + 架构」FPK 视为**不可变**，改内容必须发新版本号或新地址。
- **多个应用共用一个 tag**：CI 会把 tag 版本号 `sed` 进每个被构建应用的 `manifest`，
  所以「应用版本号」与「仓库 tag」是绑定的。Docker 应用若还要跟随上游镜像版本，
  `manifest` 的 `version` 与 compose 里的镜像 tag **必须一起改**，否则会打出
  「版本号变了、跑的还是旧镜像」的包。（引用上游 FPK 的应用不受此约束，见上节。）
- Docker 应用的 compose 里写死的宿主机路径（如 data-share 挂载点）与
  `cmd/install_callback` 写入文件的路径**必须逐字一致**。不要一个写死、一个从
  `TRIM_APPDEST` 反推 —— 两边不一致时症状是「凭据被悄悄忽略」（容器退回到自动生成
  随机密码），而且从日志上完全看不出来。
- `source_info.author`(源维护者) / `maintainer`(开发者) / `distributor`(发布者) 三者职责不同，不要混用。
