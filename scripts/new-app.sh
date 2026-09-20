#!/usr/bin/env bash
#
# 飞牛 FnDepot 多应用脚手架
#
# 在「一个仓库多个应用」结构下，输入少量参数即可生成某应用所需的全部文件：
#   - apps/<appid>.json                应用详情（FnDepot V2 拆分模式）
#   - packages/<appid>/                FPK 打包工程（fnpack 直接可 build，
#                                      内含 app/docker/docker-compose.yaml 一份 compose）
#   - assets/icons/<appid>.png         占位图标（纯标准库生成，无需 PIL）
#   并写回 fnpack.json 索引。
#
# 用法:
#   ./scripts/new-app.sh <appid> <display_name> <category> [port] [platform]
#
# 参数:
#   appid        应用标识，须与 FPK manifest 的 appname 一致；
#                仅含字母/数字/./_/-，且以字母或数字开头（如 agnes-ai-studio）
#   display_name 应用显示名（中文也可）
#   category     九大固定分类之一
#   port         容器/服务端口（可选，默认 5000）
#   platform     FPK 目标架构，只能是 all / x86 / arm 单个值（可选，默认 x86）
#                注意：manifest 的 platform 只能填一个值。要同时支持 x86 与 arm，
#                必须分别打两个包，不能写 "x86,arm"。
#
# 示例:
#   ./scripts/new-app.sh comfyui "ComfyUI" "AI赋能" 8188 x86
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "用法: $0 <appid> <display_name> <category> [port] [platform]"
  echo "  platform 只能是 all / x86 / arm 之一，默认 x86"
  exit 1
}

[ "$#" -lt 3 ] && usage

APPID="$1"; DISPLAY="$2"; CATEGORY="$3"; PORT="${4:-5000}"; PLATFORM="${5:-x86}"

# ---- appid 校验 ----
if ! [[ "$APPID" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "✗ appid 非法：须以字母/数字开头，仅可含字母、数字、. _ -" >&2; exit 1
fi

# ---- 分类校验（FnDepot 九大固定分类，不可自创）----
VALID_CATS="影音娱乐 系统工具 编程开发 AI赋能 生活服务 智能智控 教育学习 游戏地带 硬件驱动"
cat_ok=0
for c in $VALID_CATS; do [ "$CATEGORY" = "$c" ] && cat_ok=1; done
[ "$cat_ok" -eq 0 ] && { echo "✗ 分类非法，可选: $VALID_CATS" >&2; exit 1; }

# ---- 架构校验（只允许单个值）----
case "$PLATFORM" in
  all|x86|arm) ;;
  *) echo "✗ platform 非法：只能是 all / x86 / arm 之一，当前 '$PLATFORM'" >&2
     echo "  要同时支持 x86 与 arm 请分别打两个包，而不是写多值。" >&2
     exit 1 ;;
esac

# ---- 端口校验 ----
if [ -n "$PORT" ] && ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "✗ port 必须是数字，当前 '$PORT'" >&2; exit 1
fi

# ---- 幂等保护：已存在则拒绝覆盖 ----
if [ -e "$REPO_ROOT/apps/$APPID.json" ]; then
  echo "✗ apps/$APPID.json 已存在，拒绝覆盖。请换 appid 或先删除。" >&2; exit 1
fi
if [ -e "$REPO_ROOT/packages/$APPID" ]; then
  echo "✗ packages/$APPID/ 已存在，拒绝覆盖。请换 appid 或先删除。" >&2; exit 1
fi

# ---- 反查 GitHub 用户名（与 fnpack.json 的 source_info.author 保持一致）----
GITHUB_USER="$(python3 -c "import json;print(json.load(open('$REPO_ROOT/fnpack.json',encoding='utf-8'))['source_info']['author'])" 2>/dev/null || echo "")"
[ -z "$GITHUB_USER" ] && GITHUB_USER="$(git -C "$REPO_ROOT" config user.name 2>/dev/null || echo unknown)"

# ---- 反查仓库名：取 git remote，避免硬编码在仓库改名后失效 ----
REPO_NAME="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null | sed -E 's#\.git$##; s#.*/##' || true)"
REPO_NAME="${REPO_NAME:-FnDepot}"

NOW="$(TZ=Asia/Shanghai date +"%Y-%m-%dT%H:%M:%S%:z" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"

