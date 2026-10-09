"""反向代理：把 /p/<appid>/... 转发到容器内 127.0.0.1:<port>。

面板只对外暴露一个端口，所有子应用都经由这里跳转访问，
因此不需要额外映射端口，也不需要 docker.sock。
"""
from __future__ import annotations

import re

import httpx
from fastapi import Request, Response

# 逐跳首部，转发时必须剔除
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}

# 保守地重写 HTML 中的「根相对」资源路径：仅 href/src/action 且以 "/" 开头（非 //、非绝对 URL）
_ATTR_RE = re.compile(rb'(\b(?:href|src|action)\s*=\s*["\'])(/(?!/))', re.IGNORECASE)


def _upstream_base(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _rewrite_location(value: str, prefix: str, port: int) -> str:
    """把上游返回的根相对跳转改写成带前缀的形式，避免跳出面板。"""
    if value.startswith("/") and not value.startswith("//"):
        return prefix.rstrip("/") + value
    for base in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
        if value.startswith(base):
            return prefix.rstrip("/") + value[len(base):]
    return value


async def forward(request: Request, prefix: str, rest_path: str, port: int, timeout: float) -> Response:
    """prefix 形如 /p/<appid>，rest_path 是前缀之后的部分（可含查询串）。"""
    url = f"{_upstream_base(port)}/{rest_path.lstrip('/')}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["X-Forwarded-Prefix"] = prefix.rstrip("/")
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Proto"] = request.url.scheme

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            upstream = await client.request(
                request.method, url, headers=headers, content=body or None,
            )
    except httpx.HTTPError as exc:
        return Response(
            content=_error_page(prefix, port, str(exc)),
            status_code=502, media_type="text/html; charset=utf-8",
        )

    out_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP
    }
    if "location" in upstream.headers:
        out_headers["location"] = _rewrite_location(
            upstream.headers["location"], prefix, port,
        )

    content = upstream.content
    ctype = upstream.headers.get("content-type", "")
    if "text/html" in ctype and content:
        content = _ATTR_RE.sub(rb"\1" + prefix.rstrip("/").encode() + rb"\2", content)

    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=ctype or None,
    )


def _error_page(prefix: str, port: int, detail: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>无法访问子应用</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f1216;color:#e6edf3;font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.box{{max-width:520px;padding:32px 36px;background:#161b22;border:1px solid #262d36;border-radius:14px}}
h1{{font-size:17px;margin:0 0 12px}}code{{color:#7ee787}}
p{{color:#9aa7b4;margin:8px 0}}a{{color:#58a6ff}}
</style></head><body><div class="box">
<h1>子应用暂时无法访问</h1>
<p>面板已尝试连接容器内 <code>127.0.0.1:{port}</code>，但未得到响应。</p>
<p>常见原因：应用未启动、启动失败、或未监听该端口。</p>
<p>请在面板中查看该应用的<strong>日志</strong>确认原因。</p>
<p><a href="{prefix.rstrip('/')}/">重试</a></p>
<p style="font-size:12px;color:#6e7b8b">详情：{detail}</p>
</div></body></html>"""
