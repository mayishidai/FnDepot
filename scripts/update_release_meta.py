#!/usr/bin/env python3
"""回填 agnes-ai-studio 的 releases 元数据到 apps/agnes-ai-studio.json。

每次打 tag 发布 fpk 后调用，写入对应版本的 download_url / sha256 / size，
便于 FnDepot V2 索引直接展示可下载安装包。
"""
import argparse
import json
import os
import sys

REPO = "mayishidai/fnos-app-depot"
APP_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "apps", "agnes-ai-studio.json"
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True, help="版本号，如 1.0.0")
    p.add_argument("--tag", required=True, help="git tag，如 v1.0.0")
    p.add_argument("--sha", required=True, help="fpk 的 sha256")
    p.add_argument("--size", required=True, type=int, help="fpk 字节大小")
    args = p.parse_args()

    if not os.path.exists(APP_JSON):
        sys.exit(f"找不到 {APP_JSON}")

    with open(APP_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    releases = data.setdefault("releases", {})
    version_block = releases.setdefault(args.version, {})
    packages = version_block.setdefault("packages", {})
    packages["all"] = {
        "download_url": f"https://github.com/{REPO}/releases/download/{args.tag}/agnes-ai-studio.fpk",
        "sha256": args.sha,
        "size": args.size,
    }

    with open(APP_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"已更新 {APP_JSON} releases[{args.version}].packages.all")


if __name__ == "__main__":
    main()
