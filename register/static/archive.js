// HTML 转义：DB 文本进入 innerHTML 前统一编码，降低 XSS 风险。
function escapeHtml(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
var E = escapeHtml;

function renderBody(value) {
  const text = value == null || value === "" ? "暂无正文。" : String(value);
  return E(text).replace(/https?:\/\/[^\s<>"']+/g, function (match) {
    const trailing = (match.match(/[),，。；]+$/) || [""])[0];
    const url = trailing ? match.slice(0, -trailing.length) : match;
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${trailing}`;
  });
}

// 分类导航由 /api/archive.json 下发，后端硬保证 <=10（含「全部」）。
let CATS = [{ id: "all", label: "全部" }];

// 统计贴纸由 API 实时下发；坐标仅为排版常量。
let STATS = [];
const STAT_POS = [
  { x: 210, y: 594, r: -1.5 }, { x: 340, y: 598, r: 1.2 },
  { x: 470, y: 592, r: -0.8 }, { x: 600, y: 597, r: 1.6 },
  { x: 730, y: 593, r: -1.2 },
];

const viewport = document.getElementById("viewport");
const hit = document.getElementById("hit");
const stage = document.getElementById("stage");
const nav = document.getElementById("nav");
const countEl = document.getElementById("count");
const statusEl = document.getElementById("archiveStatus");
const statusText = document.getElementById("archiveStatusText");
const retryButton = document.getElementById("archiveRetry");
const ARCHIVE_API = (document.currentScript && document.currentScript.getAttribute("data-archive-api")) || window.ARCHIVE_API || "";
let pieces = [];
let cursor = 0;
let activeCat = "all";
let lastWheel = 0;
let loadError = false;

function pad(n) { return String(n).padStart(2, "0"); }
function maxZ() { return Math.max(...pieces.map(p => p.z)); }
function isCompactLayout() {
  return window.matchMedia ? window.matchMedia("(max-width: 900px)").matches : window.innerWidth <= 900;
}

function face(p) {
  const tags = (p.tags || []).map(t => `<span class="tag">${E(t)}</span>`).join("");
  const status = `<span class="status ${E(p.st)}"><i></i>${E(p.status)}</span>`;
  const head = `<div class="idtag">${E(p.code)}</div><div class="year">${E(p.year)}</div>`;
  switch (p.kind) {
    case "poster":
      return `<div class="face poster-face sheet-shadow">${head}<div class="ring"></div>
        <div class="kicker" style="margin-top:18px">Key finding</div>
        <div class="big">${E(p.metric)}</div>
        <div class="title" style="margin-top:12px;font-size:15px">${E(p.title)}</div>
        <div class="summary" style="margin-top:5px">${E(p.summary)}</div>
        <div class="foot"><div class="tags">${tags}</div>${status}</div>
        <div class="poster-slip">${E(p.owner)} · ${E(p.metricLabel)}</div></div><span class="expand">展开 ↗</span>`;
    case "sheet": {
      const rows = (p.rows || []).slice(0, 3).map(r => `<div class="row"><b>${E(r[0])}</b><span>${E(r[1])}</span></div>`).join("");
      return `<div class="face sheet-face sheet-shadow">${head}
        <div class="kicker">Lab notebook · ${E(p.metric)} ${E(p.metricLabel)}</div>
        <div class="rows">${rows}</div><div class="red-ring"></div>
        <div class="red-note" style="margin-top:auto">${E(p.red)}</div>
        <div class="summary clamp1" style="margin-top:5px">${E(p.summary)}</div>
        <div class="foot" style="margin-top:5px"><div class="tags">${tags}</div>${status}</div></div><span class="expand">展开 ↗</span>`;
    }
    case "ticket":
      return `<div class="face ticket-face sheet-shadow"><div class="hazard"><span>ADMIT</span></div>
        <div class="ticket-main"><div><div class="kicker">${E(p.code)} · ${E(p.year)}</div><div class="admit">${E(p.metric)}</div></div>
        <div class="title clamp1" style="font-size:13px">${E(p.title)}</div>
        <div class="summary clamp1" style="font-size:9px">${E(p.summary)}</div>
        <div class="ticket-meta"><div><small>团队</small><b>${E(String(p.owner || "").split(" · ")[0])}</b></div><div><small>状态</small><b>${E(p.status)}</b></div><div><small>席位</small><b>A-12</b></div></div></div>
        <div class="barcode" aria-hidden="true"></div></div><span class="expand">展开 ↗</span>`;
    case "card":
      return `<div class="face card-face">${head}<div class="mark">${E(p.title)}</div>
        <div class="lines">${E(p.owner)}<br />${E(p.metric)} ${E(p.metricLabel)}<br />${E(p.status)} · ${E(p.year)}</div></div><span class="expand">展开 ↗</span>`;
    case "photo":
      return `<div class="face photo-face sheet-shadow">${head}<div class="img"></div>
        <figcaption>${E(p.metric)} ${E(p.metricLabel)}</figcaption>
        <div class="title" style="margin-top:6px;font-size:15px">${E(p.title)}</div>
        <div class="summary" style="margin-top:4px">${E(p.summary)}</div>
        <div class="foot" style="margin-top:auto;display:flex;justify-content:space-between"><div class="tags">${tags}</div>${status}</div>
        <div class="meta" style="margin-top:4px">${E(p.owner)}</div></div><span class="expand">展开 ↗</span>`;
    case "note":
      return `<div class="face note-face sheet-shadow">${head}<div class="kicker">Memo · ${E(p.code)}</div>
        <div class="hand-big">${E(p.metric)}</div><div class="under">${E(p.metricLabel)}</div>
        <div class="title" style="font-size:16px;margin-top:8px">${E(p.title)}</div>
        <div class="summary" style="margin-top:4px">${E(p.summary)}</div>
        <div class="red-note" style="margin-top:auto">${E(p.red)}</div>
        <div class="foot" style="margin-top:4px;display:flex;justify-content:space-between"><div class="tags">${tags}</div>${status}</div>
        <div class="meta" style="margin-top:4px">${E(p.owner)}</div></div><span class="expand">展开 ↗</span>`;
    case "journal":
      return `<div class="face journal-face sheet-shadow">${head}<div class="kicker">Journal · ${E(p.year)}</div>
        <div class="title">${E(p.title)}</div><div class="summary" style="margin-top:7px">${E(p.summary)}</div>
        <div class="tags" style="margin-top:8px">${tags}</div>
        <div class="refs">${E(p.refs)}<br />${E(p.metric)} ${E(p.metricLabel)} · ${E(p.owner)}</div>
        <div class="read">展开摘要 ↗</div>${status}</div>`;
    case "blueprint":
      return `<div class="face blueprint-face sheet-shadow">${head}<div class="kicker">Blueprint · ${E(p.code)}</div>
        <div class="title clamp2" style="margin-top:4px">${E(p.title)}</div>
        <div class="diagram"><span class="figure">${E(p.metric)}</span></div>
        <div class="summary clamp2" style="font-size:8px">${E(p.summary)}</div>
        <div class="meta" style="margin-top:4px;font-size:8px">${E(p.metricLabel)} · ${E(p.owner)}</div>${status}</div><span class="expand">展开 ↗</span>`;
  }
  return "";
}

function build() {
  hit.innerHTML = pieces.map((p, i) =>
    `<article class="piece" data-i="${i}" tabindex="0" role="button" aria-haspopup="dialog" aria-controls="detailOverlay" aria-expanded="false" aria-label="${E(p.title)}"><div class="piece-sheet"><span class="piece-category">${E(p.catLabel || "其他")}</span>${face(p)}</div></article>`
  ).join("") + (pieces.length ? STATS.slice(0, 5).map((s, i) => {
    const g = STAT_POS[i % STAT_POS.length];
    return `<div class="stat" style="transform:translate(${g.x}px,${g.y}px) rotate(${g.r}deg)"><b>${E(s.value)}</b><span>${E(s.label)}</span></div>`;
  }).join("") : "") + (pieces.length
    ? `<div class="stat-note">数据实时统计 · 来自平台公开分享</div>`
    : `<div class="archive-empty">${loadError ? "公开分享暂时无法加载" : "暂无公开分享的 idea，来发布第一个吧"}</div>`);

  hit.querySelectorAll(".piece").forEach(el => bindPiece(el));
  nav.innerHTML = CATS.slice(0, 10).map(c =>
    `<button type="button" data-cat="${E(c.id)}" aria-pressed="${c.id === activeCat}" class="${c.id === activeCat ? "active" : ""}"><span class="slot">${c.id === activeCat ? '<i class="dot"></i>' : ""}</span>${E(c.label)}</button>`
  ).join("");
  nav.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    activeCat = b.dataset.cat;
    nav.querySelectorAll("button").forEach(x => {
      const on = x === b;
      x.classList.toggle("active", on);
      x.setAttribute("aria-pressed", String(on));
      x.querySelector(".slot").innerHTML = on ? '<i class="dot"></i>' : "";
    });
    paint();
  }));
  paint();
}

function paint() {
  hit.querySelectorAll(".piece").forEach((el, i) => {
    const p = pieces[i];
    el.style.width = p.w + "px";
    el.style.height = p.h + "px";
    el.style.zIndex = p.z;
    el.style.setProperty("--piece-r", `${p.r}deg`);
    el.style.transform = `translate(${p.x}px, ${p.y}px) rotate(${p.r}deg)`;
    el.classList.toggle("is-active", i === cursor);
    el.classList.toggle("is-dim", activeCat !== "all" && p.cat !== activeCat && !(p.tags || []).includes(activeCat));
  });
  countEl.textContent = pieces.length ? `${pad(Math.min(cursor + 1, pieces.length))} / ${pad(pieces.length)}` : `00 / 00`;
}

function bindPiece(el) {
  const i = Number(el.dataset.i);
  let origin = null;
  el.addEventListener("pointerdown", e => {
    if (e.button !== 0 || isCompactLayout()) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    el.classList.add("is-dragging");
    pieces[i].z = maxZ() + 1;
    origin = { x: e.clientX, y: e.clientY, px: pieces[i].x, py: pieces[i].y, moved: false };
    paint();
  });
  el.addEventListener("pointermove", e => {
    if (!origin || !el.hasPointerCapture?.(e.pointerId)) return;
    const s = scale();
    const dx = e.clientX - origin.x, dy = e.clientY - origin.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) origin.moved = true;
    pieces[i].x = origin.px + dx / s;
    pieces[i].y = origin.py + dy / s;
    el.style.transform = `translate(${pieces[i].x}px, ${pieces[i].y}px) rotate(${pieces[i].r}deg)`;
  });
  const up = () => {
    const wasClick = origin && !origin.moved;
    el.classList.remove("is-dragging");
    origin = null;
    if (wasClick) openDetail(i, el);
  };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", () => { el.classList.remove("is-dragging"); origin = null; });
  el.addEventListener("click", () => {
    if (isCompactLayout()) openDetail(i, el);
  });
  el.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!e.repeat) openDetail(i, el);
    }
  });
  el.addEventListener("focus", () => { cursor = i; paint(); });
}

function step(dir) {
  if (!pieces.length) return;
  cursor = (cursor + dir + pieces.length) % pieces.length;
  pieces[cursor].z = maxZ() + 1;
  paint();
}

function shuffle() {
  pieces.forEach(p => {
    p.x += (Math.random() - .5) * 64;
    p.y += (Math.random() - .5) * 46;
    p.r += (Math.random() - .5) * 9;
    p.z = 8 + Math.floor(Math.random() * 30);
  });
  paint();
}

// 统一的数据应用函数（全局作用域，供 API 加载与复位共用）。
let lastPayload = null;
function applyData(d) {
  if (!d) return;
  lastPayload = d;
  pieces = Array.isArray(d.items) ? d.items : [];
  STATS = Array.isArray(d.stats) ? d.stats : [];
  CATS = pieces.length
    ? (Array.isArray(d.tags) && d.tags.length ? d.tags : [{ id: "all", label: "全部" }]).slice(0, 10)
    : [{ id: "all", label: "全部" }];
  cursor = 0;
  activeCat = "all";
  build();
}

// 复位：清空位置改动后重新应用真实数据，绝不回退写死示例。
function reset() {
  var payload = lastPayload || window.__ARCHIVE__;
  if (payload) {
    applyData(payload);
  } else {
    pieces = []; STATS = []; CATS = [{ id: "all", label: "全部" }];
    cursor = 0; build();
  }
}

function scale() {
  return Math.min(window.innerWidth / 1240, window.innerHeight / 760);
}
function fit() {
  stage.style.transform = isCompactLayout() ? "" : `scale(${scale()})`;
}
window.addEventListener("resize", fit);

hit.addEventListener("wheel", e => {
  if (isCompactLayout()) return;
  e.preventDefault();
  const now = performance.now();
  if (now - lastWheel < 260) return;
  if (Math.abs(e.deltaY) < 6 && Math.abs(e.deltaX) < 6) return;
  lastWheel = now;
  step((e.deltaY || e.deltaX) > 0 ? 1 : -1);
}, { passive: false });

document.getElementById("next").addEventListener("click", () => step(1));
document.getElementById("shuffle").addEventListener("click", shuffle);
document.getElementById("reset").addEventListener("click", reset);
stage.addEventListener("dblclick", e => { if (e.target.closest(".join-card")) return; reset(); });

const overlay = document.getElementById("detailOverlay");
const sheet = document.getElementById("detailSheet");
let detailIndex = -1;
let detailReturnFocus = null;

function openDetail(i, trigger) {
  if (!pieces.length || !pieces[i]) return;
  const wasOpen = detailIndex >= 0;
  const focusedId = wasOpen && sheet.contains(document.activeElement) ? document.activeElement.id : "";
  if (!wasOpen) detailReturnFocus = trigger || document.activeElement;
  detailIndex = i;
  const p = pieces[i];
  sheet.innerHTML = `
    <button class="close" id="dClose" type="button" aria-label="关闭">×</button>
    <div class="d-head"><span class="d-code">${E(p.code)}</span><span class="d-kind">${E(p.catLabel || "其他")}</span><span class="d-year">${E(p.year)}</span></div>
    <h2 id="dTitle">${E(p.title)}</h2>
    <div class="d-metric-row"><span class="d-metric">${E(p.metric)}</span><span class="d-metric-label">${E(p.metricLabel)}</span></div>
    <div class="d-summary d-content">${renderBody(p.content || p.summary)}</div>
    <div class="d-tags">${(p.tags || []).map(t => `<span class="tag">${E(t)}</span>`).join("")}</div>
    <div class="d-foot"><span class="d-owner">${E(p.owner)} · ${E(p.status)}</span>
      <span class="d-nav"><button id="dPrev" type="button">← 上一项</button><button id="dNext" type="button">下一项 →</button></span>
    </div>
    <div class="d-source">数据源：平台公开分享</div>`;

  if (!wasOpen) {
    viewport.inert = true;
    viewport.setAttribute("aria-hidden", "true");
    overlay.inert = false;
    overlay.setAttribute("aria-hidden", "false");
  }
  hit.querySelectorAll(".piece").forEach((el, index) => el.setAttribute("aria-expanded", String(index === i)));
  overlay.classList.add("open");
  document.getElementById("dClose").addEventListener("click", closeDetail);
  document.getElementById("dPrev").addEventListener("click", () => openDetail(pieces.length ? (detailIndex - 1 + pieces.length) % pieces.length : 0));
  document.getElementById("dNext").addEventListener("click", () => openDetail(pieces.length ? (detailIndex + 1) % pieces.length : 0));
  const focusTarget = document.getElementById(focusedId || "dClose");
  if (focusTarget) focusTarget.focus({ preventScroll: true });
}

function closeDetail() {
  if (detailIndex < 0) return;
  overlay.classList.remove("open");
  detailIndex = -1;
  viewport.inert = false;
  viewport.removeAttribute("aria-hidden");
  overlay.inert = true;
  overlay.setAttribute("aria-hidden", "true");
  hit.querySelectorAll(".piece").forEach(el => el.setAttribute("aria-expanded", "false"));
  const target = detailReturnFocus;
  detailReturnFocus = null;
  if (target && target.isConnected !== false) target.focus({ preventScroll: true });
}

function trapDetailFocus(e) {
  const focusable = Array.from(sheet.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])"))
    .filter(el => !el.disabled && !el.hidden);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (e.shiftKey && (active === first || !sheet.contains(active))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (active === last || !sheet.contains(active))) {
    e.preventDefault();
    first.focus();
  }
}

overlay.addEventListener("click", e => { if (e.target === overlay) closeDetail(); });

// 全页只保留一个方向键处理器：弹窗打开时不会同时推进背景纸片。
window.addEventListener("keydown", e => {
  if (e.defaultPrevented) return;
  if (detailIndex >= 0) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeDetail();
    } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      if (!e.repeat) openDetail(pieces.length ? (detailIndex + (e.key === "ArrowRight" ? 1 : -1) + pieces.length) % pieces.length : 0);
    } else if (e.key === "Tab") {
      trapDetailFocus(e);
    }
    return;
  }
  const tag = (e.target && e.target.tagName) || "";
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
  if (["ArrowDown", "ArrowRight"].includes(e.key)) { e.preventDefault(); step(1); }
  else if (["ArrowUp", "ArrowLeft"].includes(e.key)) { e.preventDefault(); step(-1); }
});

function showArchiveError(message) {
  loadError = true;
  pieces = [];
  STATS = [];
  CATS = [{ id: "all", label: "全部" }];
  cursor = 0;
  build();
  statusText.textContent = `${message} 请检查网络后重试。`;
  statusEl.hidden = false;
  retryButton.disabled = false;
}

// HTTP 状态与 JSON 契约都必须通过；失败保留明确提示和重试入口。
async function loadArchive() {
  const api = ARCHIVE_API;
  retryButton.disabled = true;
  statusEl.hidden = true;
  if (!api) {
    showArchiveError("数据接口未配置。");
    return;
  }
  try {
    let response;
    try {
      response = await fetch(api, { headers: { Accept: "application/json" }, cache: "no-store" });
    } catch (error) {
      throw new Error("网络连接失败。");
    }
    if (!response.ok) throw new Error(`加载失败（HTTP ${response.status}）。`);
    let data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error("服务器返回了无法解析的 JSON 数据。");
    }
    if (!data || !Array.isArray(data.items) || !Array.isArray(data.stats) || !Array.isArray(data.tags)) {
      throw new Error("公开分享数据格式不正确。");
    }
    loadError = false;
    applyData(data);
  } catch (error) {
    showArchiveError(error.message || "加载失败。");
  } finally {
    retryButton.disabled = false;
  }
}

retryButton.addEventListener("click", loadArchive);

// 数据源：/api/archive.json 为唯一事实来源；空数据显示空态，绝不回退假示例。
(function () {
  // 本地离线验证时可注入 window.__ARCHIVE__；生产无此变量时正常走 API。
  if (window.__ARCHIVE__) { applyData(window.__ARCHIVE__); return; }
  loadArchive();
})();

build();
fit();
