#!/usr/bin/env bash
#
# 飞牛 FnDepot 多应用脚手架
# 在「一个仓库多个应用」结构下，输入少量参数即可生成某应用所需的全部文件，并写回 fnpack.json 索引。
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
#   platform     架构，逗号分隔（可选，默认 x86,arm）
#
# 示例:
#   ./scripts/new-app.sh comfyui "ComfyUI" "AI赋能" 8188 "x86,arm"
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="main"

usage() { echo "用法: $0 <appid> <display_name> <category> [port] [platform]"; exit 1; }
[ "$#" -lt 3 ] && usage

APPID="$1"; DISPLAY="$2"; CATEGORY="$3"; PORT="${4:-}"; PLATFORM="${5:-x86,arm}"

# ---- appid 校验 ----
if ! [[ "$APPID" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "✗ appid 非法：须以字母/数字开头，仅可含字母、数字、. _ -"; exit 1
fi

# ---- 分类校验（FnDepot 九大固定分类，不可自创）----
VALID_CATS="影音娱乐 系统工具 编程开发 AI赋能 生活服务 智能智控 教育学习 游戏地带 硬件驱动"
ok=0
for c in $VALID_CATS; do [ "$CATEGORY" = "$c" ] && ok=1; done
[ "$ok" -eq 0 ] && { echo "✗ 分类非法，可选: $VALID_CATS"; exit 1; }

# ---- 反查 GitHub 用户名（与 fnpack.json 的 source_info.author 保持一致）----
GITHUB_USER="$(python3 -c "import json;print(json.load(open('$REPO_ROOT/fnpack.json',encoding='utf-8'))['source_info']['author'])" 2>/dev/null || echo mayishidai)"

mkdir -p "$REPO_ROOT/apps" "$REPO_ROOT/assets/icons"

NOW="$(TZ=Asia/Shanghai date +"%Y-%m-%dT%H:%M:%S%:z" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"
ICON_URL="https://raw.githubusercontent.com/$GITHUB_USER/fnos-app-depot/$BRANCH/assets/icons/$APPID.png"
DL_URL="https://github.com/$GITHUB_USER/fnos-app-depot/releases/download/v1.0.0/$APPID.fpk"
PLAT_JSON="[$(echo "$PLATFORM" | sed 's/,/","/g; s/^/"/; s/$/"/')]"

# 1) 应用详情 JSON（拆分模式）
cat > "$REPO_ROOT/apps/$APPID.json" <<JSON
{
  "app_name": "$APPID",
  "display_name": "$DISPLAY",
  "desc": "请在此填写 $DISPLAY 的简介（支持 HTML，客户端会清理危险内容）。",
  "platform": $PLAT_JSON,
  "categories": ["$CATEGORY"],
  "icon_url": "$ICON_URL",
  "run_as": "package",
  "install_type": "",
  "is_docker": true,
  "service_port": "${PORT:-}",
  "releases": {
    "1.0.0": {
      "packages": {
        "all": {
          "download_url": "$DL_URL",
          "sha256": "",
          "size": 0
        }
      }
    }
  }
}
JSON

# 2) FPK 清单模板（fnpack 输入）
cat > "$REPO_ROOT/app_${APPID}.yml" <<YML
# 飞牛 FPK 清单模板（fnpack 输入）
#   fnpack build app_${APPID}.yml
# 镜像需先在应用主仓库启用 CI 自动构建发布到 ghcr.io/$GITHUB_USER/$APPID:latest
appid: $APPID
name: $DISPLAY
version: 1.0.0
image: ghcr.io/$GITHUB_USER/$APPID:latest
ports:
  - ${PORT:-5000}
environment:
  - PYTHONUNBUFFERED=1
volumes:
  - /app/config.json:/app/config.json
  - /app/data:/app/data
privileged: false
restart: unless-stopped
YML

# 3) docker-compose 手动部署
cat > "$REPO_ROOT/docker-compose.${APPID}.yml" <<YML
version: '3.8'
services:
  $APPID:
    image: ghcr.io/$GITHUB_USER/$APPID:latest
    container_name: $APPID
    ports:
      - "${PORT:-5000}:${PORT:-5000}"
    volumes:
      - ./data/$APPID:/app/data
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
YML

# 4) 占位图标（512x512）
python3 - "$REPO_ROOT/assets/icons/$APPID.png" "$DISPLAY" <<'PY'
import sys, os
from PIL import Image, ImageDraw, ImageFont
out, label = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(out), exist_ok=True)
img = Image.new('RGBA', (512, 512), (18, 22, 40, 255))
d = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 40)
except Exception:
    f = ImageFont.load_default()
d.ellipse([150, 140, 362, 352], fill=(99, 102, 241, 255))
d.ellipse([186, 176, 326, 316], fill=(236, 72, 153, 255))
d.text((256, 400), label[:16], font=f, fill=(255, 255, 255, 255), anchor='mm')
img.save(out)
print('icon ->', out, os.path.getsize(out), 'bytes')
PY

# 5) 写回 fnpack.json 索引（python 保证 JSON 合法）
python3 - "$REPO_ROOT/fnpack.json" "$APPID" "$NOW" <<'PY'
import sys, json
path, appid, now = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(path, encoding='utf-8'))
data.setdefault('apps', {})
data['apps'][appid] = {"details_url": f"apps/{appid}.json", "details_updated_at": now}
json.dump(data, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
json.load(open(path, encoding='utf-8'))  # 回读校验
print('fnpack.json 索引已加入:', appid)
PY

echo
echo "✓ 已生成 $APPID 相关文件，后续请："
echo "  1) 编辑 apps/$APPID.json：补全 desc、替换为真实图标、发布后回填 sha256 与 size"
echo "  2) 按需修改 app_$APPID.yml / docker-compose.$APPID.yml 的 volumes、env"
echo "  3) 构建并发布：fnpack build app_$APPID.yml，上传到本仓库 Release v1.0.0"
echo "  4) git add -A && git commit -m 'add <appid>' && git push"
