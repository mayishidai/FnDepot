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
├── assets/
│   └── icons/<appid>.png       # 应用图标
├── scripts/
│   ├── new-app.sh              # 多应用脚手架（一键生成详情 + FPK 工程 + 图标并写回索引）
│   ├── update_release_meta.py  # 发布时回填 download_url / sha256 / size（CI 调用）
│   └── verify_source.py        # 按 FnDepot V2 规范做发布前检查（--remote 校验实链）
└── .github/workflows/
    └── release-fpk.yml         # 发布 CI：打 v* tag 自动构建/回填/校验/发 Release
```

> ⚠️ **仓库名必须恰为 `FnDepot`**（大小写敏感）—— 这是 FnDepot 客户端识别 GitHub 源的唯一信标。
> 仓库曾用名 `fnos-app-depot`，改名后旧地址依赖 GitHub 的 301 跳转才能生效；
> 因此**所有 URL 已统一改为 `FnDepot`**，且图标改用仓库相对路径，避免再次改名后失效。

## 已收录应用

| 应用 | 分类 | 说明 |
|---|---|---|
| Agnes AI Studio | AI赋能 | 文生图 / 图生图 / 文生视频 / 图文生视频，调用 Agnes AI 免费模型 |

## GitHub 用户名

仓库内镜像地址（`ghcr.io/mayishidai/...`）使用 GitHub 用户名 `mayishidai`（与 `fnpack.json` 的 `source_info.author` 一致）。若你 fork 到自己的账号发布，全局替换即可：

```bash
find . -type f \( -name '*.json' -o -name '*.yml' -o -name '*.sh' \) -exec sed -i 's/mayishidai/你的用户名/g' {} +
```

> 脚手架脚本 `scripts/new-app.sh` 会从 `source_info.author` 自动读取此用户名，无需手改模板。

## 发布应用（CI 自动化流程）

1. **发布 Docker 镜像**：应用主仓库 push 到 `main` 自动构建并推送 `ghcr.io/<user>/<appid>:latest`。
2. **准备源文件**：确保 `apps/<appid>.json` 与 `packages/<appid>/`（fnpack 工程）齐全。
3. **本地预检**：`python3 scripts/verify_source.py`。
4. **打 tag 触发发布**：
   ```bash
   git tag v1.0.0 && git push origin v1.0.0
   ```
   CI 自动完成：构建 FPK → 计算 sha256/size → 回填 `apps/<appid>.json` → 规范校验 → 提交元数据 → 发 GitHub Release。

> CI 会自动发现 `packages/` 下**全部**应用，新增应用无需改 workflow。
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
