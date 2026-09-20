#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_source.py — 按 FnDepot 外部应用源 V2 规范做发布前检查

实现规范（https://github.com/EWEDLCM/FnDepot）第 12 节「发布前检查清单」的自动化核对，
并额外校验拆分模式的一致性（索引键 / app_name / FPK manifest 的 appname 三者对齐）。

用法:
    python3 scripts/verify_source.py            # 校验
    python3 scripts/verify_source.py --remote   # 额外校验远程 FPK 可下载且 sha256/size 与声明一致

退出码: 0 = 通过（允许有警告），1 = 存在错误。

依赖: 仅 Python 标准库。
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VALID_PLATFORMS = {"all", "x86", "arm"}
VALID_RUN_AS = {"package", "root"}
VALID_CATEGORIES = {
    "影音娱乐", "系统工具", "编程开发", "AI赋能", "生活服务",
    "智能智控", "教育学习", "游戏地带", "硬件驱动",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^\d+(\.\d+)*([-+][0-9A-Za-z.\-]+)?$")
MAX_PREVIEWS = 8
MAX_VERSIONS = 100

errors: list = []
warnings: list = []
passed: list = []


def err(m: str) -> None:
    errors.append(m)


def warn(m: str) -> None:
    warnings.append(m)


def ok(m: str) -> None:
    passed.append(m)


def rel(p: str) -> Path:
    return (ROOT / p.lstrip("./")).resolve()


def normalize_url(base: Path, url: str) -> str:
    """把相对 URL 按基准目录解析成绝对路径字符串；绝对 URL 原样返回。"""
    if url.startswith(("http://", "https://")):
        return url
    return str((base / url).resolve())


# ---------------------------------------------------------------- 源级

def check_source() -> dict | None:
    fp = ROOT / "fnpack.json"
    if not fp.is_file():
        err("根目录缺少 fnpack.json（GitHub 模式下文件名必须完全匹配）")
        return None

    raw = fp.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        err("fnpack.json 带 UTF-8 BOM —— 必须是纯 UTF-8")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        err(f"fnpack.json 不是严格 JSON（注释/尾逗号/未转义字符?）: {exc}")
        return None
    if re.search(r",\s*[}\]]", raw.decode("utf-8")):
        warn("fnpack.json 疑似存在尾逗号")
    ok("fnpack.json 是纯 UTF-8 严格 JSON")

    if data.get("schema_version") != "2":
        err(f'schema_version 必须是字符串 "2"，当前 {data.get("schema_version")!r}')
    else:
        ok('schema_version == "2"')

    si = data.get("source_info")
    if not isinstance(si, dict):
        err("缺少 source_info 对象（V2 必需）")
        return data
    for k in ("name", "author"):
        if not si.get(k):
            err(f"source_info.{k} 为空（必填）")
        else:
            ok(f"source_info.{k} = {si[k]}")
    if "details_updated_at" in si:
        err("source_info 中出现 details_updated_at —— 规范规定该字段只能放在应用节点")
    else:
        ok("源级未误用 details_updated_at")

    if si.get("homepage") and not str(si["homepage"]).startswith(("http://", "https://")):
        err("source_info.homepage 必须是 http/https URL")

    i18n = si.get("i18n")
    if i18n is not None:
        if not isinstance(i18n, dict):
            err("source_info.i18n 必须是对象")
        else:
            for loc, f in i18n.items():
                if not isinstance(f, dict):
                    err(f"source_info.i18n[{loc}] 必须是对象")
                    continue
                bad = [k for k in f if k not in ("name", "description")]
                if bad:
                    err(f"source_info.i18n[{loc}] 含非法键 {bad}（只允许 name/description）")

    apps = data.get("apps")
    if not isinstance(apps, dict):
        err("apps 必须是对象")
    elif not apps:
        warn("apps 为空，源中尚无应用")
    elif len(apps) > 5000:
        err(f"应用数 {len(apps)} 超过上限 5000")

    return data


# ---------------------------------------------------------------- 应用级

def check_app(appname: str, entry: dict, remote: bool) -> None:
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", appname):
        err(f"{appname}: 应用名非法（字母/数字/点/下划线/短横线，且以字母数字开头）")

    details_url = entry.get("details_url")
    if not details_url:
        # 单文件模式：元数据全部内联
        detail = entry
        detail_base = ROOT / "fnpack.json"
        is_split = False
    else:
        is_split = True
        dp = rel(details_url)
        if not dp.is_file():
            err(f"{appname}: details_url 指向的文件不存在 -> {details_url}")
            return
        try:
            detail = json.loads(dp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            err(f"{appname}: 详情 JSON 不合法: {exc}")
            return
        detail_base = dp
        ok(f"{appname}: 拆分模式，详情文件 {details_url}")

        app_name = detail.get("app_name")
        if app_name != appname:
            err(f"{appname}: 详情文件 app_name={app_name!r} 与索引键 {appname!r} 不一致（规范强制）")
        else:
            ok(f"{appname}: app_name 与索引键一致")

    # 必填元数据（合并后校验）
    for k in ("display_name", "desc"):
        if not detail.get(k):
            err(f"{appname}: 缺少必填字段 {k}")
        else:
            ok(f"{appname}: {k} 存在")

    platform = detail.get("platform")
    if isinstance(platform, str):
        platform = [platform]
    if not isinstance(platform, list) or not platform:
        err(f"{appname}: 缺少 platform")
        platform = []
    else:
        bad = [p for p in platform if p not in VALID_PLATFORMS]
        if bad:
            err(f"{appname}: 非法 platform {bad}（只允许 all/x86/arm）")
        else:
            ok(f"{appname}: platform = {platform}")

    cats = detail.get("categories")
    if not isinstance(cats, list) or not cats:
        err(f"{appname}: 缺少 categories")
    else:
        bad = [c for c in cats if c not in VALID_CATEGORIES]
        if bad:
            err(f"{appname}: 非法分类 {bad}")
        elif len(cats) > 2:
            err(f"{appname}: categories 最多 2 个，当前 {len(cats)}")
        else:
            ok(f"{appname}: categories = {cats}")

    icon = detail.get("icon_url")
    if not icon:
        err(f"{appname}: 缺少必填 icon_url")
    else:
        p = normalize_url(detail_base.parent, icon)
        if p.startswith("http"):
            warn(f"{appname}: icon_url 使用绝对 URL，仓库改名/迁址会失效 -> {icon}")
            ok(f"{appname}: icon_url 存在（绝对 URL 形式）")
        elif Path(p).is_file():
            ok(f"{appname}: icon_url 解析命中 {Path(p).relative_to(ROOT)}")
        else:
            err(f"{appname}: icon_url 相对详情 JSON 解析后不存在 -> {p}")

    if detail.get("run_as") not in VALID_RUN_AS:
        err(f"{appname}: run_as 必须是 package 或 root，当前 {detail.get('run_as')!r}")
    else:
        ok(f"{appname}: run_as = {detail['run_as']}")

    if not isinstance(detail.get("is_docker"), bool):
        err(f"{appname}: is_docker 必须是布尔值")
    else:
        ok(f"{appname}: is_docker = {detail['is_docker']}")

    if not isinstance(detail.get("install_type", ""), str):
        err(f"{appname}: install_type 必须是字符串（空串=存储空间，root=系统空间）")
    else:
        ok(f"{appname}: install_type = {detail.get('install_type')!r}")

    if "service_port" in detail and not isinstance(detail["service_port"], str):
        err(f"{appname}: service_port 必须是字符串")

    # 规范 4.3：开发者 / 发布者
    if not detail.get("maintainer"):
        warn(f"{appname}: 未填写 maintainer（开发者），应用详情页将无开发者信息")
    else:
        ok(f"{appname}: maintainer = {detail['maintainer']}")
    for k in ("maintainer_url", "distributor_url"):
        v = detail.get(k)
        if v and not str(v).startswith(("http://", "https://")):
            err(f"{appname}: {k} 必须是 http/https URL")
    if detail.get("distributor") == detail.get("maintainer") and detail.get("distributor"):
        warn(f"{appname}: distributor 与 maintainer 相同，规范规定可省略")

    previews = detail.get("preview_urls") or []
    if isinstance(previews, list):
        if len(previews) > MAX_PREVIEWS:
            warn(f"{appname}: preview_urls 有 {len(previews)} 张，客户端只读前 {MAX_PREVIEWS} 张")
        for u in previews:
            p = normalize_url(detail_base.parent, u)
            if not p.startswith("http") and not Path(p).is_file():
                warn(f"{appname}: 预览图不存在 -> {u}")
    else:
        err(f"{appname}: preview_urls 必须是数组")

    check_releases(appname, detail.get("releases"), platform, detail_base, remote)


# ---------------------------------------------------------------- 版本级

def check_releases(appname, releases, platform, detail_base, remote) -> None:
    if not isinstance(releases, dict) or not releases:
        err(f"{appname}: 缺少 releases 或为空")
        return
    if len(releases) > MAX_VERSIONS:
        err(f"{appname}: 版本数 {len(releases)} 超过上限 {MAX_VERSIONS}")

    for version, node in releases.items():
        if not SEMVER.match(version):
            err(f"{appname}@{version}: 版本号必须是可比较的版本号（不得用 latest/日期文字）")
        else:
            ok(f"{appname}@{version}: 版本号合法")
        if not isinstance(node, dict):
            err(f"{appname}@{version}: 版本节点必须是对象")
            continue

        if not node.get("changelog"):
            warn(f"{appname}@{version}: 缺 changelog，客户端版本卡片无更新说明")
        ua = node.get("updated_at")
        if not ua:
            warn(f"{appname}@{version}: 缺 updated_at，建议填带时区偏移的 ISO 8601")
        elif not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$", ua):
            warn(f"{appname}@{version}: updated_at 建议用 ISO 8601 带时区，当前 {ua}")

        pkgs = node.get("packages")
        if not isinstance(pkgs, dict) or not pkgs:
            err(f"{appname}@{version}: 缺少 packages")
            continue

        bad = [a for a in pkgs if a not in VALID_PLATFORMS]
        if bad:
            err(f"{appname}@{version}: 非法架构键 {bad}（只允许 all/x86/arm，否则该版本校验失败）")

        # 规范 5.3：platform 与 packages 键应对齐
        keys = set(pkgs)
        if platform and keys <= {"all"} and "all" not in platform:
            warn(f"{appname}@{version}: platform={platform} 但 packages 只有 all；"
                 f"若为通用包建议 platform 写 [\"all\"]，若为架构专用包建议键名写 {platform[0]}")

        for arch, pkg in pkgs.items():
            if arch in VALID_PLATFORMS:
                check_package(appname, version, arch, pkg, detail_base, remote)


def check_package(appname, version, arch, pkg, detail_base, remote) -> None:
    tag = f"{appname}@{version}[{arch}]"
    if not isinstance(pkg, dict):
        err(f"{tag}: 安装包分支必须是对象")
        return

    url = pkg.get("download_url")
    if not url:
        err(f"{tag}: 缺少 download_url")
        return
    if str(url).startswith(("file://", "ftp://", "data:")):
        err(f"{tag}: URL 协议非法（只允许 http/https 或仓库相对路径）")
    if "@" in str(url).split("//")[-1].split("/")[0]:
        err(f"{tag}: URL 中不得含用户名/密码")

    sha = pkg.get("sha256", "")
    if not sha:
        warn(f"{tag}: 缺少 sha256（规范强烈建议，存在时客户端强制校验）")
    elif not HEX64.match(str(sha)):
        err(f"{tag}: sha256 必须是 64 位小写十六进制")
    else:
        ok(f"{tag}: sha256 格式合法")

    size = pkg.get("size")
    if size is None:
        warn(f"{tag}: 缺少 size")
    elif not isinstance(size, int) or isinstance(size, bool) or size < 0:
        err(f"{tag}: size 必须是非负整数 Bytes，不能写 '20 MB'")
    else:
        ok(f"{tag}: size = {size} bytes")

    # 本地相对路径：直接比对真实文件
    if not str(url).startswith(("http://", "https://")):
        p = Path(normalize_url(detail_base.parent, str(url)))
        if not p.is_file():
            err(f"{tag}: 本地 FPK 不存在 -> {url}")
            return
        real_size, real_sha = p.stat().st_size, sha256_of(p)
        if isinstance(size, int) and size != real_size:
            err(f"{tag}: size 与真实文件不符 (json={size}, 实际={real_size})")
        if sha and sha != real_sha:
            err(f"{tag}: sha256 与真实文件不符 (json={sha}, 实际={real_sha})")
        if isinstance(size, int) and size == real_size and sha == real_sha:
            ok(f"{tag}: 本地文件 size/sha256 完全一致")
    elif remote:
        try:
            with urllib.request.urlopen(str(url), timeout=30) as resp:
                blob = resp.read()
        except Exception as exc:  # noqa: BLE001
            err(f"{tag}: 远程 FPK 下载失败 -> {exc}")
            return
        real_size = len(blob)
        real_sha = hashlib.sha256(blob).hexdigest()
        if isinstance(size, int) and size != real_size:
            err(f"{tag}: 远程 size 不符 (json={size}, 实际={real_size})")
        if sha and sha != real_sha:
            err(f"{tag}: 远程 sha256 不符 (json={sha}, 实际={real_sha})")
        if isinstance(size, int) and size == real_size and sha == real_sha:
            ok(f"{tag}: 远程 FPK 可下载且 size/sha256 完全一致")


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ---------------------------------------------------------------- 打包工程一致性

def check_package_project(appname: str) -> None:
    """核对 packages/<appname>/manifest 的 appname 与源键一致。"""
    mf = ROOT / "packages" / appname / "manifest"
    if not mf.is_file():
        warn(f"{appname}: 未找到 packages/{appname}/manifest（若用 CI 构建可忽略）")
        return
    fields = dict(re.findall(r"^\s*(\w+)\s*=\s*(.*)$", mf.read_text(encoding="utf-8"), re.M))
    m_appname = (fields.get("appname") or "").strip()
    if m_appname != appname:
        err(f"{appname}: packages/{appname}/manifest 的 appname={m_appname!r} 与源键不一致")
    else:
        ok(f"{appname}: FPK manifest 的 appname 与源键一致")
    if not fields.get("maintainer"):
        warn(f"{appname}: packages/{appname}/manifest 未填 maintainer")
    plat = (fields.get("platform") or "").strip()
    if "," in plat or " " in plat:
        err(f"{appname}: manifest 的 platform={plat!r} 只能填一个值（多架构需分别打包）")
    elif plat:
        ok(f"{appname}: FPK manifest platform = {plat}")


def main() -> int:
    ap = argparse.ArgumentParser(description="FnDepot V2 源发布前检查")
    ap.add_argument("--remote", action="store_true",
                    help="额外下载远程 FPK 校验 sha256/size（较慢）")
    args = ap.parse_args()

    print("=" * 70)
    print("FnDepot V2 源发布前检查 —— " + str(ROOT))
    print("=" * 70)

    data = check_source()
    if data:
        apps = data.get("apps")
        if isinstance(apps, dict):
            print(f"\n[应用数] {len(apps)}")
            for appname, entry in apps.items():
                if not isinstance(entry, dict):
                    err(f"{appname}: 应用节点必须是对象")
                    continue
                check_app(appname, entry, args.remote)
                check_package_project(appname)

    print("-" * 70)
    for m in passed:
        print(f"  ✓ {m}")
    for m in warnings:
        print(f"  ! {m}")
    for m in errors:
        print(f"  ✗ {m}")
    print("-" * 70)
    print(f"通过 {len(passed)} · 警告 {len(warnings)} · 错误 {len(errors)}")
    if errors:
        print("\n结论: 不允许发布，请先修复以上错误。")
        return 1
    if warnings:
        print("\n结论: 通过（存在警告，建议处理）。")
    else:
        print("\n结论: 全部检查通过，可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
