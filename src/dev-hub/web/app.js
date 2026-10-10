/* Dev Hub 面板前端：应用卡片、启停、更新、日志、设置 */

const $ = (sel) => document.querySelector(sel);
const api = async (path, options = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error((data && data.detail) || `请求失败（${res.status}）`);
  return data;
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(message, type = "ok") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "err" ? 6000 : 3000);
}

/* ------------------------------------------------------------------ 数据 */

let apps = [];
let editingId = null;
let logTimer = null;
let currentLogApp = null;

async function refresh() {
  try {
    apps = await api("/api/apps");
    render();
  } catch (err) {
    toast(`加载失败：${err.message}`, "err");
  }
}

/* ------------------------------------------------------------------ 渲染 */

const STATE_TEXT = { running: "运行中", stopped: "已停止", exited: "异常退出" };

function relativeTime(ts) {
  if (!ts) return "尚未检测";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚检测";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前检测`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前检测`;
  return `${Math.floor(diff / 86400)} 天前检测`;
}

function render() {
  const grid = $("#grid");
  $("#empty").hidden = apps.length > 0;
  grid.hidden = apps.length === 0;

  const running = apps.filter((a) => a.runtime.status === "running").length;
  const updates = apps.filter((a) => (a.git.behind || 0) > 0).length;
  $("#summary").innerHTML = `
    <span class="chip">应用 <b>${apps.length}</b></span>
    <span class="chip">运行中 <b>${running}</b></span>
    <span class="chip">可更新 <b>${updates}</b></span>`;

  grid.innerHTML = apps.map(cardHTML).join("");
}

function cardHTML(app) {
  const st = app.runtime.status;
  const git = app.git || {};
  const behind = git.behind || 0;
  const disabled = app.enabled === false;
  const setup = app.setup_state || "idle";
  const hasSetup = !!(app.setup || "").trim();
  const running = st === "running";
  const badges = [];

  // 启用/依赖状态优先展示，其余的是 git 状态。
  // 禁用态不放徽章：右上角状态胶囊已经写了「待启用」，重复一遍是噪音。
  if (!disabled) {
    if (setup === "running") {
      badges.push(`<span class="badge setup"><span class="spin">◌</span> 安装依赖中</span>`);
    } else if (setup === "failed") {
      badges.push(`<span class="badge failed">依赖安装失败</span>`);
    } else if (hasSetup && setup !== "ok") {
      badges.push(`<span class="badge muted">依赖未安装</span>`);
    }
  }

  if (!git.cloned) badges.push(`<span class="badge muted">未克隆</span>`);
  else {
    if (behind > 0) badges.push(`<span class="badge update">可更新 ${behind} 个提交</span>`);
    else if (git.behind === 0) badges.push(`<span class="badge new">已是最新</span>`);
    else badges.push(`<span class="badge muted">未检测远端</span>`);
    if (git.ahead > 0) badges.push(`<span class="badge">本地领先 ${git.ahead}</span>`);
    if (git.dirty) badges.push(`<span class="badge dirty">有未提交改动</span>`);
    badges.push(`<span class="badge">${esc(git.branch || app.branch)}</span>`);
  }

  // 独立端口直连的应用：跳转地址是 http://<面板主机>:<port>/，不走 /p/<id>/
  if (app.expose_port) {
    if (app.expose_port_published === false) {
      badges.push(`<span class="badge failed">直连端口未发布</span>`);
    } else {
      badges.push(`<span class="badge setup">独立端口直连</span>`);
    }
  }

  const avatar = app.icon
    ? `<img class="avatar" src="${esc(app.icon)}" alt="" onerror="this.outerHTML='<div class=\\'avatar\\'>${esc((app.name || "?").slice(0, 1).toUpperCase())}</div>'">`
    : `<div class="avatar">${esc((app.name || "?").slice(0, 1).toUpperCase())}</div>`;

  const setupBtn = !disabled && hasSetup && setup !== "running"
    ? `<button class="btn small" data-act="setup" data-id="${app.id}">${setup === "idle" ? "安装依赖" : "重装依赖"}</button>`
    : "";

  // expose_port 的应用必须直连，/p/<id>/ 只会返回一张「请走独立端口」的引导页，
  // 所以有 external_url 时优先用它；拿不到 origin（比如命令行直连）就退回引导页。
  const openHref = app.expose_port && app.external_url ? app.external_url : app.url;
  const openTitle = app.expose_port && app.external_url
    ? `独立端口直连：${app.external_url}${app.expose_port_published === false ? "（该端口未在 compose 中发布，可能连不上）" : ""}`
    : "";

  return `
  <article class="card ${behind > 0 ? "has-update" : ""} ${disabled ? "is-disabled" : ""}">
    <div class="card-head">
      ${avatar}
      <div class="card-title">
        <h3 title="${esc(app.name)}">${esc(app.name)}</h3>
        <p>${esc(app.desc || app.repo)}</p>
      </div>
      <span class="state ${disabled ? "off" : st}"><i class="dot"></i>${disabled ? "待启用" : (STATE_TEXT[st] || st)}</span>
    </div>

    <div class="badges">${badges.join("")}</div>

    <div class="meta">
      <span class="ellipsis" title="${esc(app.repo)}">${esc(app.repo)}</span>
      <span class="ellipsis">提交 <code>${esc(git.head || "—")}</code> ${esc(git.subject || "")}</span>
      <span>端口 <code>${app.port}</code> · ${relativeTime(app.git_checked_at)}</span>
    </div>

    <div class="card-actions">
      ${running
        ? `<button class="btn small" data-act="stop" data-id="${app.id}">停止</button>
           <button class="btn small" data-act="restart" data-id="${app.id}">重启</button>`
        : `<button class="btn small primary" data-act="start" data-id="${app.id}" ${disabled ? "disabled" : ""}>启动</button>`}
      ${setupBtn}
      <button class="btn small" data-act="update" data-id="${app.id}" ${behind > 0 && !disabled ? "" : "disabled"}>更新代码</button>
      <button class="btn small" data-act="check" data-id="${app.id}" ${disabled ? "disabled" : ""}>检查</button>
      <button class="btn small" data-act="logs" data-id="${app.id}">日志</button>
      ${disabled
        ? `<span class="btn small is-off" title="应用未启用">打开</span>`
        : `<a class="btn small" href="${esc(openHref)}" target="_blank" rel="noopener" ${openTitle ? `title="${esc(openTitle)}"` : ""}>打开</a>`}
      <button class="btn small ghost" data-act="edit" data-id="${app.id}">编辑</button>
    </div>
  </article>`;
}

