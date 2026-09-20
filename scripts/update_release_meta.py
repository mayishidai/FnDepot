#!/usr/bin/env python3
"""回填指定应用的 releases 元数据到 apps/<appid>.json。

每次打 tag 发布 fpk 后调用，写入对应版本的 download_url / sha256 / size，
便于 FnDepot V2 索引直接展示可下载安装包。

架构键从 packages/<appid>/manifest 的 platform 推导（platform 为 all 时用 all，
否则用该值，如 x86），与 apps/<appid>.json 的 platform 对齐，
避免 packages 键名与 platform 脱节导致客户端选不到包。

仓库名从 git remote 反查（退化到 REPO_FALLBACK），避免仓库改名后 URL 全量失效；
也可用环境变量 FNDEPOT_REPO 覆盖。
"""
import argparse
import json
import os
import re
import subprocess
import sys

REPO_FALLBACK = "mayishidai/FnDepot"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_repo() -> str:
    """从 git remote 反查 owner/repo；失败则退回常量。"""
    env = os.environ.get("FNDEPOT_REPO")
    if env:
        return env.strip().strip("/")
    try:
        url = subprocess.check_output(
            ["git", "-C", ROOT, "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return REPO_FALLBACK
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else REPO_FALLBACK


REPO = resolve_repo()


def manifest_path(appid: str) -> str:
    return os.path.join(ROOT, "packages", appid, "manifest")


def app_json_path(appid: str) -> str:
    return os.path.join(ROOT, "apps", f"{appid}.json")


def resolve_arch(appid: str) -> str:
    """从 manifest 的 platform 推导 packages 的架构键，回退到应用详情。"""
    mp = manifest_path(appid)
    if os.path.exists(mp):
        fields = dict(
            re.findall(r"^\s*(\w+)\s*=\s*(.*)$",
                       open(mp, encoding="utf-8").read(), re.M)
        )
        plat = (fields.get("platform") or "").strip()
        if plat:
            if "," in plat or " " in plat:
                sys.exit(f"manifest 的 platform={plat!r} 只能填一个值（多架构需分别打包）")
            return plat
    aj = app_json_path(appid)
    if os.path.exists(aj):
        with open(aj, encoding="utf-8") as f:
            data = json.load(f)
        p = data.get("platform")
        if isinstance(p, list) and p:
            return p[0]
        if isinstance(p, str) and p:
            return p
    return "all"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", required=True, help="应用 id（对应 packages/<appid>/ 与 apps/<appid>.json）")
    p.add_argument("--version", required=True, help="版本号，如 1.0.0")
    p.add_argument("--tag", required=True, help="git tag，如 v1.0.0")
    p.add_argument("--sha", required=True, help="fpk 的 sha256")
    p.add_argument("--size", required=True, type=int, help="fpk 字节大小")
    p.add_argument("--changelog", default="", help="可选，覆盖/补充 changelog")
    args = p.parse_args()

    appid = args.app
    app_json = app_json_path(appid)

    if not re.fullmatch(r"[A-Za-z0-9._-]+", appid):
        sys.exit(f"--app 只允许字母/数字/点/下划线/短横线，当前 {appid!r}")
    if not os.path.exists(app_json):
        sys.exit(f"找不到 {app_json}")
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha):
        sys.exit(f"--sha 必须是 64 位小写十六进制，当前 {args.sha!r}")
    if args.size < 0:
        sys.exit("--size 必须是非负整数")

    with open(app_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    arch = resolve_arch(appid)

    releases = data.setdefault("releases", {})
    version_block = releases.setdefault(args.version, {})
    if not version_block.get("changelog"):
        version_block["changelog"] = args.changelog or f"发布 {args.version}。"
    version_block.setdefault("updated_at", "")
    packages = version_block.setdefault("packages", {})

    # 若历史版本用了其他架构键，保持单键一致，避免同版本出现多个分支
    if arch != "all":
        for stale in [k for k in packages if k in ("all", "x86", "arm") and k != arch]:
            packages.pop(stale, None)

    packages[arch] = {
        "download_url": f"https://github.com/{REPO}/releases/download/{args.tag}/{appid}.fpk",
        "sha256": args.sha,
        "size": args.size,
    }

    with open(app_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"仓库           = {REPO}")
    print(f"已更新 {os.path.relpath(app_json, ROOT)} releases[{args.version}].packages.{arch}")
    print(f"  download_url = {packages[arch]['download_url']}")
    print(f"  sha256       = {args.sha}")
    print(f"  size         = {args.size}")


if __name__ == "__main__":
    main()