ICON_URL="../assets/icons/$APPID.png"
DL_URL="https://github.com/$GITHUB_USER/$REPO_NAME/releases/download/v1.0.0/$APPID.fpk"

mkdir -p "$REPO_ROOT/apps" "$REPO_ROOT/assets/icons" \
         "$REPO_ROOT/packages/$APPID/app/docker" \
         "$REPO_ROOT/packages/$APPID/cmd" \
         "$REPO_ROOT/packages/$APPID/config" \
         "$REPO_ROOT/packages/$APPID/wizard"

# ============================================================
# 1) 应用详情 JSON（FnDepot V2 拆分模式）
#    架构键与 platform 对齐：platform=all -> packages.all，否则 packages.<platform>
# ============================================================
cat > "$REPO_ROOT/apps/$APPID.json" <<JSON
{
  "app_name": "$APPID",
  "display_name": "$DISPLAY",
  "desc": "请在此填写 $DISPLAY 的简介（支持 HTML，客户端会清理危险内容）。",
  "platform": [
    "$PLATFORM"
  ],
  "categories": [
    "$CATEGORY"
  ],
  "icon_url": "$ICON_URL",
  "maintainer": "$GITHUB_USER",
  "maintainer_url": "https://github.com/$GITHUB_USER",
  "run_as": "package",
  "install_type": "",
  "is_docker": true,
  "service_port": "$PORT",
  "releases": {
    "1.0.0": {
      "changelog": "首个版本。",
      "updated_at": "$NOW",
      "packages": {
        "$PLATFORM": {
          "download_url": "$DL_URL",
          "sha256": "",
          "size": 0
        }
      }
    }
  }
}
JSON

# ============================================================
# 2) FPK 打包工程 packages/<appid>/  —— fnpack 的直接输入
#    fnpack build 要求 manifest / config/privilege / config/resource /
#    ICON.PNG / ICON_256.PNG / app/ / cmd/ / wizard/ 全部存在
# ============================================================
PKG="$REPO_ROOT/packages/$APPID"

# 2.1 manifest —— 无扩展名，key=value，等号两侧留白对齐即可
cat > "$PKG/manifest" <<MANIFEST
appname      = $APPID
version      = 1.0.0
display_name = $DISPLAY
desc         = 请在此填写 $DISPLAY 的简介。
platform     = $PLATFORM
source       = thirdparty
maintainer   = $GITHUB_USER
distributor  = $GITHUB_USER
MANIFEST

# 2.2 config/privilege —— 运行权限（必须合法 JSON）
cat > "$PKG/config/privilege" <<PRIV
{
    "defaults":
    {
        "run-as": "package"
    },
    "username": "docker-$APPID",
    "groupname": "docker-$APPID"
}
PRIV

# 2.3 config/resource —— 资源声明（必须合法 JSON）
cat > "$PKG/config/resource" <<RES
{
  "docker-project": {
    "projects": [
      {
        "name": "$APPID",
        "path": "docker"
      }
    ]
  },
  "data-share": {
    "shares": [
      {
        "name": "config"
      }
    ]
  }
}
RES

# 2.4 app/docker/docker-compose.yaml —— fnOS 用 {host_port} 占位端口
cat > "$PKG/app/docker/docker-compose.yaml" <<COMPOSE
version: "3.8"

services:
  $APPID:
    image: ghcr.io/$GITHUB_USER/$APPID:latest
    container_name: $APPID
    ports:
      - "{host_port}:$PORT"
    volumes:
      - "/var/apps/$APPID/shares/config:/app/config"
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
COMPOSE

# 2.5 cmd/main —— 生命周期脚本。status 用退出码表状态：0=运行中，3=未运行
cat > "$PKG/cmd/main" <<'MAIN'
#!/bin/bash

FILE_PATH="${TRIM_APPDEST}/docker/docker-compose.yaml"

is_docker_running () {
    DOCKER_NAME=""

    if [ -f "$FILE_PATH" ]; then
        DOCKER_NAME=$(cat $FILE_PATH | grep "container_name" | awk -F ':' '{print $2}' | xargs)
    fi

    if [ -n "$DOCKER_NAME" ]; then
        docker inspect $DOCKER_NAME | grep -q "\"Status\": \"running\"," || exit 1
        return
    fi
}

