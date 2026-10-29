#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_upstream.py — 把上游仓库已发布的 FPK 同步进本应用源。

用于「作者自己就在发 FPK、我们只做收录和转发」的应用：定时跑一次，查上游有没有新
Release，有就把 download_url / sha256 / size / changelog 写进 apps/<appid>.json。

同步目标由 upstream/<name>.json 描述（一个配置文件可以产出多个应用条目，见
upstream/fnmedia-ext.json：同一个上游同时发「轻量版」与「全功能版」两枚包）。

几个刻意为之的设计，都是踩过或预见到的坑：

1. **上游 Release 存在「.sha256 已传、.fpk 未传完」的中间态**（fnmedia-ext v0.2.22 就
   是这个状态）。所以每枚资产都要逐个确认「真的存在」再收录，否则源里会挂一个下载
   不到的包，客户端点了就报错。缺失时跳过、下一轮再试，而不是写进去。
2. **版本键取 FPK 包内 manifest 的 version，不取 Release tag**。两者可能不一致
   （上游 Octop 就是 tag v1.0.2 / 包内 1.0.300），照抄 tag 会出现「源里显示的版本号
   和安装后应用中心显示的版本号不一样」。
3. **上游若提供同名 .sha256，必须交叉校验**。我们算出来的哈希和上游声明的不一致时
   宁可跳过并报警，也不要把一枚传坏的包写进源。
4. **已收录的版本节点不改写**（已发布元数据不可变），只在字段缺失时补。新增永远只是
   追加。
5. **按版本号裁剪到 keep_versions**。上游一天能发好几个版本，而 V2 规范单应用上限
   100 个版本，不裁剪几十天就撑爆了。
6. **changelog 按变体拆**。上游习惯把「全功能版」的补充说明写在 `>` 引用块里，正文
   写通用说明；所以轻量版取正文、全功能版取引用块，一方为空时互相兜底。
7. **同一上游可以再按「发布通道」拆条目**。有些作者会把未稳定的迭代版打成
   Pre-release（fnmusic 的 v2.11.0d 就是）。这类版本不该混进正式版条目，但也不该
   直接丢掉 —— 用 `channel: prerelease` 单独开一个「预览版」条目，并用
   `version_suffix` 把 `-preview` 打进版本键，客户端一眼能分辨。

用法:
    python3 scripts/sync_upstream.py                 # 同步 upstream/ 下所有配置
    python3 scripts/sync_upstream.py --dry-run       # 只报告将要做什么，不写盘
    python3 scripts/sync_upstream.py --app fnmedia-ext   # 只同步涉及该 appid 的配置

退出码: 0 = 正常（有无改动都算正常）；1 = 出错（网络/配置问题）。

依赖: 仅 Python 标准库。建议设置 GITHUB_TOKEN / GH_TOKEN，否则匿名 API 限额很低
      （60 次/小时，且是同 IP 共享的，很容易被别人用光）。
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_DIR = ROOT / "upstream"
API = "https://api.github.com"
TZ_CN = timezone(timedelta(hours=8))
UA = "FnDepot-upstream-sync/1.0"

# changelog 截断长度：上游有些 release body 很长，客户端版本卡片放不下
MAX_CHANGELOG = 500

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


# ------------------------------------------------------------------ 基础工具

def log(msg: str) -> None:
    print(msg, flush=True)


