# 收录前的安全审查规则

这份文档管的是「**一个应用能不能进这个源**」，以及进来了要怎么标注。

**不管合规与版权**（那是用的人自己的事）。只管三件事：

1. **对飞牛系统的影响** —— 是不是动了我的系统、我的官方服务、我的数据；
2. **有没有后门** —— 有没有偷偷的远程控制、常驻后台、可疑外联；
3. **有没有明显的漏洞与供应链风险** —— 关 TLS 校验、硬编码凭据、无锁定的联网装包。

配套的自动扫描脚本是 `scripts/audit_risk.py`。**脚本负责摆事实，人负责下结论**——
脚本给的是「建议放行 / 需人工确认 / 建议拒绝」三选一，最终是否收录由维护者拍板。

---

## 一、默认要求（准入门槛）

新应用进源的默认要求是：

| 项 | 默认要求 |
|---|---|
| 运行环境 | **必须有独立环境** —— Docker 容器或虚拟机，不得直接跑在飞牛系统上 |
| 运行身份 | **不得是 root**（`config/privilege` 的 `run-as` 应为 `package`） |
| 系统改动 | **不得改系统配置**：不装 systemd 服务、不改 `/etc`、不动官方服务 |
| 飞牛 API | 不申请额外权限；确需申请时必须在描述里写明申请了哪一项 |
| 网络 | 外联目标要能说清楚是什么；不得出现无法解释的域名 |

**不满足的应用不是不能收，而是必须先扫描、明确告知、由维护者手动放行，并在下方
「例外放行清单」里登记。** 走到这一步的应用，其应用描述里必须带统一格式的
「权限与影响」段（见第三节）。

已知的例外情况：**接管飞牛官方服务的应用不可能隔离**——它们天生就要操作宿主机上的
`/var/run/*.sock` 和 systemd，塞进容器就干不了活。这类应用一律走例外流程。

---

## 二、检查项清单

与 `scripts/audit_risk.py` 里的规则编号一一对应。

### A. 隔离与身份

| 编号 | 严重度 | 检查项 |
|---|---|---|
| A1 | HIGH | `run-as: root` |
| A2 | **CRITICAL** | 挂载或访问 `docker.sock`（等价于宿主机 root） |
| A3 | HIGH | 容器特权模式 `privileged: true` |
| A4 | MEDIUM | 容器 host 网络模式 |
| A5 | MEDIUM | 申请了飞牛系统 API 权限（需核对具体项） |
| A6 | MEDIUM | 共享宿主机 PID / IPC 命名空间 |

### B. 对飞牛系统的影响

| 编号 | 严重度 | 检查项 |
|---|---|---|
| B1 | HIGH | 安装/操作 `/etc/systemd/system/` 下的系统服务 |
| B2 | HIGH | 操作 `/var/run/*.sock`（通常是接管官方服务） |
| B3 | HIGH | 改名/替换官方 socket（官方流量被劫持） |
| B4 | HIGH | 写 SSH `authorized_keys` |
| B5 | MEDIUM | 设置定时任务（持久化驻留） |
| B6 | MEDIUM | 改 iptables / 内核参数 |
| B7 | MEDIUM | 改系统或官方服务配置 |
| B8 | MEDIUM | 写入系统可执行目录 |
| B9 | LOW | 其它读写系统目录的行为 |

### C. 后门与木马特征

| 编号 | 严重度 | 检查项 |
|---|---|---|
| C1 | **CRITICAL** | 远程下载后直接管道执行（`curl … \| sh`） |
| C2 | **CRITICAL** | 反向 shell 特征（`/dev/tcp/`、`bash -i`、`mkfifo` + `nc`） |
| C3 | **CRITICAL** | base64 混淆后执行 |
| C4 | HIGH | 建立网络 socket 后执行系统命令、`pty.spawn` |
| C5 | MEDIUM | `eval` / `exec` / `os.system` 动态执行 |
| C6 | MEDIUM | 以 shell 方式执行外部命令（命令注入面） |
| C7 | MEDIUM | `chmod 777`、setuid 提权位 |

### D. 漏洞与工程质量

| 编号 | 严重度 | 检查项 |
|---|---|---|
| D1 | HIGH | 关闭 TLS 证书校验（`verify=False`） |
| D2 | HIGH | 疑似硬编码密钥 / 令牌 |
| D3 | MEDIUM | 联网装依赖但未锁版本 |
| D4 | MEDIUM | 硬编码凭据 |
| D5 | LOW | CORS 全开 |
| D6 | LOW | 调试模式、过宽监听 |

### E. 供应链

| 编号 | 严重度 | 检查项 |
|---|---|---|
| E1 | MEDIUM | 运行时下载并安装自身包（自更新供应链面） |
| E2 | INFO | 包内含 sha256 锁定值（**正面信号**） |

### 判定标准

- 命中任一 **CRITICAL** → **建议拒绝**（除非能确认是误报，且把结论写在放行登记里）；
- 命中 **HIGH**，或「root + 无容器隔离」→ **需人工确认**；
- 只有 MEDIUM 及以下 → **需人工确认**（快速核对后可放行）；
- 全部未命中 → **建议放行**。

---

## 三、统一「权限与影响」段

**每一个应用的描述里都必须带这一段**，让用户在点安装之前就看到。

格式（放在 `desc` 末尾）：

