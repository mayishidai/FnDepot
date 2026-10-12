# vendored/ —— 面板托管的应用（子仓库）

这里放的是 **Dev Hub 面板里跑的那些应用**的源码，全部以 **git submodule** 形式引入。

## 为什么要有这一层

FnDepot 里混着三种性质不同的代码，之前只靠约定区分，现在在 **git 层面**也分开：

| 层 | 位置 | 归属 |
|---|---|---|
| 面板本身 | `src/dev-hub/` | 我们的代码 |
| **面板托管的应用** | **`vendored/`（本目录）** | **各应用自己的仓库，我们只读不写** |
| 自建镜像应用源码 | `src/<appid>/` | 我们的代码（CI 构建推 GHCR） |

放进子仓库后，这些应用在我们的提交历史里只是一个 **gitlink**（commit 指针），
它们的改动不会混进 FnDepot，也就不会误改别人的项目。

## 三条边界，务必记住

### ① 不参与任何构建

FPK 打包（`packages/`）与面板镜像构建（`src/dev-hub/`）**都不需要**这个目录。

CI 的 `actions/checkout@v4` 默认 `submodules: false`，本来就不拉子模块 ——
**所以 CI 一行都不用改**。千万别为了「让它也拉下来」去加 `submodules: true`，
那只会让构建变慢、并让私有仓库拖垮匿名环境的 CI。

### ② 不是事实来源，版本可能落后

面板在**运行时**自己 `git clone` 到 `/data/apps/<appid>/`，跑的是**各仓库对应分支的最新代码**。

也就是说：

> **子模块钉的 commit ≠ 面板实际在跑的版本。**

子模块只是一份**本地查阅/对照用的快照**。要查「线上到底跑的什么」，
请去各应用自己的仓库看；不要拿这里的 commit 当依据。

需要刷新快照时：

```bash
git submodule update --remote            # 全部跟到各自默认分支的最新 commit
git submodule update --remote vendored/fund   # 只刷新某一个
```

### ③ 里面有私有仓库

`AIVideoStudio` / `fund` / `mini_games` / `AIImageStudio` 是**私有仓库**
（匿名访问 404）。因此：

- 外部匿名 `git clone --recursive` 会在这几个上要求认证并失败 —— 这是预期行为；
- **不影响使用**：飞牛客户端只读 `fnpack.json` / `apps/*.json` / FPK，
  不 clone 本仓库、更不拉子模块；
- 本机与 CI 用设置里配的 `github_token` 访问。

## 当前清单

| 子模块 | 面板里的应用 | 仓库 | 可见性 |
|---|---|---|---|
| `AIVideoStudio` | `ai-video-studio` | mayishidai/AIVideoStudio | 私有 |
| `fund` | `fund`（leekfund） | mayishidai/fund | 私有 |
| `mini_games` | `mini-games` + `mini-games-api` | mayishidai/mini_games | 私有 |
| `AIImageStudio` | `ai-image-studio` | mayishidai/AIImageStudio | 私有 |
| `Octop` | `octop` | TencentCloud/Octop | 公开 |
| `opencut-classic` | `opencut` | OpenCut-app/opencut-classic | 公开 |

均为**浅克隆**（`--depth 1`）：这里只作查阅，不需要完整历史。

面板预置清单的事实来源是 `src/dev-hub/server/catalog.py`，不是这张表 ——
那边新增/删掉应用时，记得同步这里。

> `dramaclaw` 暂未纳入：它是 `enabled: false` 的待启用占位，用户明确「暂不接入」。