case $1 in
start)
    # run start command. exit 0 if success, exit 1 if failed
    # do nothing, docker application will be started by appcenter
    exit 0
    ;;
stop)
    # run stop command. exit 0 if success, exit 1 if failed
    # do nothing, docker application will be stopped by appcenter
    exit 0
    ;;
status)
    # check application status command. exit 0 if running, exit 3 if not running
    if is_docker_running; then
        exit 0
    else
        exit 3
    fi
    ;;
*)
    exit 1
    ;;
esac
MAIN

# 2.6 其余生命周期钩子（默认空实现）
write_hook() {
  local name="$1" note="$2"
  cat > "$PKG/cmd/$name" <<HOOK
#!/bin/bash

### This script is called $note.

exit 0
HOOK
}
write_hook install_init       "before the user installs the application"
write_hook install_callback   "after the user installs the application"
write_hook upgrade_init       "before the user upgrades the application"
write_hook upgrade_callback   "after the user upgrades the application"
write_hook uninstall_init     "before the user uninstalls the application"
write_hook uninstall_callback "after the user uninstalls the application"
write_hook config_init        "before the user changes environment variables in the application settings page"
write_hook config_callback    "after the user changes environment variables in the application settings page"

chmod +x "$PKG/cmd"/*

# wizard 目录需存在（可为空），用 .gitkeep 让它进版本库
touch "$PKG/wizard/.gitkeep"

# ============================================================
# 3) 占位图标：assets/icons/<appid>.png (512x512) + ICON.PNG / ICON_256.PNG
#    纯标准库生成，不依赖 PIL
# ============================================================
python3 - "$REPO_ROOT/assets/icons/$APPID.png" "$PKG/ICON.PNG" "$PKG/ICON_256.PNG" <<'PY'
import os, struct, sys, zlib

ICON_RGBA = (99, 102, 241, 255)   # indigo
ICON_RGB  = (99, 102, 241)        # 同色，用于 ICON.PNG 的 RGB 变体


def png_bytes(w, h, rgb, with_alpha):
    """用 zlib 手写一个纯色 PNG（无第三方依赖）。"""
    ctype = 6 if with_alpha else 2
    bpp = 4 if with_alpha else 3
    raw = bytearray()
    row = bytes(rgb) if not with_alpha else bytes(rgb)
    for _ in range(h):
        raw.append(0)              # filter type 0
        raw.extend(row * w)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


targets = [
    (sys.argv[1], 512, ICON_RGBA, True),   # 应用源图标
    (sys.argv[2], 512, ICON_RGBA, True),   # FPK 图标
    (sys.argv[3], 256, ICON_RGBA, True),   # FPK 小图标
]
for path, size, color, alpha in targets:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png_bytes(size, size, color, alpha))
    print(f"  icon -> {os.path.basename(path)} ({size}x{size}, {os.path.getsize(path)} bytes)")
PY

# ============================================================
# 4) 写回 fnpack.json 索引
# ============================================================
python3 - "$REPO_ROOT/fnpack.json" "$APPID" "$NOW" <<'PY'
import json, sys

path, appid, now = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data.setdefault("apps", {})[appid] = {
    "details_url": f"apps/{appid}.json",
    "details_updated_at": now,
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
json.load(open(path, encoding="utf-8"))   # 回读校验
print(f"  fnpack.json 索引已加入: {appid}")
PY

cat <<DONE

✓ 已生成 $APPID 的全部文件

  应用详情     apps/$APPID.json
  FPK 工程     packages/$APPID/          (manifest + cmd/ + config/ + app/docker/ + wizard/)
  占位图标     assets/icons/$APPID.png
               packages/$APPID/ICON.PNG, ICON_256.PNG

后续步骤：
  1) 编辑 apps/$APPID.json 与 packages/$APPID/manifest，补全 desc 等描述
  2) 用真实图标替换 assets/icons/$APPID.png 与 packages/$APPID/ICON*.PNG
  3) 按需修改 packages/$APPID/app/docker/docker-compose.yaml 的 volumes / environment
  4) 本地出包：cd packages/$APPID && fnpack build
  5) 发布：打 tag 触发 CI —— git tag v1.0.0 && git push origin v1.0.0
     （CI 会自动构建 FPK、回填 sha256/size、发 Release）
  6) 提交源码：git add -A && git commit -m "add $APPID" && git push

校验：python3 scripts/verify_source.py
DONE
