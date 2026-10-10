# Dev Hub —— 飞牛 fnOS 应用导航与管理面板
#
# 面板负责：clone/拉取各应用代码、以子进程方式启停、采集日志、反代跳转。
# 镜像内还要自带各子应用需要的运行时（子应用是直接跑在本容器里的进程）：
#   python3.12 —— FastAPI 类子应用；各自在应用目录里建独立 venv（见应用配置的 setup 命令），
#                 避免 AIVideoStudio 锁的 fastapi==0.128.2 和面板自己的 0.115.6 打架。
#   node 22    —— mini_games 后端用了 node:sqlite + --experimental-sqlite，要求 Node >= 22.5；
#                 Debian bookworm 自带的 nodejs 是 18，跑不起来，必须单独装。
#   esbuild    —— mini_games 的 H5 打包脚本（tools/build-sheep.mjs）通过 PATH 调用它。
#   pnpm 9     —— AIVideoStudio 的前端（Vue+Vite）用仓库自带的 pnpm-lock.yaml 构建。
#                 固定 9.x：它的 lockfileVersion 是 9.0；且 pnpm 10 默认拦掉依赖的
#                 postinstall 脚本，esbuild 的平台二进制就装不上、vite build 会失败。
#   ffmpeg     —— AIVideoStudio 的本地成片合成（ffmpeg / ffprobe）。
FROM python:3.12-slim

# HOME 必须显式给：官方 python 镜像不设 HOME，而飞牛以 `run-as: package` 的
# 非 root uid 启动容器，该 uid 在镜像 /etc/passwd 里没有条目 —— npm / uv / pip / git
# 全都定位不到家目录（npm 会以 uv_os_homedir ENOENT 直接崩）。/data 是随卷持久化的
# 可写目录，缓存留在这里还能让 uv 对 .venv 走硬链接（跨文件系统会退化成拷贝或报错）。
# 官方 Octop 的 fnOS 包同样钉了 HOME=/data。
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEVHUB_DATA=/data \
    HOME=/data \
    DEBIAN_FRONTEND=noninteractive

# git：代码更新；ffmpeg：媒体合成；curl/gnupg/xz-utils：装 Node 源与健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg xz-utils ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Node 22 + 全局 esbuild / pnpm（版本号打印出来，构建日志里能直接确认装对了）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g esbuild pnpm@9 \
    && node -v \
    && esbuild --version \
    && pnpm -v \
    && ffmpeg -version | head -1 \
    && git config --system --add safe.directory '*'

WORKDIR /opt/dev-hub

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY server ./server
COPY web ./web

VOLUME ["/data"]
EXPOSE 8890

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8890/api/health || exit 1

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8890"]
