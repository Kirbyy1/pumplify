const $ = (sel, el = document) => el.querySelector(sel);
const form = $("#search");
const input = $("#address");
const goBtn = $("#go");
const detectedEl = $("#detected");
const statusEl = $("#status");
const resultEl = $("#result");
const landingEl = $("#landing");
const recentEl = $("#recent");
const toastEl = $("#toast");

const EVM_RE = /^0x[0-9a-fA-F]{40}$/;
const SOL_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

const SOURCES = {
  label: { name: "Known entity", desc: "Curated exchange & protocol labels" },
  kol: { name: "KOL lists", desc: "kolscan · MadeOnSol · Solana Tracker" },
  fomo: { name: "Fomo", desc: "Wallets bound to a Fomo profile" },
  pump: { name: "pump.fun", desc: "Profile username & linked X" },
  sns: { name: "Solana Name Service", desc: ".sol primary domain" },
  ens: { name: "ENS", desc: ".eth primary name" },
  spaceid: { name: "SPACE ID", desc: ".bnb primary name" },
};
const CHAIN = {
  solana: { name: "Solana", dot: "sol", explorer: "Solscan" },
  ethereum: { name: "Ethereum", dot: "eth", explorer: "Etherscan" },
  bnb: { name: "BNB Chain", dot: "bnb", explorer: "BscScan" },
};

const ICON = {
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  share: '<svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  out: '<svg viewBox="0 0 24 24"><path d="M7 17L17 7M8 7h9v9"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M17.8 3h3.1l-6.8 7.7L22 21h-6.2l-4.9-6.3L5.3 21H2.2l7.2-8.3L1.8 3h6.4l4.4 5.8L17.8 3zm-1.1 16.2h1.7L7.4 4.7H5.6l11.1 14.5z"/></svg>',
};

/* ---------- helpers ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// Only allow http(s) images; ipfs:// goes through a public gateway.
function safeImg(url) {
  if (!url) return null;
  if (url.startsWith("ipfs://")) return "https://ipfs.io/ipfs/" + url.slice(7);
  return /^https?:\/\//i.test(url) ? url : null;
}
const shortAddr = (a) => (a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);
const fmtNum = (n, max = 4) => Number(n).toLocaleString("en-US", { maximumFractionDigits: max });
function fmtUsd(n, compact = true) {
  if (n == null) return "—";
  if (compact && n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (compact && n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (compact && n >= 1e4) return `$${(n / 1e3).toFixed(1)}K`;
  return "$" + n.toLocaleString("en-US", { maximumFractionDigits: n < 1 ? 4 : 2 });
}
function timeAgo(ms) {
  if (!ms) return "—";
  const s = (Date.now() - ms) / 1000;
  const units = [["y", 31536000], ["mo", 2592000], ["d", 86400], ["h", 3600], ["m", 60]];
  for (const [u, sec] of units) if (s >= sec) return `${Math.floor(s / sec)}${u} ago`;
  return "just now";
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let toastTimer;
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastEl.hidden = true), 1800);
}
async function copy(text, label = "Copied to clipboard") {
  try {
    await navigator.clipboard.writeText(text);
    toast(label);
  } catch {
    toast("Couldn't access clipboard");
  }
}

function detect(addr) {
  if (EVM_RE.test(addr)) return ["ethereum", "bnb"];
  if (SOL_RE.test(addr)) return ["solana"];
  return null;
}

/* ---------- live detection ---------- */
function updateDetected() {
  const v = input.value.trim();
  if (v.length < 3) return (detectedEl.hidden = true);
  const chains = detect(v);
  detectedEl.hidden = false;
  detectedEl.classList.remove("bad");
  detectedEl.innerHTML = !chains
    ? "Name search"
    : chains.length > 1
      ? `<i class="cdot eth"></i><i class="cdot bnb"></i>EVM`
      : `<i class="cdot sol"></i>Solana`;
}
input.addEventListener("input", updateDetected);

$("#paste").addEventListener("click", async () => {
  try {
    input.value = (await navigator.clipboard.readText()).trim();
    updateDetected();
    input.focus();
  } catch {
    toast("Clipboard blocked — paste with Ctrl+V");
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== input) {
    e.preventDefault();
    input.focus();
    input.select();
  }
});