/* ------------------------------------------------------------------ 事件 */

$("#grid").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const { act, id } = btn.dataset;
  const app = apps.find((a) => a.id === id);
  if (!app) return;

  if (act === "edit") return openAppModal(app);
  if (act === "logs") return openLogs(app);

  const labels = { start: "启动", stop: "停止", restart: "重启", update: "更新代码", check: "检查更新", setup: "安装依赖" };
  btn.disabled = true;
  const origin = btn.textContent;
  btn.innerHTML = `<span class="spin">◌</span>`;
  try {
    let result;
    if (act === "start" || act === "stop" || act === "restart" || act === "setup") {
      result = await api(`/api/apps/${id}/${act}`, { method: "POST" });
    } else if (act === "update") {
      result = await api(`/api/apps/${id}/update`, { method: "POST" });
    } else {
      result = await api(`/api/apps/${id}/check`, { method: "POST" });
    }
    if (act === "check") {
      const behind = result.git.behind || 0;
      toast(behind > 0 ? `${app.name}：落后远端 ${behind} 个提交` : `${app.name}：已是最新`);
    } else {
      toast(`${app.name}：${result.message || labels[act] + "成功"}`);
    }
    await refresh();
  } catch (err) {
    toast(`${app.name}：${err.message}`, "err");
    btn.disabled = false;
    btn.textContent = origin;
  }
});

$("#btn-check-all").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  btn.innerHTML = `<span class="spin">◌</span> 检测中`;
  try {
    await api("/api/check-all", { method: "POST" });
    toast("全部应用检查完成");
    await refresh();
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "检查全部更新";
  }
});

/* ------------------------------------------------------------------ 应用编辑 */

function openAppModal(app) {
  editingId = app ? app.id : null;
  $("#modal-app-title").textContent = app ? `编辑「${app.name}」` : "添加应用";
  $("#btn-delete-app").hidden = !app;
  $("#f-id").value = app ? app.id : "";
  $("#f-id").disabled = !!app;
  $("#f-name").value = app ? app.name : "";
  $("#f-repo").value = app ? app.repo : "";
  $("#f-branch").value = app ? app.branch : "main";
  $("#f-port").value = app ? app.port : "";
  $("#f-run").value = app ? app.run : "";
  $("#f-setup").value = app ? app.setup : "";
  $("#f-subdir").value = app ? app.subdir : "";
  $("#f-icon").value = app ? app.icon : "";
  $("#f-desc").value = app ? app.desc : "";
  $("#f-env").value = app ? Object.entries(app.env || {}).map(([k, v]) => `${k}=${v}`).join("\n") : "";
  $("#f-enabled").checked = app ? app.enabled !== false : true;
  $("#f-expose").checked = app ? !!app.expose_port : false;
  $("#f-prefix-api").checked = app ? !!app.prefix_api : false;
  $("#f-autostart").checked = app ? !!app.auto_start : true;
  $("#f-clone").checked = !app;
  $("#modal-app").hidden = false;
  setTimeout(() => $("#f-name").focus(), 30);
}

function parseEnv(text) {
  const out = {};
  text.split("\n").map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const i = line.indexOf("=");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  return out;
}

