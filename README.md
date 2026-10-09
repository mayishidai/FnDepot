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
> ⚠️ 反代是**按路径前缀改写**的，因此只适用于资源/接口地址用相对路径的应用。
> 若某个应用的仪表盘把地址写死成根路径（前端的 `BASE_URL` 为空、WebSocket 直接拼
> `window.location.host + /api/...`），挂在 `/p/<id>/` 下必然 404，这类应用要打开
> **独立端口直连**（见下）。

### 内置应用（预置清单）

`src/dev-hub/server/catalog.py` 里维护了一份预置清单，面板启动时会自动补进配置，
**开箱即有卡片，不用手工录入**：

| 应用 ID | 仓库 | 分支 | 端口 | 说明 |
|---|---|---|---|---|
| `ai-video-studio` | AIVideoStudio | `master` | 19101 | AI 视频工作台。只认 loopback 监听，故启动命令**不加** `--host` |
| `fund` | fund | `main` | 19102 | 韭菜盒子。依赖含 akshare + pandas，首次启动装得比较久 |
| `mini-games` | mini_games | `main` | 19103 | 用 esbuild 打包 `games/sheep` 并托管 H5 |
| `mini-games-api` | mini_games | `main` | 19104 | 羊了个羊后端（Node 内置 sqlite） |
| `ai-image-studio` | AIImageStudio | `main` | 19105 | 仓库尚无提交，预置为**待启用**占位 |
| `octop` | Octop | `main` | 19106 | 腾讯 Octop 多智能体助手。**独立端口直连**，首次启动现场构建前端 + 装 243 个锁包 |

播种规则：**只补缺、不覆盖**——已存在的条目（含你改过的字段）一律不动；
在面板里删掉某个内置条目会记进 `config.removed`，之后不再自动补回。
旧版本留下的配置在加载时会被补齐新字段（例如 `expose_port`），端口不会被改动。

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
预置的 `ai-image-studio` 就是这种状态——等仓库有代码了，编辑卡片填上启动命令并勾选启用即可。

### 添加一个应用

在面板里点「＋ 添加应用」，填写：

| 字段 | 说明 |
|---|---|
| 应用 ID | 唯一标识，同时作为目录名与访问路径 `/p/<id>/` |
| GitHub 仓库地址 | `https://github.com/<你>/<repo>.git` |
| 分支 | 默认 `main`；注意部分仓库默认分支是 `master` |
| 应用端口 | 容器内监听端口，留空自动从 19100 起分配；手填冲突会直接报错 |
| 启动命令 | 在工作目录下执行，`{port}` 会被替换成实际端口 |
| 安装/构建命令 | 可选。**首次启动时自动执行**，更新代码后也会重跑 |
| 子目录 | 可选，仓库内相对路径（单仓多应用时用） |
| 环境变量 | 每行 `KEY=VALUE`，会注入子进程 |
| 独立端口直连 | 勾选框。应用的仪表盘写死根路径、挂不住 `/p/<id>/` 时勾上（见上文） |

**依赖是首次启动时装的**：点了「启动」之后，面板会先在后台跑安装命令
（卡片显示「安装依赖中」，日志可实时看进度），装完再自动拉起进程。
安装在应用目录内建独立 venv，因此不会和面板自己的依赖打架；
结果落在 `state.json`，面板重启不会重复安装。安装失败时卡片标红，
修好后点「重装依赖」再试，或用「更新代码」连带重装。

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