$(".examples").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-try]");
  if (!btn) return;
  input.value = btn.dataset.try;
  form.chain.value = "auto";
  updateDetected();
  form.requestSubmit();
});

/* ---------- recent (per-browser convenience) ---------- */
function getRecent() {
  try { return JSON.parse(localStorage.getItem("pumpscan:recent") || "[]"); } catch { return []; }
}
function pushRecent(addr) {
  const list = [addr, ...getRecent().filter((a) => a !== addr)].slice(0, 5);
  try { localStorage.setItem("pumpscan:recent", JSON.stringify(list)); } catch {}
  renderRecent();
}
function renderRecent() {
  const list = getRecent();
  recentEl.hidden = !list.length;
  recentEl.innerHTML = list.length
    ? `<span>Recent</span>` + list.map((a) => `<button type="button" data-addr="${esc(a)}">${esc(shortAddr(a))}</button>`).join("")
    : "";
}
recentEl.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-addr]");
  if (!btn) return;
  input.value = btn.dataset.addr;
  updateDetected();
  form.requestSubmit();
});

/* ---------- rendering ---------- */
function scoreRing(score, confidence) {
  const r = 44, c = 2 * Math.PI * r;
  const color = confidence === "none" ? "var(--line-3)" : score >= 70 ? "var(--green)" : "var(--amber)";
  return `
    <div class="score" title="Ownership confidence">
      <svg viewBox="0 0 104 104">
        <circle class="track" cx="52" cy="52" r="${r}"/>
        <circle class="bar" cx="52" cy="52" r="${r}" stroke="${color}"
                stroke-dasharray="${c}" stroke-dashoffset="${c}" data-target="${c * (1 - score / 100)}"/>
      </svg>
      <div class="score-val"><b>${score}</b><span>Confidence</span></div>
    </div>`;
}