def api_get(url: str) -> bytes:
    """调 GitHub API（带 token，提高限额）。"""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def download(url: str) -> bytes:
    """下载 Release 资产。

    刻意不带 Authorization：browser_download_url 会 302 到 CDN，而 urllib 重定向时
    会沿用原请求头，等于把 token 发给第三方域名。这些资产本来就是公开的。
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def vkey(v: str):
    """版本号排序键。数字段按数值比，非数字段按字符串比（0.2.21 < 0.2.100）。

    预发布后缀（SEMVER 的 `-xxx`）单独摘出来，且排在「无后缀」之前：即
    `2.11.0-3 < 2.11.0`，符合 SEMVER 语义。早期实现把 `-` 当成普通分隔符，
    会得出 `2.11.0 < 2.11.0-3`（预发布反而更新），与规范相反。
    """
    core, _, pre = v.partition("-")
    out = []
    for part in re.split(r"[.\+]", core):
        out.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    out.append((0, 0 if pre else 1, pre))
    return out


def now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def iso_cn(ts: str | None) -> str:
    """把 GitHub 的 UTC 时间戳转成本源统一使用的 +08:00 偏移 ISO 8601。

    用上游发布时间而不是「我们同步的时间」，版本列表按时间排序才是对的。
    """
    if not ts:
        return now_iso()
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return now_iso()
    return dt.astimezone(TZ_CN).isoformat(timespec="seconds")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ FPK 解析

def manifest_fields(blob: bytes) -> dict:
    """从 FPK（tar.gz）里解出 manifest 字段。解不出来返回空 dict。"""
    try:
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            member = next(
                (n for n in tar.getnames() if n.lstrip("./") == "manifest"), None
            )
            if member is None:
                return {}
            text = tar.extractfile(member).read().decode("utf-8", "replace")
    except (tarfile.TarError, OSError):
        return {}
    return {k: v.strip() for k, v in re.findall(r"^\s*(\w+)\s*=\s*(.*)$", text, re.M)}


def split_changelog(body: str, kind: str) -> str:
    """按变体类型从 Release body 里摘 changelog。

    上游的写法是：正文写通用说明，用 `>` 引用块补充「全功能版：…」。所以轻量版取
    正文（plain）、全功能版取引用块（quote）；目标为空时互相兜底，避免某个版本没
    按套路写就丢掉整段说明。
    """
    plain: list = []
    quote: list = []
    for line in (body or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            quote.append(s.lstrip("> ").strip())
        elif not s.startswith("#"):
            plain.append(s)
    p, q = " ".join(plain).strip(), " ".join(quote).strip()
    text = (q or p) if kind == "quote" else (p or q)
    return text[:MAX_CHANGELOG]


def filter_releases(rel_order: list, mode: str) -> list:
    """按变体的发布通道挑 Release。

    stable = 只要正式版（默认，避免把半成品收进源）
    prerelease = 只要预发布版（单独开一个「预览版」条目时用）
    all = 都要
    """
    if mode == "all":
        return rel_order
    want_pre = mode == "prerelease"
    return [r for r in rel_order if bool(r.get("prerelease")) == want_pre]


def baseline_note(var: dict, rel_order: list) -> str:
    """生成「预览版 vs 稳定版」的版本关系说明。

    预览版单独成条目后，最大的问题是用户看不出它和稳定版谁更靠前、领先多少。
    这里显式算出：稳定版条目当前最新的版本号作基线，再数上游有多少个预发布迭代
    比它新，把结论写进 desc。
    """
    base_app = var.get("baseline_app")
    if not base_app:
        return ""
    path = ROOT / "apps" / f"{base_app}.json"
    if not path.is_file():
        return ""
    srel = (read_json(path).get("releases") or {})
    if not srel:
        return ""

    base_v = max(srel, key=vkey)
    ahead = [r["tag_name"] for r in rel_order
             if r.get("prerelease") and vkey(r["tag_name"].lstrip("v")) > vkey(base_v)]

    if ahead:
        rel_txt = (f"当前基线稳定版 **{base_v}**，上游已有 **{len(ahead)} 个预发布迭代**在其之后"
                   f"（{'、'.join(ahead[:5])}），即本条目比稳定版新。")
    else:
        rel_txt = (f"当前基线稳定版 **{base_v}**，上游暂无比它更新的预发布迭代"
                   f"（作者可能已把预发布内容并入正式版），此时装稳定版即可。")

    return (f"\n\n【预览版通道说明】本条目只收录上游标记为 Pre-release 的版本，"
            f"与「稳定版」是**同一个 appid**（装了其一就不能再装其二）。{rel_txt}"
            f"版本号带 `-N` 后缀即预发布（如 `2.11.0-3`），按 SEMVER 语义它**小于**对应的"
            f"正式版 `2.11.0`；一旦上游把 `2.11.0` 转为正式版，稳定版条目会收录它，"
            f"届时请以稳定版为准。")


# ------------------------------------------------------------------ 单个版本

def resolve_asset(rel: dict, var: dict):
    """定位本次要收录的资产；返回 (资产名, 下载URL, 上游声明的sha256或None, 跳过原因)。"""
    ver_guess = rel["tag_name"].lstrip("v")
    assets = {a["name"]: a for a in rel.get("assets", [])}

    # 有些上游的资产名与 Release tag 对不上（fnmusic-ext 的 v2.11.0d 发的却是
    # fnmusic-ext-2.11.0-3.fpk），硬拼模板必然找不到。这时改用后缀挑：
    # 取该 Release 里第一个以 asset_suffix 结尾、且本身不是 .sha256 的资产。
    suffix = var.get("asset_suffix")
    if suffix:
        cands = sorted(n for n in assets
                       if n.endswith(suffix) and not n.endswith(".sha256"))
        if not cands:
            return None, None, None, f"{rel['tag_name']}: 没有以 {suffix} 结尾的资产（跳过，下轮再试）"
        name = cands[0]
    else:
        name = var["asset"].format(version=ver_guess)

    # 坑 1：Release 可能只传了一半 —— .sha256 在了、.fpk 还没传完
    if name not in assets:
        return None, None, None, f"{rel['tag_name']}: 资产 {name} 尚未上传（跳过，下轮再试）"

    declared = None
    sha_asset = assets.get(name + ".sha256")
    if sha_asset:
        try:
            txt = download(sha_asset["browser_download_url"]).decode("utf-8", "replace")
            m = re.match(r"([0-9a-fA-F]{64})", txt.strip())
            if m:
                declared = m.group(1).lower()
        except Exception:
            declared = None
    return name, assets[name]["browser_download_url"], declared, None


def build_version(rel: dict, var: dict, dry_run: bool):
    """同步一个 Release 的指定变体；返回 (version, node, manifest字段) 或 (None, 原因, None)。"""
    name, url, declared, reason = resolve_asset(rel, var)
    if reason:
        return None, reason, None

    if dry_run:
        # 干跑不下载大包：只确认资产存在、报告将要做什么
        return rel["tag_name"].lstrip("v"), {"_dry_run": True, "url": url}, {}

    blob = download(url)
    real_sha = hashlib.sha256(blob).hexdigest()

    # 坑 3：与上游声明的哈希交叉校验，不一致宁可不收
    if declared and declared != real_sha:
        return None, (f"{rel['tag_name']}: {name} 哈希与上游 .sha256 不符 "
                      f"（上游 {declared[:12]}… / 实算 {real_sha[:12]}…），跳过"), None

    fields = manifest_fields(blob)
    # 坑 2：版本键以包内 manifest 为准
    version = (fields.get("version") or "").strip() or rel["tag_name"].lstrip("v")

    node = {
        # 前缀加在截断之后：changelog 有 500 字上限，前缀必须在额度外，否则
        # 上游正文一长就把「这是预览版」的标记挤出去了。
        "changelog": (var.get("changelog_prefix") or "")
                     + split_changelog(rel.get("body") or "", var.get("changelog_from", "plain")),
        "updated_at": iso_cn(rel.get("published_at")),
        "packages": {
            var["arch"]: {
                "download_url": url,
                "sha256": real_sha,
                "size": len(blob),
            }
        },
    }
    return version, node, fields


# ------------------------------------------------------------------ 详情文件

def apply_header(detail: dict, var: dict, cfg: dict, fields: dict, extra_note: str = "") -> None:
    """刷新详情文件的头部元数据。

    分两类字段：
    - 从包内 manifest 派生的（display_name / desc / maintainer）：每次同步都刷新，
      作者改名改描述能自动跟上；
    - 本源自己定的静态字段（platform / categories / icon_url / run_as …）：只在缺失
      时补，绝不覆盖 —— 否则我们在仓库里做的手工修正会被上游冲掉。
    """
    tpl = var.get("display_name", "{manifest}")
    dn = tpl.replace("{manifest}", (fields.get("display_name") or "").strip()) if "{manifest}" in tpl else tpl
    if dn:
        detail["display_name"] = dn

    desc = (fields.get("desc") or "").strip()
    if desc:
        detail["desc"] = desc + (var.get("desc_suffix") or "") + (extra_note or "")

    if fields.get("maintainer"):
        detail["maintainer"] = fields["maintainer"].strip()
    if cfg.get("homepage"):
        detail.setdefault("maintainer_url", cfg["homepage"])
    if fields.get("maintainer_url"):
        detail["maintainer_url"] = fields["maintainer_url"].strip()

    static = {
        "app_name": var["appid"],
        "platform": [var["arch"]],
        "categories": var.get("categories") or [],
        "icon_url": var.get("icon", ""),
        "run_as": var.get("run_as", "package"),
        "install_type": var.get("install_type", ""),
        "is_docker": bool(var.get("is_docker", False)),
    }
    for key, val in static.items():
        detail.setdefault(key, val)


def prune(releases: dict, keep: int) -> list:
    """裁掉超出 keep 的最老版本，返回被删的版本号列表。"""
    if len(releases) <= keep:
        return []
    ordered = sorted(releases, key=vkey, reverse=True)
    drop = ordered[keep:]
    for v in drop:
        releases.pop(v, None)
    return drop


def sync_variant(rel_order: list, var: dict, cfg: dict, dry_run: bool,
                 refresh: bool = False) -> dict:
    """同步一个变体（一个 appid）；返回统计。

    refresh=True 时即使没有新版本，也会重读该通道最新一版包的 manifest 来刷新头部
    元数据 —— 改了配置里的 permission_note / desc_suffix 之类要靠它立刻生效
    （正常同步只在「收录了新版本」时才刷新头部）。代价是要重新下载一枚包。
    """
    appid = var["appid"]
    app_path = ROOT / "apps" / f"{appid}.json"
    stat = {"appid": appid, "added": [], "skipped": [], "pruned": [], "refreshed": False}

    if not app_path.is_file():
        stat["skipped"].append(f"缺少 apps/{appid}.json，跳过（请先手工建好详情文件）")
        return stat

    detail = read_json(app_path)
    releases = detail.setdefault("releases", {})
    keep = int(var.get("keep_versions", cfg.get("keep_versions", 10)))
    channel = channel_of(var, cfg)
    suffix = var.get("version_suffix", "")
    # 只有「需要靠 tag 认人」的变体才往节点里写 upstream_tag：正式版条目的版本键与
    # tag 基本对应，没必要为了幂等给全部历史节点补字段（已发布元数据尽量不动）。
    tag_tracking = bool(suffix) or channel == "prerelease"
    latest_fields: dict = {}

    # 已收录标记：优先用节点里的 upstream_tag，老数据回退到版本键本身
    seen: set = set()
    for v, n in releases.items():
        seen.add(v)
        seen.add(v.lstrip("v"))
        if isinstance(n, dict) and n.get("upstream_tag"):
            seen.add(n["upstream_tag"])
            seen.add(str(n["upstream_tag"]).lstrip("v"))

    for rel in rel_order:
        guess = rel["tag_name"].lstrip("v")
        if rel["tag_name"] in seen or guess in seen:
            continue
        if not in_channel(rel, channel):
            continue
        # 已经收满 keep 个之后，更老的版本没必要再看（收进来也会被裁掉）
        if len(releases) >= keep and vkey(guess) < vkey(min(releases, key=vkey)):
            break

        version, node, fields = build_version(rel, var, dry_run)
        if version is None:
            stat["skipped"].append(node)  # 第二个返回值是原因
            continue
        if suffix:
            version = version + suffix
        if tag_tracking:
            node["upstream_tag"] = rel["tag_name"]
        releases[version] = node
        stat["added"].append(version)
        if fields:
            latest_fields = fields

    if dry_run:
        stat["pruned"] = prune(dict(releases), keep) if len(releases) > keep else []
        return stat

    if refresh and not latest_fields and rel_order and not dry_run:
        _, _, fields = build_version(rel_order[0], var, dry_run)
        if fields:
            latest_fields = fields
            stat["refreshed"] = True

    if latest_fields:
        # desc 每次同步都会被包内 manifest 刷新，所以「权限段」必须由配置注入，
        # 直接手改 apps/*.json 会被下一轮同步冲掉。
        parts = [p for p in ((var.get("permission_note") or "").strip(),
                             baseline_note(var, rel_order)) if p]
        note = "\n\n" + "\n\n".join(parts) if parts else ""
        apply_header(detail, var, cfg, latest_fields, note)

    stat["pruned"] = prune(releases, keep)
    write_json(app_path, detail)
    return stat


# ------------------------------------------------------------------ 主流程

def load_releases(repo: str, cfg: dict) -> list:
    """拉取上游 Release 列表（含 Pre-release），按版本号从新到旧排序。

    只剔除 draft；是否收 Pre-release 交给每个变体自己的 channel 决定 —— 同一个上游
    可能同时要「正式版条目」和「预览版条目」，在这一层过滤就把后者饿死了。
    """
    data = json.loads(api_get(f"{API}/repos/{repo}/releases?per_page=100"))
    if not isinstance(data, list):
        raise RuntimeError(f"拉取 {repo} 的 Release 失败：{(data or {}).get('message')}")

    kept = [r for r in data if not r.get("draft")]
    kept.sort(key=lambda r: vkey(r["tag_name"].lstrip("v")), reverse=True)
    return kept


def channel_of(var: dict, cfg: dict) -> str:
    """变体要收哪个发布通道：stable / prerelease / all。"""
    ch = var.get("channel")
    if ch in ("stable", "prerelease", "all"):
        return ch
    # 向后兼容：老配置在顶层写 include_prerelease，等价于这个变体两个通道都收
    return "all" if cfg.get("include_prerelease") else "stable"


def in_channel(rel: dict, channel: str) -> bool:
    if channel == "all":
        return True
    is_pre = bool(rel.get("prerelease"))
    return is_pre if channel == "prerelease" else not is_pre


def ensure_indexed(appid: str) -> bool:
    """确保应用已登记进 fnpack.json 索引，并刷新 details_updated_at。"""
    idx = ROOT / "fnpack.json"
    data = read_json(idx)
    apps = data.setdefault("apps", {})
    entry = apps.setdefault(appid, {"details_url": f"apps/{appid}.json"})
    entry["details_updated_at"] = now_iso()
    write_json(idx, data)
    return True


def sync_config(path: Path, dry_run: bool, only_app: str | None, refresh: bool = False) -> int:
    cfg = read_json(path)
    repo = cfg["repo"]
    keep = int(cfg.get("keep_versions", 10))
    variants = [v for v in (cfg.get("variants") or [])
                if not only_app or v["appid"] == only_app]
    if not variants:
        return 0

    log(f"\n=== {path.name} · {repo} · 保留最近 {keep} 版 ===")
    try:
        rel_order = load_releases(repo, cfg)
    except Exception as exc:  # noqa: BLE001
        log(f"  ✗ {exc}")
        return 1
    log(f"  上游 Release {len(rel_order)} 个，最新 {rel_order[0]['tag_name'] if rel_order else '—'}")

    changed = False
    failed = False
    for var in variants:
        stat = sync_variant(rel_order, var, cfg, dry_run, refresh)
        vkeep = int(var.get("keep_versions") or keep)
        log(f"  [{stat['appid']}] 通道={channel_of(var, cfg)} 保留={vkeep}"
            + (f" 基线={var['baseline_app']}" if var.get("baseline_app") else ""))
        if stat["added"]:
            log(f"    新增版本: {', '.join(stat['added'])}")
            changed = True
        else:
            log("    无新版本")
        if stat.get("refreshed"):
            log("    已刷新头部元数据（--refresh）")
            changed = True
        for reason in stat["skipped"]:
            log(f"    跳过: {reason}")
        if stat["pruned"]:
            log(f"    裁剪旧版本: {', '.join(stat['pruned'])}")
            changed = True
        if not dry_run and (stat["added"] or stat["pruned"]):
            ensure_indexed(stat["appid"])
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="同步上游已发布的 FPK 到本应用源")
    ap.add_argument("--dry-run", action="store_true", help="只报告将要做什么，不写盘")
    ap.add_argument("--app", help="只同步涉及该 appid 的配置")
    ap.add_argument("--refresh", action="store_true",
                    help="即使没有新版本也重新读取最新包刷新头部元数据（改了权限段说明时用）")
    args = ap.parse_args()

    if not TOKEN:
        log("! 未设置 GITHUB_TOKEN/GH_TOKEN，走匿名 API（限额 60 次/小时，容易失败）")

    configs = sorted(UPSTREAM_DIR.glob("*.json"))
    if not configs:
        log(f"upstream/ 下没有配置文件，无需同步")
        return 0

    log("=" * 70)
    log(f"上游同步{'（干跑）' if args.dry_run else ''} —— {ROOT}")
    log("=" * 70)

    rc = 0
    for path in configs:
        rc |= sync_config(path, args.dry_run, args.app, args.refresh)

    log("-" * 70)
    log("完成。改动需提交后才会生效。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
