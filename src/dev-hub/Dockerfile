# Dev Hub —— 飞牛 fnOS 应用导航与管理面板
#
# 面板负责：clone/拉取各应用代码、以子进程方式启停、采集日志、反代跳转。
# 因此镜像内需自带 git 与常见运行时（python3/node），供被管理的子应用使用。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEVHUB_DATA=/data

# git：代码更新；node/npm：JS 类子应用；curl：健康检查与子应用依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
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