function renderIdentity(d) {
  const o = d.owner;
  const pump = d.sources.find((s) => s.key === "pump" && s.found);
  const avatar = safeImg(o?.avatar);
  const handle = o?.x?.replace(/^@/, "");
  const primary = d.chains[0];

  const tags = [];
  if (o) tags.push(`<span class="tag ${d.score >= 70 ? "green" : "amber"}">${d.score >= 70 ? "Verified match" : "Weak match"}</span>`);
  else tags.push(`<span class="tag">No public identity</span>`);
  if (o?.kind) tags.push(`<span class="tag">${esc(o.kind)}</span>`);
  if (handle) tags.push(`<a class="tag" href="https://x.com/${encodeURIComponent(handle)}" target="_blank" rel="noopener">${ICON.x}@${esc(handle)}</a>`);
  if (pump?.banned) tags.push(`<span class="tag red">Banned on pump.fun</span>`);
  const tg = d.sources.find((s) => s.found && s.telegram)?.telegram;
  if (tg && /^https:\/\/t\.me\//.test(tg)) tags.push(`<a class="tag" href="${esc(tg)}" target="_blank" rel="noopener">Telegram</a>`);
  d.chains.forEach((c) => tags.push(`<span class="tag"><i class="cdot ${CHAIN[c].dot}"></i>${CHAIN[c].name}</span>`));

  const links = [
    pump ? `<a class="link-btn" href="${esc(pump.url)}" target="_blank" rel="noopener">pump.fun ${ICON.out}</a>` : "",
    ...Object.entries(d.explorers).map(([c, url]) =>
      `<a class="link-btn" href="${esc(url)}" target="_blank" rel="noopener">${CHAIN[c].explorer} ${ICON.out}</a>`),
  ].join("");

  return `
    <div class="idcard ${o ? "" : "anon"}">
      <div class="id-top">
        <div class="avatar-wrap">
          <div class="avatar">${o ? esc(o.name[0].toUpperCase()) : "?"}${avatar ? `<img src="${esc(avatar)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</div>
          <span class="avatar-chain"><i class="cdot ${CHAIN[primary].dot}"></i></span>
        </div>
        <div class="id-main">
          <div class="id-label">${o ? `Owner · via ${esc(o.source)}` : "Owner"}${d.resolved_from ? ` · found by searching “${esc(d.resolved_from.label)}” on ${esc(d.resolved_from.via)}` : ""}</div>
          <p class="id-name">${o ? esc(o.name) : "Unknown wallet"}</p>
          <div class="id-tags">${tags.join("")}</div>
          ${o?.bio ? `<p class="id-bio">${esc(o.bio)}</p>` : ""}
        </div>
        ${scoreRing(d.score, d.confidence)}
      </div>
      <div class="id-addr">
        <div class="addr-chip">
          <code>${esc(d.address)}</code>
          <button class="icon-btn" type="button" data-copy="${esc(d.address)}">${ICON.copy}Copy</button>
          <button class="icon-btn" type="button" data-share>${ICON.share}Share</button>
        </div>
        ${links}
      </div>
    </div>`;
}

function renderKpis(d) {
  const totalUsd = d.balances.reduce((s, b) => s + (b.usd || 0), 0);
  const hasUsd = d.balances.some((b) => b.usd != null);
  const hits = d.sources.filter((s) => s.found).length;
  const social = ["fomo", "pump"].map((k) => d.sources.find((s) => s.key === k && s.found)).find(Boolean);
  const graduated = d.coins.filter((c) => c.complete).length;
  const solana = d.chains.includes("solana");

  const kpi = (label, val, sub) => `
    <div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-val">${val}</div><div class="kpi-sub">${sub}</div></div>`;

  return `<div class="kpis">
    ${kpi("Native value", hasUsd ? fmtUsd(totalUsd, false) : "—", d.balances.map((b) => `${fmtNum(b.amount, 3)} ${b.symbol}`).join(" · ") || "unavailable")}
    ${kpi("Identity matches", `${hits}<span style="color:var(--faint)">/${d.sources.length}</span>`, hits ? "sources agree" : "nothing linked")}
    ${kpi(social ? `${social.source} followers` : "Followers", social ? fmtNum(social.followers, 0) : "—", social ? `${fmtNum(social.following, 0)} following` : "no social profile")}
    ${kpi("Coins created", solana ? d.coins.length + (d.coins.length >= 12 ? "+" : "") : "—", solana ? `${graduated} graduated` : "Solana only")}
  </div>`;
}

function signalDetail(s) {
  if (s.key === "kol" && s.pnl != null) {
    const sign = s.pnl >= 0 ? "+" : "";
    return `${sign}${fmtNum(s.pnl, 1)} SOL PnL (${s.timeframe}d)${s.wins != null ? ` · ${s.wins}W / ${s.losses}L` : ""}`;
  }
  if (s.key === "fomo") {
    const parts = [`${fmtNum(s.followers, 0)} followers`];
    if (s.trades != null) parts.push(`${fmtNum(s.trades, 0)} trades`);
    if (s.last_seen) parts.push(`seen ${timeAgo(s.last_seen * 1000)}`);
    return parts.join(" · ");
  }
  if (s.key === "pump" && s.found) return `${fmtNum(s.followers, 0)} followers`;
  return "";
}

function renderLinked(d) {
  const fomo = d.sources.find((s) => s.key === "fomo" && s.found);
  const others = fomo?.other_wallets || [];
  if (!others.length) return "";
  return `<section class="panel">
    <div class="panel-head"><h2>Linked wallets</h2><span class="count">same Fomo profile</span></div>
    <div class="panel-body">${others.map((w) => `
      <button class="match" type="button" data-scan="${esc(w.address)}">
        <span class="bal-ico"><i class="cdot ${w.chain === "solana" ? "sol" : "eth"}"></i></span>
        <span class="match-main"><b>${w.chain === "solana" ? "Solana" : "EVM"} wallet</b><code>${esc(w.address)}</code></span>
        <span class="match-go">Scan →</span>
      </button>`).join("")}</div>
  </section>`;
}

const VIA_TAG = { ENS: "eth", SNS: "sol", "SPACE ID": "bnb", Fomo: "all" };

function renderMatches(d) {
  const rows = d.matches.map((m) => {
    const img = safeImg(m.avatar);
    return `
      <button class="match" type="button" data-scan="${esc(m.address)}" data-chain="${m.chain === "solana" || m.chain === "bnb" ? m.chain : "auto"}">
        <span class="match-av">${esc(m.label[0].toUpperCase())}${img ? `<img src="${esc(img)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}</span>
        <span class="match-main">
          <b>${esc(m.label)} <span class="tag"><i class="cdot ${VIA_TAG[m.via] || "sol"}"></i>${esc(m.via)}</span></b>
          <code>${esc(m.address)}</code>
          ${m.detail ? `<span class="match-sub">${esc(m.detail)}</span>` : ""}
        </span>
        <span class="match-go">Scan →</span>
      </button>`;
  }).join("");
  resultEl.innerHTML = `<section class="panel">
    <div class="panel-head"><h2>Wallets matching “${esc(d.query)}”</h2><span class="count">${d.matches.length}</span></div>
    <div class="panel-body"><p class="match-note">Different services can map the same name to different people. Pick the one you mean.</p>${rows}</div>
  </section>`;
  resultEl.hidden = false;
  landingEl.hidden = true;
}

function renderSignals(d) {
  const rows = d.sources.map((s) => {
    const meta = SOURCES[s.key];
    const cls = !s.ok ? "err" : s.found ? "hit" : "miss";
    const st = !s.ok ? "!" : s.found ? "✓" : "–";
    let val = !s.ok ? "Source unavailable" : s.found ? esc(s.name) : "No match";
    if (s.found && s.url) val = `<a href="${esc(s.url)}" target="_blank" rel="noopener">${val}</a>`;
    const detail = s.found ? signalDetail(s) : "";
    return `<div class="row ${cls}"><span class="st">${st}</span><span class="nm"><b>${meta.name}</b><span>${detail || meta.desc}</span></span><span class="vl">${val}</span></div>`;
  });
  const hits = d.sources.filter((s) => s.found).length;
  return `<section class="panel">
    <div class="panel-head"><h2>Identity signals</h2><span class="count">${hits} / ${d.sources.length}</span></div>
    <div class="panel-body rows">${rows.join("")}</div>
  </section>`;
}

function renderBalances(d) {
  const rows = d.balances.length
    ? d.balances.map((b) => `
        <div class="bal">
          <span class="bal-ico"><i class="cdot ${CHAIN[b.chain].dot}"></i></span>
          <span class="bal-name"><b>${CHAIN[b.chain].name}</b><span>${esc(b.symbol)}</span></span>
          <span class="bal-amt"><b>${fmtNum(b.amount)}</b><span>${fmtUsd(b.usd, false)}</span></span>
        </div>`).join("")
    : `<div class="empty"><span class="empty-ico">∅</span>Balance lookup unavailable right now.</div>`;
  return `<section class="panel">
    <div class="panel-head"><h2>Holdings</h2><span class="count">native</span></div>
    <div class="panel-body">${rows}</div>
  </section>`;
}

function renderCoins(d) {
  if (!d.chains.includes("solana")) return "";
  const body = d.coins.length
    ? `<table class="table">
        <thead><tr><th>Token</th><th class="num">Market cap</th><th>Created</th><th>Status</th></tr></thead>
        <tbody>${d.coins.map((c) => {
          const img = safeImg(c.image);
          return `<tr data-href="https://pump.fun/coin/${encodeURIComponent(c.mint)}">
            <td><div class="coin-cell">${img ? `<img src="${esc(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="ph"></span>`}
              <div><b>${esc(c.name)}</b><span>$${esc(c.symbol)}</span></div></div></td>
            <td class="num">${fmtUsd(c.market_cap)}</td>
            <td>${timeAgo(c.created)}</td>
            <td>${c.complete ? `<span class="pill grad-done">Graduated</span>` : `<span class="pill curve">Bonding</span>`}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>`
    : `<div class="empty"><span class="empty-ico">◎</span>This wallet hasn't launched any coins on pump.fun.</div>`;
  return `<section class="panel">
    <div class="panel-head"><h2>Coins launched on pump.fun</h2><span class="count">${d.coins.length}${d.coins.length >= 12 ? "+" : ""}</span></div>
    ${body}
  </section>`;
}

function render(d) {
  resultEl.innerHTML =
    renderIdentity(d) +
    renderKpis(d) +
    `<div class="split">${renderSignals(d)}${renderBalances(d)}</div>` +
    renderLinked(d) +
    renderCoins(d);
  resultEl.hidden = false;
  landingEl.hidden = true;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const bar = $(".score .bar", resultEl);
    if (bar) bar.style.strokeDashoffset = bar.dataset.target;
  }));
}

resultEl.addEventListener("click", (e) => {
  const scanBtn = e.target.closest("[data-scan]");
  if (scanBtn) {
    input.value = scanBtn.dataset.scan;
    form.chain.value = "auto";
    updateDetected();
    return scan(scanBtn.dataset.scan, scanBtn.dataset.chain || "auto");
  }
  const copyBtn = e.target.closest("[data-copy]");
  if (copyBtn) return copy(copyBtn.dataset.copy, "Address copied");
  if (e.target.closest("[data-share]")) return copy(location.href, "Link copied");
  const row = e.target.closest("tr[data-href]");
  if (row) window.open(row.dataset.href, "_blank", "noopener");
});

/* ---------- scan flow ---------- */
function stepsFor(chains, isName) {
  if (isName) return ["Resolving .eth / .sol / .bnb names", "Searching KOL lists", "Searching Fomo handles", "Scanning matched wallet"];
  const s = ["Validating address", "Checking known entity labels", "Matching Fomo profiles", "Fetching pump.fun profile"];
  if (chains.includes("solana")) s.push("Checking KOL lists", "Resolving .sol domain", "Indexing launched coins");
  if (chains.includes("ethereum")) s.push("Resolving ENS name");
  if (chains.includes("bnb")) s.push("Resolving .bnb name");
  s.push("Reading balances");
  return s;
}

function showProgress(steps) {
  statusEl.hidden = false;
  statusEl.innerHTML = `
    <div class="scan-steps">${steps.map((s) => `<div class="scan-step"><span class="tick"></span>${s}</div>`).join("")}</div>
    <div class="skeleton"><div class="sk" style="height:170px"></div><div class="sk" style="height:96px"></div></div>`;
  const els = [...statusEl.querySelectorAll(".scan-step")];
  let i = 0;
  els[0].classList.add("active");
  const timer = setInterval(() => {
    if (i >= els.length - 1) return;
    els[i].classList.replace("active", "done");
    els[++i].classList.add("active");
  }, 260);
  return async () => {
    clearInterval(timer);
    els.forEach((el) => { el.classList.remove("active"); el.classList.add("done"); });
    await sleep(180);
  };
}

function showError(msg) {
  statusEl.hidden = false;
  statusEl.innerHTML = `<div class="error-card"><span class="error-ico">!</span><div><b>Scan failed</b>${esc(msg)}</div></div>`;
}

async function scan(address, chain) {
  goBtn.disabled = true;
  resultEl.hidden = true;
  const detected = detect(address);
  const chains = chain === "auto" ? detected || ["solana"] : [chain];
  const finish = showProgress(stepsFor(chains, !detected));
  try {
    if (location.protocol === "file:") {
      throw new Error("This page was opened as a file. Start the server (python pumpscan/app.py) and open http://localhost:8000 instead.");
    }
    const res = await fetch(`/api/lookup?${new URLSearchParams({ q: address, chain })}`).catch(() => {
      throw new Error("Can't reach the pumpscan server. Is it still running? Start it with: python pumpscan/app.py");
    });
    const data = await res.json().catch(() => ({ error: "Unexpected server response." }));
    if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status})`);
    await finish();
    statusEl.hidden = true;
    history.replaceState(null, "", `#${encodeURIComponent(address)}`);
    data.matches ? renderMatches(data) : render(data);
    pushRecent(address);
    window.scrollTo({ top: $(".search").offsetTop - 90, behavior: "smooth" });
  } catch (err) {
    await finish();
    showError(err.message);
  } finally {
    goBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const address = input.value.trim();
  if (address) scan(address, form.chain.value);
});

/* cursor-follow glow on feature cards */
document.querySelectorAll(".feature").forEach((el) => {
  el.addEventListener("pointermove", (e) => {
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  });
});

/* deep links: /#<address> */
function scanFromHash() {
  const addr = decodeURIComponent(location.hash.slice(1)).trim();
  if (addr === "how" || addr === "sources") return void (landingEl.hidden = false);
  if (!addr || (addr === input.value.trim() && !resultEl.hidden)) return;
  input.value = addr;
  form.chain.value = "auto";
  updateDetected();
  scan(addr, "auto");
}
window.addEventListener("hashchange", scanFromHash);
renderRecent();
scanFromHash();