```
【权限与影响】
· 运行环境：Docker 容器隔离，以非 root 专用用户（docker-xxx）运行；无特权模式、不挂 docker.sock
· 系统改动：无 —— 不装 systemd 服务、不改系统配置、不接管或替换飞牛官方服务
· 飞牛 API：未申请
· 占用端口：1 个（由应用中心分配）
· 读写数据：仅自己的数据卷 /var/apps/xxx/shares/data
· 网络行为：<说清楚访问谁、为什么>
```

- **本地工程**（`packages/`）：直接写在 `apps/<appid>.json` 的 `desc` 里。
- **引用上游 FPK 的应用**：必须写在 `upstream/<name>.json` 的 `permission_note` 里，
  由同步脚本注入 `desc`。**直接手改 `apps/*.json` 会被下一轮同步冲掉**——因为 desc
  每次同步都跟着包内 manifest 刷新。

### 安装前的强制确认（wizard）

我们自己打包的应用（`packages/` 下有工程的），`wizard/install` 里带一个
**`required: true` 的勾选框**：不勾选就装不下去。这保证了「**装成功的，一定是同意过
权限条件的**」。

引用上游 FPK 的应用**改不了包**，因此做不到这一层，只能靠描述层标注——这也是把它们
单独列出来的原因之一。

---

## 四、流程

```
要接一个新应用（或上游发了新版本）
        │
        ▼
  ① 跑扫描：python3 scripts/audit_risk.py --fpk <包>    （本地/新应用）
            python3 scripts/audit_risk.py --app <appid>  （已在源里的）
        │
        ▼
  ② 看报告：结论 + 命中项 + 外联域名
        │
        ▼
  ③ 维护者决策：放行 / 拒绝 / 放行但标注例外
        │
        ▼
  ④ 登记：写进下方「例外放行清单」（若属例外），描述里补齐权限段
        │
        ▼
  ⑤ 收录
```

CI 会自动跑扫描并留档报告（`risk-audit.yml`），但**不会自动拒绝**——结论永远交给人。

---

## 五、例外放行清单

不满足第一节默认要求、但经维护者确认放行的应用。登记在这里，便于复查。

| 应用 | 违反的默认要求 | 扫描结论 | 放行时间与理由 |
|---|---|---|---|
| `fnmedia-ext` | root + 无容器隔离；装 systemd 服务；改名接管官方影视 socket | 需人工确认（HIGH×N） | 2026-10-29 维护者确认放行。功能本质要求接管宿主机 socket，无法容器化。 |
| `fnmedia-ext-full` | 同上，另会拉起 Android 容器跑爬虫 | 需人工确认（HIGH×N） | 2026-10-29 同上 |
| `fnmusic-ext` | root + 无容器隔离；装 systemd 服务；接管官方音乐 socket；申请 `trim.file.userAccess` | 需人工确认（HIGH×N） | 2026-10-29 维护者确认放行。同上，且工程质量优于 fnmedia（0 处 `verify=False`、有 `SECURITY.md`、产物带 sha256 锁定）。 |
| `fnmusic-ext-preview` | 同上（且是上游预发布版） | 需人工确认 | 2026-10-29 同上 |

这 4 个的描述里都带了权限段，且明确写了「⚠ 本应用不满足『独立运行环境』要求」。

---

## 六、扫描脚本用法

```bash
python3 scripts/audit_risk.py                    # 扫全部（本地工程 + 源内每个应用的最新包）
python3 scripts/audit_risk.py --pkg iptv         # 只扫某个本地工程
python3 scripts/audit_risk.py --app fnmusic-ext  # 只扫某个应用（会下载其最新包）
python3 scripts/audit_risk.py --fpk ./x.fpk      # 扫单枚包
python3 scripts/audit_risk.py --json             # JSON 输出（CI 用）
python3 scripts/audit_risk.py --offline          # 不下载，只用缓存
```

- 下载的包缓存在 `.workbuddy/cache/audit/`（已被 git 忽略），重复扫不会重复下载。
- **退出码**：0 = 无 HIGH/CRITICAL；1 = 有 HIGH；2 = 有 CRITICAL。
  CI 里用 `continue-on-error` 收报告，不拿它卡流程。

---

## 七、已知误报与规则边界

写在这里，免得下次对着报告怀疑人生。

- **注释与文档不算行为**。作者写「不挂 docker.sock」时，关键词照样命中——脚本会抹掉
  整行注释，并对「否定语境」（不挂/不做/not/never…）降级为 INFO。
- **`os.dup2(2, 1)` 不是后门**，是把 stderr 并到 stdout 的常规日志写法。规则已只保留
  `pty.spawn` 这类强特征。
- **`socket.socket(AF_UNIX)` 不是后门**，连本地 socket 是正常操作（接管官方服务就是这么
  做的）。规则只针对 `AF_INET` + 执行系统命令的组合。
- **shebang 不是「写 /bin」**。`#!/bin/bash` 会被路径类规则命中，已抹掉。
- **必须递归解包中包**。fnmedia 把全部 Python 代码塞在 `app.tgz` 里，只扫 FPK 顶层的话
  真正的业务逻辑一行都看不到，`verify=False` 之类会全部漏掉。
- **第三方依赖目录要跳过**（`node_modules/`、`site-packages/` 等），否则「外联域名」会
  被依赖的 README 和注释灌满，真正的通信目标反而看不见。
- **脚本只能看静态特征**。加密/混淆的载荷、只在运行时才下载的代码、需要真机跑起来才
  暴露的行为，脚本扫不出来。这也是结论必须交给人看的原因。
