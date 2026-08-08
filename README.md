# FnOS 应用渠道包仓库（FnDepot 兼容）

本仓库集中存放面向 **飞牛 fnOS** 的第三方应用渠道包，供用户在飞牛「应用中心 → 外部应用源」中添加使用。
格式遵循 [FnDepot](https://github.com/EWEDLCM/FnDepot) 的 V2 规范（GitHub 仓库即一个外部源）。

> 飞牛第三方源为去中心化机制：用户自行添加本仓库地址即可，无需官方审核。

## 目录结构

```
fnos-app-depot/
├── fnpack.json                 # 主索引（source_info + apps 引用，多应用都在此登记）
├── apps/
│   └── <appid>.json             # 各应用详情（拆分模式），按需新增
├── app_<appid>.yml              # 飞牛 FPK 清单模板（fnpack 输入）
├── docker-compose.<appid>.yml   # 手动 docker-compose 部署用
├── scripts/
│   └── new-app.sh               # 多应用脚手架（一键生成上述文件并写回索引）
├── assets/
│   └── icons/                   # 应用图标（<appid>.png）
└── README.md
```

## 已收录应用

| 应用 | 分类 | 说明 |
|---|---|---|
| Agnes AI Studio | AI赋能 | 文生图 / 图生图 / 文生视频 / 图文生视频，调用 Agnes AI 免费模型 |

##  GitHub 用户名

仓库内 `icon_url`、镜像地址（`ghcr.io/mayishidai/...`）、下载地址均使用 GitHub 用户名 `mayishidai`（与 `fnpack.json` 的 `source_info.author` 一致）。若你 fork 到自己的账号发布，全局替换即可：

```bash
find . -type f \( -name '*.json' -o -name '*.yml' \) -exec sed -i 's/mayishidai/你的用户名/g' {} +
```

> 脚手架脚本 `scripts/new-app.sh` 会从 `source_info.author` 自动读取此用户名，无需手改模板。

## 发布 Agnes AI Studio 渠道包（完整流程）

### 1. 发布 Docker 镜像
Agnes AI Studio 主仓库已含 `.github/workflows/docker-build.yml`，push 到 `master`/`main` 会自动构建并推送镜像到 `ghcr.io/mayishidai/agnes-ai-studio:latest`。
只需在主仓库 Settings → Secrets 确保 `GITHUB_TOKEN` 有 `packages: write` 权限（默认有）。

### 2. 准备图标
将 `agnes-ai-studio.png`（512×512，PNG/WebP，<500KB）放入 `assets/icons/`。

### 3. 构建 FPK 安装包
在装有飞牛 `fnpack` 工具的机器上：
```bash
fnpack build app_agnes_ai_studio.yml
# 生成 agnes-ai-studio.fpk
```

### 4. 上传 Release
在本仓库创建 GitHub Release（建议 tag `v1.0.0`），上传 `agnes-ai-studio.fpk`。
记录其下载地址、sha256、size（字节）。

### 5. 回填配置
更新 `apps/agnes-ai-studio.json` 的 `releases`：
```json
"releases": {
  "1.0.0": {
    "packages": {
      "all": {
        "download_url": "https://github.com/mayishidai/fnos-app-depot/releases/download/v1.0.0/agnes-ai-studio.fpk",
        "sha256": "<实际sha256>",
        "size": <实际字节数>
      }
    }
  }
}
```

### 6. 提交并 push 本仓库

## 飞牛用户如何使用

1. 飞牛 fnOS → 应用中心 → 设置 → 外部应用源
2. 添加源，填写本仓库地址：`https://github.com/mayishidai/fnos-app-depot`
3. 应用中心即可看到 Agnes AI Studio，点击安装
4. 安装后在浏览器打开（默认端口 5000），在设置页填入 Agnes AI API Key 即可使用

## 扩展更多应用

推荐用脚手架一键生成（免去手写多个文件与维护索引）：

```bash
./scripts/new-app.sh <appid> <display_name> <category> [port] [platform]
# 例：./scripts/new-app.sh comfyui "ComfyUI" "AI赋能" 8188 "x86,arm"
```

脚本会自动校验 appid 与分类、生成 `apps/<id>.json`、`app_<id>.yml`、`docker-compose.<id>.yml`、占位图标，并写回 `fnpack.json` 索引（GitHub 用户名从 `source_info.author` 自动读取）。

也可完全手动新增一个应用：

1. 在 `fnpack.json` 的 `apps` 中加一个键：
   ```json
   "my-new-app": { "details_url": "apps/my-new-app.json", "details_updated_at": "2026-08-08T22:00:00+08:00" }
   ```
2. 新建 `apps/my-new-app.json`（必填字段同 Agnes，见 FnDepot V2 规范）
3. 如需 FPK，新增 `app_my_new_app.yml` 模板
4. 提交即可

分类九选一：`影音娱乐、系统工具、编程开发、AI赋能、生活服务、智能智控、教育学习、游戏地带、硬件驱动`。