$("#btn-save-app").addEventListener("click", async () => {
  const payload = {
    id: $("#f-id").value.trim(),
    name: $("#f-name").value.trim(),
    repo: $("#f-repo").value.trim(),
    branch: $("#f-branch").value.trim() || "main",
    port: Number($("#f-port").value) || 0,
    run: $("#f-run").value.trim(),
    setup: $("#f-setup").value.trim(),
    subdir: $("#f-subdir").value.trim(),
    icon: $("#f-icon").value.trim(),
    desc: $("#f-desc").value.trim(),
    env: parseEnv($("#f-env").value),
    enabled: $("#f-enabled").checked,
    expose_port: $("#f-expose").checked,
    prefix_api: $("#f-prefix-api").checked,
    auto_start: $("#f-autostart").checked,
    clone_now: $("#f-clone").checked,
  };
  try {
    if (editingId) await api(`/api/apps/${editingId}`, { method: "PUT", body: JSON.stringify(payload) });
    else await api("/api/apps", { method: "POST", body: JSON.stringify(payload) });
    $("#modal-app").hidden = true;
    toast(editingId ? "配置已保存" : "应用已添加");
    await refresh();
  } catch (err) {
    toast(err.message, "err");
  }
});

$("#btn-delete-app").addEventListener("click", async () => {
  if (!editingId) return;
  const app = apps.find((a) => a.id === editingId);
  const purge = confirm(`确定删除「${app.name}」？\n\n点「确定」= 同时删除已克隆的代码目录\n点「取消」= 仅从面板移除，保留代码`);
  try {
    const res = await api(`/api/apps/${editingId}?purge=${purge}`, { method: "DELETE" });
    $("#modal-app").hidden = true;
    if (res && res.warning) toast(res.warning, "err");
    else toast("应用已删除");
    await refresh();
  } catch (err) {
    toast(err.message, "err");
  }
});

/* ------------------------------------------------------------------ 日志 */

async function loadLogs() {
  if (!currentLogApp) return;
  try {
    const data = await api(`/api/apps/${currentLogApp.id}/logs?lines=500`);
    const box = $("#logs-content");
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    box.textContent = data.log || "（暂无日志）";
    if (atBottom) box.scrollTop = box.scrollHeight;
  } catch (err) {
    $("#logs-content").textContent = err.message;
  }
}

function openLogs(app) {
  currentLogApp = app;
  $("#drawer-logs-title").textContent = `${app.name} · 日志`;
  $("#drawer-logs").hidden = false;
  loadLogs();
  clearInterval(logTimer);
  logTimer = setInterval(() => { if ($("#logs-follow").checked) loadLogs(); }, 3000);
}

$("#btn-clear-logs").addEventListener("click", async () => {
  if (!currentLogApp) return;
  await api(`/api/apps/${currentLogApp.id}/logs`, { method: "DELETE" });
  await loadLogs();
  toast("日志已清空");
});

/* ------------------------------------------------------------------ 设置 */

$("#btn-settings").addEventListener("click", async () => {
  const s = await api("/api/settings");
  $("#s-poll").value = s.poll_minutes;
  $("#s-port-start").value = s.port_start;
  $("#s-timeout").value = s.proxy_timeout;
  $("#s-token").value = "";
  $("#s-token").placeholder = s.github_token_set ? "已保存，留空则不修改" : "留空表示不使用";
  $("#s-clear-token").checked = false;
  $("#modal-settings").hidden = false;
});

$("#btn-save-settings").addEventListener("click", async () => {
  try {
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        poll_minutes: Number($("#s-poll").value) || 0,
        port_start: Number($("#s-port-start").value) || 19100,
        proxy_timeout: Number($("#s-timeout").value) || 30,
        github_token: $("#s-token").value.trim(),
        clear_token: $("#s-clear-token").checked,
      }),
    });
    $("#modal-settings").hidden = true;
    toast("设置已保存");
  } catch (err) {
    toast(err.message, "err");
  }
});

/* ------------------------------------------------------------------ 操作记录 */

$("#btn-events").addEventListener("click", async () => {
  $("#modal-events").hidden = false;
  try {
    const data = await api("/api/events?lines=300");
    const box = $("#events-content");
    box.textContent = data.log || "（暂无记录）";
    box.scrollTop = box.scrollHeight;
  } catch (err) {
    $("#events-content").textContent = err.message;
  }
});

/* ------------------------------------------------------------------ 通用 */

$("#btn-add").addEventListener("click", () => openAppModal(null));

document.addEventListener("click", (ev) => {
  const closer = ev.target.closest("[data-close]");
  if (!closer) return;
  const host = closer.closest(".modal, .drawer");
  if (host) host.hidden = true;
  clearInterval(logTimer);
  currentLogApp = null;
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    document.querySelectorAll(".modal, .drawer").forEach((el) => { el.hidden = true; });
    clearInterval(logTimer);
    currentLogApp = null;
  }
});

document.querySelectorAll(".modal").forEach((modal) => {
  modal.addEventListener("mousedown", (ev) => { if (ev.target === modal) modal.hidden = true; });
});

/* ------------------------------------------------------------------ 启动 */

refresh();
setInterval(refresh, 5000);
