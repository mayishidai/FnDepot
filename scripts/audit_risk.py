#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_risk.py — 收录前 / 同步后的风险扫描。

关注三类问题（合规与版权不管）：

- **对飞牛系统的影响**：是不是 root 跑、有没有隔离、往 `/etc` `/var/run` 写了什么、
  有没有接管官方服务、申请了哪些飞牛 API 权限。
- **后门与木马特征**：反向 shell、远程代码管道执行、混淆执行、可疑外联。
- **漏洞与工程质量**：关 TLS 校验、硬编码凭据、无锁定的联网装包、自更新供应链面。

能扫三种目标：

1. `packages/<id>/` —— 本仓库自己的 FPK 工程（未打包）
2. 一枚 `.fpk`（本地路径或 URL）—— FPK 就是 tar.gz，直接内存解包
3. `--app <appid>` —— 取 `apps/<appid>.json` 里最新版本的外链包下来扫

用法:
    python3 scripts/audit_risk.py                    # 扫仓库全部应用
    python3 scripts/audit_risk.py --pkg iptv         # 只扫某个本地工程
    python3 scripts/audit_risk.py --app fnmusic-ext  # 只扫某个应用（含外链包）
    python3 scripts/audit_risk.py --fpk ./x.fpk      # 扫单枚包
    python3 scripts/audit_risk.py --json             # 机器可读输出（CI 用）
    python3 scripts/audit_risk.py --offline          # 不下载外链包，只扫本地与缓存

退出码: 0 = 无 CRITICAL/HIGH；1 = 存在 HIGH；2 = 存在 CRITICAL。
（把「建议」交给人决策，脚本只负责把事实摆出来。）

