"""反向代理：把 /p/<appid>/... 转发到容器内 127.0.0.1:<port>。

面板只对外暴露一个端口，所有子应用都经由这里跳转访问，
因此不需要额外映射端口，也不需要 docker.sock。

「根路径依赖」按代价从低到高分三档处理：
- 静态资源写死根路径（href/src）→ 重写 HTML 属性即可，见 _ATTR_RE；
- 运行时由 JS 拼出来的根相对接口地址 → 重写不了，只能注入 shim 兜住，见 SHIM_PATH；
- 连 shim 也兜不住的（另有 WebSocket 等非 HTTP 流量）→ 条目标 expose_port，
  干脆不走反代，改用独立端口直连。
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

# ---- 路径前缀 shim（prefix_api）--------------------------------------------
#
# 为什么需要它：_ATTR_RE 只能重写 HTML 里「静态写死」的 href/src，管不到运行时
# 拼出来的地址。典型是单页应用把接口写成根相对再交给 fetch：
#
#     new URL('/api/v2/capabilities', location.origin)
#
# 页面挂在 /p/<id>/ 下时 location.origin 是**面板**的源，于是请求打到面板根路径
# /api/v2/capabilities —— 面板返回 404，前端拿不到数据。表现很有迷惑性：
# js/css 都 200、页面骨架渲染出来了，但接口全 404，界面上是一片错误文案或空白。
#
# 修法：往 HTML 里注入一段同源脚本，在请求真正发出前把前缀补回去。只处理
# 「根相对、且尚未带前缀」的地址，跨源 / 绝对 URL / 协议相对 //host 一律不碰。
#
# 为什么是一个独立文件而不是内联 <script>：这类应用的 CSP 通常是
# `script-src 'self'`（不含 'unsafe-inline'），内联脚本会被浏览器直接拒掉；
# 同源外部文件则放行。所以 shim 由面板自己提供，用 <script src> 引。
SHIM_PATH = "__devhub/prefix-shim.js"

_TAG_HEAD_RE = re.compile(rb"<head\b[^>]*>", re.IGNORECASE)
_TAG_BODY_RE = re.compile(rb"<body\b[^>]*>", re.IGNORECASE)

# 用 __PREFIX__ 占位而不是 str.format：脚本里全是 {} 花括号，format 会炸。
_SHIM_JS = """(function () {
  "use strict";
  var PREFIX = "__PREFIX__";

  // 应用拼接口地址有两种常见写法，都要覆盖：
  //   1) 直接给根相对串 —— fetch('/api/x')、'/api/' + name
  //   2) 先绝对化再发 —— new URL('/api/x', location.origin).toString()
  //      （AIVideoStudio 的前端就是第 2 种，只认第 1 种会漏掉全部请求）
  // 跨源、协议相对 //host、以及已经带了前缀的地址一律原样放行。
  function inScope(abs) {
    if (abs.indexOf(PREFIX + "/") === 0) { return null; }
    return PREFIX + abs;
  }

  function fix(u) {
    if (typeof u !== "string" || u === "") { return u; }
    if (u.charAt(0) === "/") {
      return u.charAt(1) === "/" ? u : (inScope(u) || u);
    }
    var origin = location.origin;
    if (u.indexOf(origin + "/") === 0) {
      var path = u.slice(origin.length);
      var fixed = inScope(path);
      return fixed === null ? u : origin + fixed;
    }
    return u;
  }

  var nativeFetch = window.fetch;
  if (typeof nativeFetch === "function") {
    window.fetch = function (input, init) {
      if (typeof input === "string") {
        return nativeFetch.call(window, fix(input), init);
      }
      if (input && typeof input === "object" && typeof input.url === "string") {
        var url = fix(input.url);
        if (url !== input.url) {
          try {
            return nativeFetch.call(window, new Request(url, input), init);
          } catch (e) {
            /* body 已被读取、无法克隆时退回原请求 */
          }
        }
      }
      return nativeFetch.apply(window, arguments);
    };
  }

  var nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var args = Array.prototype.slice.call(arguments);
    if (args.length > 1) { args[1] = fix(args[1]); }
    return nativeOpen.apply(this, args);
  };
})();
"""


def prefix_shim_js(prefix: str) -> bytes:
    return _SHIM_JS.replace("__PREFIX__", prefix.rstrip("/")).encode("utf-8")


def _inject_shim(html: bytes, prefix: str) -> bytes:
    """把 shim 的 <script src> 插到尽可能靠前的位置（head 之后，退而求其次 body 之后）。

    必须排在应用自己的脚本之前：应用是 <script type="module">（默认 defer），
    而这个标签是解析期同步执行的普通脚本，插在 head 里就一定是先跑的那个。
    """
    tag = ('<script src="%s/%s"></script>' % (prefix.rstrip("/"), SHIM_PATH)).encode()
    for rx in (_TAG_HEAD_RE, _TAG_BODY_RE):
        match = rx.search(html)
        if match:
            return html[:match.end()] + tag + html[match.end():]
    return tag + html


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


async def forward(request: Request, prefix: str, rest_path: str, port: int, timeout: float,
                  prefix_api: bool = False) -> Response:
    """prefix 形如 /p/<appid>，rest_path 是前缀之后的部分（可含查询串）。

    prefix_api=True 时额外做两件事：对外提供 shim 文件本身，并在 HTML 里注入它的
    <script src>。详见模块上方 SHIM_PATH 处的说明。
    """
    if prefix_api and rest_path.strip("/") == SHIM_PATH:
        return Response(
            content=prefix_shim_js(prefix),
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

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
        if prefix_api:
            # 顺序要紧：先重写属性、再注入 shim。反过来的话，新插入的那个
            # src="/p/<id>/__devhub/..." 会被 _ATTR_RE 再补一次前缀。
            content = _inject_shim(content, prefix)

    return Response(
        content=content,
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=ctype or None,
    )


def _direct_page(app_id: str, port: int, target: str, running: bool = True) -> str:
    """「独立端口直连」应用的提示页。

    这类应用的仪表盘把资源与 API 地址写死成根路径（典型是 Octop 前端用的
    window.location.host + /api/...），挂在 /p/<id>/ 前缀下必然 404，
    所以不走代理，改为提示用户打开它独占的那个端口。

    running=False 时补一句未运行提示：否则用户打开这个地址会直接连接被拒，
    误以为端口没发布。
    """
    warn = "" if running else (
        '<p style="color:#e3b341">该应用当前<strong>未运行</strong>，'
        '请先在面板卡片上点「启动」，否则打开下面的地址会连接失败。</p>'
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>请使用独立端口访问</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f1216;color:#e6edf3;font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.box{{max-width:560px;padding:32px 36px;background:#161b22;border:1px solid #262d36;border-radius:14px}}
h1{{font-size:17px;margin:0 0 12px}}code{{color:#7ee787}}
p{{color:#9aa7b4;margin:8px 0}}a{{color:#58a6ff}}
.go{{display:inline-block;margin-top:14px;padding:8px 16px;border-radius:8px;
background:#2f81f7;color:#fff;text-decoration:none;font-size:14px}}
</style></head><body><div class="box">
<h1>该应用需要独立端口访问</h1>
<p><code>{app_id}</code> 的控制台把资源与接口地址写死在根路径上，无法挂在
<code>/p/{app_id}/</code> 这样的路径前缀下（会全部 404）。</p>
<p>面板已在容器内把它映射到独立端口 <code>{port}</code>，请直接打开：</p>
{warn}<p><a class="go" href="{target}">{target}</a></p>
<p style="font-size:12px;color:#6e7b8b">面板卡片上的「打开」按钮也会跳到这个地址。</p>
</div></body></html>"""


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