依赖: 仅 Python 标准库。
"""

import argparse
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "apps"
PACKAGES_DIR = ROOT / "packages"
CACHE_DIR = ROOT / ".workbuddy" / "cache" / "audit"

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# 文本文件的扩展名；其余按二进制处理（只记大小，不扫内容）
TEXT_EXT = {
    ".sh", ".bash", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".conf", ".cfg", ".service", ".md", ".txt", ".pl", ".rb",
    ".php", ".go", ".rs", ".java", ".lua", "",
}
# 扫描内容时跳过大文件：一个 20MB 的编译产物逐行正则会拖到几十秒
MAX_TEXT_SCAN = 2 * 1024 * 1024

# ------------------------------------------------------------------ 检查规则
# (编号, 严重度, 分组, 正则, 说明)
RULES = [
    # ---- A. 隔离与身份
    ("A1", "HIGH", "隔离", r"^\s*\"run-as\"\s*:\s*\"root\"", "以 root 身份运行（无隔离的超级用户）"),
    ("A2", "CRITICAL", "隔离", r"docker\.sock", "挂载/访问 docker.sock —— 等价于宿主机 root"),
    ("A3", "HIGH", "隔离", r"privileged\s*:\s*true|--privileged", "容器特权模式（可逃逸到宿主机）"),
    ("A4", "MEDIUM", "隔离", r"network_mode\s*:\s*[\"']?host", "容器 host 网络模式（共享宿主机网络栈）"),
    ("A5", "MEDIUM", "隔离", r"\"api-scope\"\s*:\s*\[[^\]]+\]", "申请了飞牛系统 API 权限（需核对具体项）"),
    ("A6", "MEDIUM", "隔离", r"pid:\s*host|ipc:\s*host", "共享宿主机 PID/IPC 命名空间"),

    # ---- B. 对飞牛系统的影响
    ("B1", "HIGH", "系统", r"/etc/systemd/system/|systemctl\s+(enable|start|daemon-reload|stop|disable)",
     "安装/操作系统级 systemd 服务（开机自启、常驻后台）"),
    ("B2", "HIGH", "系统", r"/var/run/[\w.-]+\.sock|/run/[\w.-]+\.sock", "操作 /var/run 下的 socket（通常是接管官方服务）"),
    ("B3", "HIGH", "系统", r"mv\s+[\"']?/var/run/|rename.*\.sock|\.sock\.bak|mv\s+.*\.sock\s+.*_upstream",
     "改名/替换官方 socket（官方服务流量被劫持）"),
    ("B4", "HIGH", "系统", r"authorized_keys|/root/\.ssh", "写 SSH authorized_keys（可直接登录）"),
    ("B5", "MEDIUM", "系统", r"crontab|/etc/cron\.|systemd\.timer", "设置定时任务（持久化驻留）"),
    ("B6", "MEDIUM", "系统", r"iptables|nftables|sysctl\s+-w|/proc/sys/", "改动网络/内核参数"),
    ("B7", "MEDIUM", "系统", r"/etc/nginx|nginx\.conf|/usr/trim|/etc/.*\.conf", "改动系统或官方服务配置"),
    ("B8", "MEDIUM", "系统", r"/usr/bin/|/usr/local/bin/|/bin/|/sbin/", "写入系统可执行目录"),
    ("B9", "LOW", "系统", r"/etc/|/var/lib/", "读写系统目录（需确认范围）"),

    # ---- C. 后门与木马特征
    ("C1", "CRITICAL", "后门", r"curl\s+[^\n|]*\|\s*(sudo\s+)?(ba)?sh|wget\s+[^\n|]*-O\s*-\s*\|\s*(ba)?sh|wget\s+[^\n|]*\|\s*sh",
     "远程下载后直接管道执行（无校验地执行远端代码）"),
    ("C2", "CRITICAL", "后门", r"/dev/tcp/|nc\s+[\w.]+\s+\d+\s+-e|bash\s+-i\s+>&|mkfifo\s+.*\s+&&\s+nc",
     "反向 shell 特征（可被远程控制）"),
    ("C3", "CRITICAL", "后门", r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh|eval\s*\(\s*[\"']?[A-Za-z0-9+/=]{40,}",
     "base64 混淆后执行（隐藏真实行为）"),
    # 只针对 AF_INET：AF_UNIX 是连本地 socket 的正常写法（fnmedia 就是这么接管
    # 官方服务的），照旧规则会把「连接」当成「后门」。pty.spawn / os.dup2 例外，
    # 这两个本身就有强后门特征。
    # 只保留 pty.spawn（强后门特征）与 AF_INET+执行 的组合。原来单列 os.dup2，
    # 结果 `os.dup2(2, 1)`（把 stderr 并到 stdout 的常规日志写法）也被判成后门。
    ("C4", "HIGH", "后门",
     r"socket\.socket\s*\(\s*socket\.AF_INET[\s\S]{0,400}?(subprocess|os\.system|pty\.spawn|exec\s*\(|eval\s*\()|pty\.spawn",
     "建立网络 socket 后执行系统命令（交互式后门特征）"),
    ("C5", "MEDIUM", "后门", r"\beval\s*\(|\bexec\s*\(|os\.system\s*\(|Function\s*\(\s*[\"'`]",
     "动态执行代码（需确认输入来源是否可控）"),
    ("C6", "MEDIUM", "后门", r"subprocess[^\n]*shell\s*=\s*True|child_process[^\n]*exec\s*\(",
     "以 shell 方式执行外部命令（有命令注入面）"),
    ("C7", "MEDIUM", "后门", r"chmod\s+777|chmod\s+\+s|setuid", "过宽权限或提权位"),

    # ---- D. 漏洞与工程质量
    ("D1", "HIGH", "漏洞", r"verify\s*=\s*False|check_hostname\s*=\s*False|InsecureRequestWarning",
     "关闭 TLS 证书校验（可被中间人）"),
    ("D2", "HIGH", "漏洞", r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})",
     "疑似硬编码密钥/令牌"),
    ("D3", "MEDIUM", "漏洞", r"pip\s+install[^\n]*(?<!==)\s(?!-)[a-z0-9_.-]+\s*$",
     "联网安装依赖且未锁版本（供应链风险）"),
    ("D4", "MEDIUM", "漏洞", r"(password|passwd|secret|token|api_key)\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']",
     "硬编码凭据"),
    ("D5", "LOW", "漏洞", r"allow_origins\s*=\s*\[\s*[\"']\*", "CORS 全开"),
    ("D6", "LOW", "漏洞", r"debug\s*=\s*True|--insecure|0\.0\.0\.0/0", "调试模式或过宽监听"),

    # ---- E. 供应链
    ("E1", "MEDIUM", "供应链", r"releases/download[^\n]*\.(fpk|tar|zip|sh)|\.fpk\s*\|\s*(ba)?sh",
     "运行时下载并安装包（自更新供应链面）"),
    ("E2", "INFO", "供应链", r"[0-9a-f]{64}", "包内含 sha256 锁定值（完整性校验，正面信号）"),
]

# 外联域名白名单：这些是常见基础设施，出现在依赖/镜像地址里属正常
KNOWN_HOSTS = {
    "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
    "api.github.com", "gitee.com", "ghcr.io", "docker.io", "registry-1.docker.io",
    "pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "npmjs.com",
    "nodejs.org", "python.org", "debian.org", "ubuntu.com", "alpinelinux.org",
    "localhost", "127.0.0.1",
}

HOST_RE = re.compile(r"https?://([a-zA-Z0-9._-]+)")
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


# ------------------------------------------------------------------ 目标加载

def iter_dir_files(base: Path):
    """遍历目录下的文件，yield (相对路径, 字节内容)。"""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__"}]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                # 统一成正斜杠：Windows 下 os.walk 给出的是反斜杠，会让
                # meta_from_files 里按 "config/privilege" 找文件的逻辑全部落空。
                yield str(p.relative_to(base)).replace(os.sep, "/"), p.read_bytes()
            except OSError:
                continue


def iter_tar_files(blob: bytes):
    """解 FPK（tar.gz），yield (包内相对路径, 字节内容)。"""
    try:
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for m in tar.getmembers():
                if not (m.isfile() or m.islnk()):
                    continue
                try:
                    f = tar.extractfile(m)
                except (tarfile.TarError, OSError):
                    continue
                if f is None:
                    continue
                yield m.name.lstrip("./"), f.read()
    except tarfile.TarError as exc:
        raise RuntimeError(f"解包失败（不是合法的 tar.gz？）：{exc}") from exc


def download(url: str, cache_name: str | None, offline: bool) -> bytes:
    """下载外链包，带本地缓存（28MB 的包，重复扫很费时）。"""
    if cache_name:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp = CACHE_DIR / cache_name
        if cp.is_file():
            return cp.read_bytes()
        if offline:
            raise RuntimeError(f"离线模式且无缓存：{cache_name}")
    req = urllib.request.Request(url, headers={"User-Agent": "FnDepot-risk-audit/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        blob = resp.read()
    if cache_name:
        (CACHE_DIR / cache_name).write_bytes(blob)
    return blob


# ------------------------------------------------------------------ 元信息

# 解压炸弹防护：累计解压上限与文件数上限
MAX_EXPAND_BYTES = 300 * 1024 * 1024
MAX_EXPAND_FILES = 30000


def try_expand(blob: bytes):
    """把归档内容解出来；不是归档或解不开则返回 None。

    必须递归解：fnmedia-ext 把全部 Python 代码塞在 `app.tgz` 里（包中包），
    只扫 FPK 顶层的话，真正的业务逻辑一行都看不到 —— `verify=False` 这类
    代码级特征会全部漏掉，扫描器等于没扫。
    """
    if blob[:2] == b"\x1f\x8b":          # gzip：可能是 .tar.gz 也可能是纯 gzip
        try:
            out = {}
            with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
                for m in tar.getmembers():
                    if not (m.isfile() or m.islnk()):
                        continue
                    f = tar.extractfile(m)
                    if f is not None:
                        out[m.name.lstrip("./")] = f.read()
            return out or None
        except (tarfile.TarError, OSError, EOFError):
            return None
    if blob[:2] == b"PK":                # zip / whl / jar / apk
        try:
            out = {}
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    out[info.filename] = zf.read(info)
            return out or None
        except (zipfile.BadZipFile, OSError, EOFError):
            return None
    return None


def expand_nested(files: dict, max_depth: int = 3) -> dict:
    """递归展开包中包，子路径用 `父名!子路径` 标记，便于定位来源。"""
    out = dict(files)
    frontier = dict(files)
    total = sum(len(b) for b in out.values())
    depth = 0
    while frontier and depth < max_depth and total < MAX_EXPAND_BYTES:
        nxt: dict = {}
        for name, blob in frontier.items():
            sub = try_expand(blob)
            if not sub:
                continue
            for k, v in sub.items():
                if total + len(v) > MAX_EXPAND_BYTES or len(out) > MAX_EXPAND_FILES:
                    break
                key = f"{name}!{k}"
                if key not in out:
                    out[key] = v
                    nxt[key] = v
                    total += len(v)
        frontier = nxt
        depth += 1
    return out


def meta_from_files(files: dict) -> dict:
    """从包内文件提取结构性元信息（运行身份、隔离方式、API 权限等）。"""
    def read(name):
        for k, v in files.items():
            if k.lstrip("./") == name:
                return v.decode("utf-8", "replace")
        return ""

    meta = {"run_as": "", "docker": False, "api_scope": [], "shares": [],
            "appname": "", "version": "", "mounts": []}

    mf = read("manifest")
    for k in ("appname", "version"):
        m = re.search(rf"^{k}\s*=\s*(.*)$", mf, re.M)
        if m:
            meta[k] = m.group(1).strip()

    priv = read("config/privilege")
    m = re.search(r"\"run-as\"\s*:\s*\"([^\"]+)\"", priv)
    if m:
        meta["run_as"] = m.group(1)

    res = read("config/resource")
    if "docker-project" in res:
        meta["docker"] = True
    m = re.search(r"\"api-scope\"\s*:\s*\[([^\]]*)\]", res)
    if m:
        meta["api_scope"] = re.findall(r"\"([^\"]+)\"", m.group(1))
    m = re.search(r"\"data-share\"\s*:\s*\{([\s\S]*?)\}", res)
    if m:
        meta["shares"] = re.findall(r"\"name\"\s*:\s*\"([^\"]+)\"", m.group(1))

    for k, v in files.items():
        if k.endswith(("docker-compose.yaml", "docker-compose.yml")):
            text = v.decode("utf-8", "replace")
            meta["mounts"] = re.findall(r"-\s*\"?([^\"\s:]+):", text)
    return meta


def collect_hosts(files: dict) -> dict:
    """统计包内出现的外联域名。"""
    counts: dict = {}
    for name, blob in files.items():
        if Path(name).suffix.lower() not in TEXT_EXT or len(blob) > MAX_TEXT_SCAN:
            continue
        # 与内容扫描一致地跳过依赖目录：否则「外联域名」里几百个条目全来自
        # 第三方依赖的 README 与注释，真正的对外通信目标反而看不见。
        if any(mk in name.replace("\\", "/") for mk in SKIP_PATH_MARKERS):
            continue
        text = blob.decode("utf-8", "replace")
        for h in HOST_RE.findall(text):
            counts[h] = counts.get(h, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ------------------------------------------------------------------ 扫描

# 第三方依赖目录：扫它们只会得到海量噪声（fnmusic 解开后有近 3000 个文件、
# 几百个「外联域名」全来自依赖的 README 和注释），应用自身代码反被淹没。
SKIP_PATH_MARKERS = (
    "node_modules/", "site-packages/", "dist-packages/", "vendor/",
    "__pycache__/", ".venv/", "venv/", "/deps/", "third_party/",
)

# 否定语境：作者写「不挂 docker.sock」「不做容器级操作」这种声明时，关键词照样命中，
# 却被当成真的做了那件事 —— 这是最危险的一类误报（凭空造出一个 CRITICAL）。
NEGATIVE_HINTS = (
    "不挂", "不会", "不使用", "不用", "不做", "不申请", "不改", "不写入",
    "禁止", "无需", "没有", "未使用", "not ", "never", "don't", "does not",
    "no docker", "without",
)


def scan_files(files: dict) -> list:
    """按规则扫描全部文本文件内容。返回 findings 列表。"""
    findings = []
    for name, blob in sorted(files.items()):
        ext = Path(name).suffix.lower()
        if ext not in TEXT_EXT:
            continue
        if len(blob) > MAX_TEXT_SCAN:
            continue
        if any(mk in name.replace("\\", "/") for mk in SKIP_PATH_MARKERS):
            continue
        text = blob.decode("utf-8", "replace")
        # shebang（#!/bin/bash、#!/usr/bin/env python）会被「写入系统目录」类规则
        # 当成真的往 /bin 里写东西。整行抹掉再扫（替换成空行，行号不变）。
        text = re.sub(r"(?m)^#!.*$", "", text)
        # 同理抹掉整行注释（# 或 // 开头），注释里的词不代表代码行为。
        text = re.sub(r"(?m)^\s*(#|//).*$", "", text)

        for code, sev, group, pattern, hint in RULES:
            m = re.search(pattern, text, re.M)
            if not m:
                continue
            line_no = text[: m.start()].count("\n") + 1
            snippet = m.group(0)
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."

            lines = text.splitlines()
            line_text = lines[line_no - 1].lower() if line_no <= len(lines) else ""
            note = ""
            real_sev = sev
            if any(h in line_text for h in NEGATIVE_HINTS):
                real_sev = "INFO"
                note = "（该行像是在声明「不做此事」，按非实际行为处理）"

            findings.append({
                "code": code, "severity": real_sev, "group": group, "hint": hint,
                "file": name, "line": line_no, "match": snippet, "note": note,
            })
    # 同文件同规则只保留第一条，避免刷屏
    seen = set()
    uniq = []
    for f in findings:
        key = (f["file"], f["code"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def verdict(findings: list, meta: dict) -> tuple:
    """给出结论：放行 / 需人工确认 / 建议拒绝。"""
    worst = min((SEV_RANK[f["severity"]] for f in findings), default=len(SEV_RANK))
    root = meta.get("run_as") == "root"
    if "CRITICAL" in [f["severity"] for f in findings]:
        return "建议拒绝", "存在后门/木马级特征", 2
    if not meta.get("docker") and root:
        return "需人工确认", "root 身份且无容器隔离（完全访问宿主机）", 1
    if "HIGH" in [f["severity"] for f in findings]:
        return "需人工确认", "存在高危项（改系统配置 / 关 TLS 校验等）", 1
    if worst <= SEV_RANK["MEDIUM"]:
        return "需人工确认", "存在中低风险项，建议核对后决定", 0
    return "建议放行", "未发现风险特征", 0


def audit(name: str, files: dict) -> dict:
    files = expand_nested(files)          # 先展开包中包，再看内容
    meta = meta_from_files(files)
    findings = scan_files(files)
    hosts = collect_hosts(files)
    unknown_hosts = {h: c for h, c in hosts.items()
                     if h not in KNOWN_HOSTS and not h.endswith((".github.io",))}
    v, reason, rc = verdict(findings, meta)
    return {
        "target": name, "meta": meta, "findings": findings,
        "hosts": hosts, "unknown_hosts": unknown_hosts,
        "verdict": v, "reason": reason, "rc": rc,
        "files": len(files), "bytes": sum(len(b) for b in files.values()),
    }


# ------------------------------------------------------------------ 报告

def print_report(r: dict) -> None:
    m = r["meta"]
    print(f"\n{'=' * 72}")
    print(f"风险扫描：{r['target']}")
    print(f"{'=' * 72}")
    print(f"  应用      : {m.get('appname') or '—'}  版本 {m.get('version') or '—'}")
    print(f"  运行身份  : {m.get('run_as') or '未声明'}"
          + ("  ⚠ root" if m.get("run_as") == "root" else ""))
    print(f"  隔离方式  : {'Docker 容器' if m.get('docker') else '⚠ 无（直接跑在宿主机）'}")
    if m.get("api_scope"):
        print(f"  飞牛 API  : {', '.join(m['api_scope'])}")
    if m.get("shares"):
        print(f"  数据卷    : {', '.join(m['shares'])}")
    print(f"  规模      : {r['files']} 个文件 / {r['bytes']:,} 字节")

    if r["unknown_hosts"]:
        top = list(r["unknown_hosts"].items())[:8]
        print(f"  外联域名  : {len(r['unknown_hosts'])} 个非常见域名，"
              f"出现最多的是 " + ", ".join(f"{h}({c})" for h, c in top))

    if not r["findings"]:
        print("\n  未命中任何风险规则。")
    else:
        print(f"\n  命中 {len(r['findings'])} 项：")
        for f in sorted(r["findings"], key=lambda x: SEV_RANK[x["severity"]]):
            print(f"    [{f['severity']:<8}] {f['code']} {f['hint']}"
                  + (f" {f['note']}" if f.get("note") else ""))
            print(f"               {f['file']}:{f['line']}  →  {f['match']}")

    print(f"\n  结论      : {r['verdict']} —— {r['reason']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描应用对飞牛系统的影响与后门/漏洞特征")
    ap.add_argument("--pkg", help="只扫 packages/<pkg> 本地工程")
    ap.add_argument("--app", help="只扫 apps/<app>.json 对应的应用（外链包会下载）")
    ap.add_argument("--fpk", help="扫单枚 .fpk（本地路径）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（CI 用）")
    ap.add_argument("--offline", action="store_true", help="不下载外链包，只用缓存")
    args = ap.parse_args()

    targets: list = []  # (显示名, {路径: 内容})

    if args.fpk:
        p = Path(args.fpk)
        if not p.is_file():
            print(f"✗ 文件不存在：{p}", file=sys.stderr)
            return 1
        targets.append((p.name, dict(iter_tar_files(p.read_bytes()))))

    elif args.pkg:
        d = PACKAGES_DIR / args.pkg
        if not d.is_dir():
            print(f"✗ 没有这个本地工程：{d}", file=sys.stderr)
            return 1
        targets.append((f"packages/{args.pkg}", dict(iter_dir_files(d))))

    elif args.app:
        targets.extend(load_app_targets([args.app], args.offline))

    else:
        for d in sorted(PACKAGES_DIR.iterdir()):
            if d.is_dir():
                targets.append((f"packages/{d.name}", dict(iter_dir_files(d))))
        appids = sorted(p.stem for p in APPS_DIR.glob("*.json"))
        targets.extend(load_app_targets(appids, args.offline))

    if not targets:
        print("没有可扫的目标。", file=sys.stderr)
        return 1

    results = [audit(n, f) for n, f in targets]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print_report(r)
        print(f"\n{'=' * 72}")
        for r in results:
            flag = {"建议放行": "✓", "需人工确认": "!", "建议拒绝": "✗"}[r["verdict"]]
            print(f"  {flag} {r['target']:<28} {r['verdict']}（{r['reason']}）")
        print(f"{'=' * 72}")

    return max(r["rc"] for r in results)


def load_app_targets(appids: list, offline: bool) -> list:
    """把 apps/<id>.json 指向的最新版本包拉下来扫。"""
    out = []
    for appid in appids:
        path = APPS_DIR / f"{appid}.json"
        if not path.is_file():
            continue
        detail = json.loads(path.read_text(encoding="utf-8"))
        rels = detail.get("releases") or {}
        if not rels:
            continue

        def vkey(v):
            core, _, pre = v.partition("-")
            key = []
            for part in re.split(r"[.\+]", core):
                key.append((0, int(part), "") if part.isdigit() else (1, 0, part))
            key.append((0, 0 if pre else 1, pre))
            return key

        latest = max(rels, key=vkey)
        pkgs = (rels[latest].get("packages") or {})
        arch = sorted(pkgs)[0] if pkgs else None
        if not arch:
            continue
        node = pkgs[arch]
        url = node.get("download_url")
        if not url:
            continue
        cache_name = f"{appid}-{latest}-{arch}.fpk"
        try:
            blob = download(url, cache_name, offline)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {appid}@{latest} 下载失败，跳过：{exc}", file=sys.stderr)
            continue
        try:
            out.append((f"{appid}@{latest}", dict(iter_tar_files(blob))))
        except RuntimeError as exc:
            print(f"  ! {appid}@{latest} 解包失败：{exc}", file=sys.stderr)
    return out


if __name__ == "__main__":
    sys.exit(main())
