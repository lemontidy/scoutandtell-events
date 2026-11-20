/* Scout & Tell job board */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const EMBEDDED = window.parent !== window;
  const PAGE = 25;
  const CONTACT = "jobs@scoutandtell.com";

  const state = { jobs: [], sponsored: { spotlight: [], featured: [], gold: [] }, q: "", where: "", type: "", cat: "", sort: "new", limit: PAGE };
  let ENDPOINT = "";

  // ---------------------------------------------------------------- stats
  // Counts visits and clicks for sponsor reports. No names, emails or IPs:
  // a visitor is a random ID kept in this browser only.
  const visitor = (() => {
    try {
      let v = localStorage.getItem("st_jobs_v");
      if (!v) { v = Math.random().toString(36).slice(2, 12); localStorage.setItem("st_jobs_v", v); }
      return v;
    } catch (_) { return "anon-" + Math.random().toString(36).slice(2, 8); }
  })();
  const queue = [];
  let flushTimer;
  function stat(event, data = {}) {
    queue.push({ event, visitor, embedded: EMBEDDED, ...data });
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, 1500);
  }
  function flush() {
    if (!ENDPOINT || !queue.length) { queue.length = 0; return; }
    const body = JSON.stringify({ kind: "event", events: queue.splice(0, 25) });
    // Google Apps Script answers with a redirect, which sendBeacon drops, so use fetch.
    try {
      fetch(ENDPOINT, { method: "POST", body, mode: "no-cors", keepalive: true, headers: { "Content-Type": "text/plain" } })
        .catch(() => { try { navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, body); } catch (_) {} });
    } catch (_) {}
    if (queue.length) flush();
  }
  addEventListener("pagehide", flush);
  addEventListener("visibilitychange", () => document.visibilityState === "hidden" && flush());
  const jobInfo = (j, extra = {}) => ({ jobId: j.id || "", company: j.company || "", title: j.title || "", ...extra });
  // Sponsored cards count as "seen" once at least half of the card is on screen.
  const seen = new Set();
  const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const el = e.target, key = el.dataset.imp;
      if (seen.has(key)) return;
      seen.add(key); io.unobserve(el);
      const [tier, slot, company, title] = key.split("|");
      stat("sponsored_view", { tier, slot, company, title });
    });
  }, { threshold: 0.5 }) : null;
  function watchImpressions() { if (io) $$("[data-imp]").forEach((el) => !seen.has(el.dataset.imp) && io.observe(el)); }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const todayIso = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Denver" });
  const live = (arr) => (arr || []).filter((x) => x && x.title && (!x.ends || x.ends >= todayIso()));
  const mail = (subject, body = "") => `mailto:${CONTACT}?subject=${encodeURIComponent(subject)}${body ? "&body=" + encodeURIComponent(body) : ""}`;
  const goldSet = () => new Set(live(state.sponsored.gold.map((g) => (typeof g === "string" ? { title: g, company: g } : g))).map((g) => g.company.toLowerCase()));

  function ago(iso) {
    if (!iso) return "";
    const d = Math.round((new Date(todayIso()) - new Date(iso)) / 864e5);
    if (d <= 0) return "Today";
    if (d === 1) return "Yesterday";
    if (d < 7) return `${d} days ago`;
    if (d < 14) return "1 week ago";
    return `${Math.floor(d / 7)} weeks ago`;
  }

  // ---------------------------------------------------------------- load
  async function load() {
    const [jobs, sponsored, cfg] = await Promise.all([
      fetch("jobs.json", { cache: "no-cache" }).then((r) => r.json()),
      fetch("sponsored.json", { cache: "no-cache" }).then((r) => r.json()).catch(() => ({})),
      fetch("config.json", { cache: "no-cache" }).then((r) => r.json()).catch(() => ({})),
    ]);
    ENDPOINT = cfg.endpoint || "";
    state.jobs = jobs.jobs || [];
    if (ENDPOINT) {
      try {
        const posted = await fetch(ENDPOINT + "?action=jobs").then((r) => r.json());
        state.jobs = (posted.jobs || []).map((j) => ({ ...j, category: j.category || "Other" })).concat(state.jobs);
      } catch (_) {}
    }
    const ref = (() => { try { return document.referrer ? new URL(document.referrer).host : ""; } catch (_) { return ""; } })();
    stat("page_view", { referrer: ref, utm: new URLSearchParams(location.search).get("utm_source") || "" });
    state.sponsored = { spotlight: [], featured: [], gold: [], ...sponsored };
    const towns = jobs.towns || [...new Set(state.jobs.map((j) => j.town))];
    $("#where").insertAdjacentHTML("beforeend", towns.map((t) => `<option>${esc(t)}</option>`).join(""));
    $("#cats").innerHTML = `<button data-cat="" class="on">All</button>` + (jobs.categories || []).map((c) => `<button data-cat="${esc(c)}">${esc(c)}</button>`).join("");
    if (jobs.updated) {
      const when = new Date(jobs.updated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Denver" });
      $("#meta").textContent = `${state.jobs.length.toLocaleString()} open jobs · updated ${when}`;
    }
    readUrl();
    renderSponsored();
    render();
    renderBrowse();
    watchImpressions();
  }

  // ---------------------------------------------------------------- url state
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.q = p.get("q") || ""; state.where = p.get("where") || ""; state.type = p.get("type") || ""; state.cat = p.get("cat") || "";
    $("#q").value = state.q; $("#where").value = state.where;
  }
  function writeUrl() {
    const p = new URLSearchParams();
    for (const k of ["q", "where", "type", "cat"]) if (state[k]) p.set(k, state[k]);
    const s = p.toString();
    try { history.replaceState(null, "", s ? `?${s}` : location.pathname); } catch (_) {}
  }

  // ---------------------------------------------------------------- sponsored
  function renderSponsored() {
    const spots = live(state.sponsored.spotlight).slice(0, 2);
    const reserve = (wide) => `
      <div class="j-open${wide ? " wide" : ""}">
        <p class="j-mono">Spotlight spot open</p>
        <h3>Your role here, above everyone.</h3>
        <p>Seen first on every visit and in the newsletter.</p>
        <a class="j-btn j-btn-solid" data-cta="reserve_spotlight" href="${mail("Spotlight spot on the Scout & Tell job board")}">Reserve this spot</a>
      </div>`;
    $("#spotlight").innerHTML = spots.length
      ? spots.map((s, i) => `
        <button class="j-spot" data-sp="spotlight:${i}" data-imp="spotlight|${i + 1}|${esc(s.company)}|${esc(s.title)}">
          <div class="j-spot-top">
            <div class="j-spot-co"><span>${esc(s.company)}</span><span class="j-badge">Spotlight</span></div>
            <h3>${esc(s.title)}</h3>
            ${s.blurb ? `<p class="j-spot-blurb">${esc(s.blurb)}</p>` : ""}
          </div>
          <div class="j-spot-foot">
            <div><strong>${esc(s.town)}</strong><small>${esc([s.type, s.pay].filter(Boolean).join(" · "))}</small></div>
            <span class="j-arrow" aria-hidden="true">→</span>
          </div>
        </button>`).join("") + (spots.length < 2 ? reserve(false) : "")
      : reserve(true);

    const feats = live(state.sponsored.featured);
    $("#featured").className = feats.length ? "j-feat-row" : "";
    $("#featured").innerHTML = feats.length
      ? feats.map((f, i) => `
        <button class="j-feat" data-sp="featured:${i}" data-imp="featured|${i + 1}|${esc(f.company)}|${esc(f.title)}">
          <span class="j-co">${esc(f.company)}</span>
          <h3>${esc(f.title)}</h3>
          <div class="j-feat-foot"><span>${esc(f.town)}</span><span>${esc(f.pay || f.type || "")}</span></div>
        </button>`).join("")
      : `<div class="j-banner"><p>Featured spot open. Your job in the clay frame, and in Wednesday's newsletter.</p><a data-cta="featured_banner" href="${mail("Featured job on Scout & Tell")}">Get featured →</a></div>`;
  }

  // ---------------------------------------------------------------- list
  function matches(j) {
    if (state.where && j.town !== state.where) return false;
    if (state.type && j.type !== state.type) return false;
    if (state.cat && j.category !== state.cat) return false;
    if (state.q) {
      const hay = `${j.title} ${j.company} ${j.town} ${j.category}`.toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }
  function sorted(list) {
    const gold = goldSet();
    const by = {
      new: (a, b) => (b.posted || b.first_seen || "").localeCompare(a.posted || a.first_seen || ""),
      pay: (a, b) => (b.pay_sort || 0) - (a.pay_sort || 0),
      az: (a, b) => a.title.localeCompare(b.title),
    }[state.sort];
    return list.map((j) => ({ ...j, gold: gold.has(j.company.toLowerCase()) })).sort(by);
  }
  function row(j) {
    return `<li><button class="j-row${j.gold ? " gold" : ""}" data-id="${j.id}"${j.gold ? ` data-imp="gold|list|${esc(j.company)}|${esc(j.title)}"` : ""}>
      <div><h3>${esc(j.title)}</h3><div class="j-co-line">${esc(j.company)}${j.pay ? ` · <span class="j-pay">${esc(j.pay)}</span>` : ""}</div></div>
      ${j.type ? `<span class="j-pill">${esc(j.type)}</span>` : "<span></span>"}
      <span class="j-row-where">${esc(j.town)}<small>${esc(ago(j.posted || j.first_seen))}</small></span>
      <span class="j-chev" aria-hidden="true">›</span>
    </button></li>`;
  }
  function render() {
    const list = sorted(state.jobs.filter(matches));
    const shown = list.slice(0, state.limit);
    const where = state.where ? ` in ${state.where}` : "";
    $("#listTitle").textContent = state.q || state.where || state.cat || state.type ? `Jobs${where}` : "Just posted";
    $("#count").textContent = list.length ? `${list.length.toLocaleString()} job${list.length === 1 ? "" : "s"}${state.q ? ` matching “${state.q}”` : ""}${where}` : "";
    $("#list").innerHTML = shown.length ? shown.map(row).join("")
      : `<li class="j-empty">No jobs match that yet. Try another town or a shorter search.${state.jobs.length ? "" : "<br>New jobs arrive every morning."}</li>`;
    $("#more").hidden = list.length <= shown.length;
    $$("#typeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.type === state.type));
    $$("#cats button").forEach((b) => b.classList.toggle("on", b.dataset.cat === state.cat));
    $$("#quick button").forEach((b) => b.classList.toggle("on", (b.dataset.type && b.dataset.type === state.type) || (b.dataset.cat && b.dataset.cat === state.cat)));
    writeUrl();
    postHeight();
    watchImpressions();
  }

  // ---------------------------------------------------------------- browse
  function renderBrowse() {
    const gold = goldSet();
    const count = (key) => state.jobs.reduce((m, j) => ((m[j[key]] = (m[j[key]] || 0) + 1), m), {});
    const top = (obj, n, skip = []) => Object.entries(obj).filter(([k]) => k && !skip.includes(k)).sort((a, b) => b[1] - a[1]).slice(0, n).map(([k]) => k);
    const boxes = [
      ...top(count("town"), 2).map((t) => ({ label: `Jobs in ${t}`, key: "where", val: t, jobs: state.jobs.filter((j) => j.town === t) })),
      ...top(count("category"), 2, ["Other"]).map((c) => ({ label: c, key: "cat", val: c, jobs: state.jobs.filter((j) => j.category === c) })),
    ];
    $("#browseSec").hidden = !boxes.length;
    $("#browse").innerHTML = boxes.map((b) => `
      <div class="j-box">
        <div class="j-box-head"><h3>${esc(b.label)}</h3><button data-browse="${b.key}" data-val="${esc(b.val)}">See all ${b.jobs.length}</button></div>
        <ul>${b.jobs.slice(0, 3).map((j) => `<li><button class="j-mini${gold.has(j.company.toLowerCase()) ? " gold" : ""}" data-id="${j.id}">
          <div><strong>${esc(j.title)}</strong><span>${esc(j.company)}</span></div><em>${esc(b.key === "where" ? j.pay || j.type || "" : j.town)}</em></button></li>`).join("")}</ul>
      </div>`).join("");
  }

  // ---------------------------------------------------------------- job pop-up
  function openJob(j, paid, tier) {
    const facts = [j.town, j.type, j.pay, j.posted || j.first_seen ? `Posted ${ago(j.posted || j.first_seen).toLowerCase()}` : ""].filter(Boolean);
    const url = j.apply_url || "";
    $("#mBody").innerHTML = `
      <div class="j-m-head">
        <p class="j-mono">${esc(j.company)}${paid ? " · Sponsored" : ""}</p>
        <h2 id="mTitle">${esc(j.title)}</h2>
        <div class="j-m-facts">${facts.map((f) => `<span>${esc(f)}</span>`).join("")}</div>
      </div>
      <div class="j-m-body">
        ${j.blurb ? `<p><strong>${esc(j.blurb)}</strong></p>` : ""}
        ${j.description ? `<p class="j-m-desc">${esc(j.description)}</p>` : ""}
        <div class="j-m-actions">
          ${url ? `<a class="j-btn j-btn-clay" id="applyBtn" href="${esc(url)}" target="_blank" rel="noopener">Apply now ↗</a>` : ""}
          <span class="j-m-small">${j.via && !paid ? `Full details${j.direct ? " on the employer's site" : ` via ${esc(j.via)}`}` : ""}</span>
        </div>
        <p class="j-m-small" style="margin-top:18px">Is this your job? <a href="${mail(`My listing: ${j.title} at ${j.company}`, `Job ID: ${j.id || "sponsored"}\n\nI'd like to (edit / upgrade / remove) this listing.`)}">Edit, upgrade or remove it</a>.</p>
      </div>`;
    const gold = !paid && goldSet().has((j.company || "").toLowerCase());
    $("#applyBtn")?.addEventListener("click", () => {
      track("apply", j);
      stat(paid ? "sponsored_apply" : "apply_click", jobInfo(j, { tier: paid ? tier : gold ? "gold" : "" }));
    });
    openDialog($("#jobModal"));
    track("view", j);
    stat(paid ? "sponsored_open" : "job_open", jobInfo(j, { tier: paid ? tier : gold ? "gold" : "" }));
  }

  // ---------------------------------------------------------------- embed
  if (EMBEDDED) document.documentElement.classList.add("st-embedded");
  let lastH = 0, lastClickY = 0;
  function postHeight() {
    if (!EMBEDDED) return;
    requestAnimationFrame(() => {
      const h = Math.ceil($("#app").getBoundingClientRect().bottom + window.scrollY);
      if (h !== lastH) { lastH = h; window.parent.postMessage({ type: "st-jobs-height", height: h }, "*"); }
    });
  }
  function track(name, j) { try { window.parent.postMessage({ type: "st-jobs-event", name, id: j.id, title: j.title, company: j.company }, "*"); } catch (_) {} }
  function openDialog(dlg) {
    if (EMBEDDED) { dlg.style.position = "absolute"; dlg.style.margin = "0 auto"; dlg.style.top = Math.max(16, lastClickY - 160) + "px"; dlg.style.maxHeight = "none"; }
    dlg.showModal();
    if (EMBEDDED) dlg.scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("pointerdown", (ev) => { lastClickY = ev.pageY; }, true);

  // ---------------------------------------------------------------- wire up
  function set(patch, scroll) {
    Object.assign(state, patch, { limit: PAGE });
    render();
    if (scroll) $("#listSec").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    const id = t.closest("[data-id]")?.dataset.id;
    if (id) { const j = state.jobs.find((x) => x.id === id); if (j) openJob({ ...j }, false); return; }
    const sp = t.closest("[data-sp]")?.dataset.sp;
    if (sp) { const [kind, i] = sp.split(":"); openJob(live(state.sponsored[kind])[+i], true, kind); return; }
    const br = t.closest("[data-browse]");
    if (br) { stat("browse_click", { detail: br.dataset.browse + ":" + br.dataset.val }); set({ where: "", cat: "", q: "", type: "", [br.dataset.browse]: br.dataset.val }, true); $("#where").value = state.where; $("#q").value = ""; return; }
    const cta = t.closest("[data-cta]");
    if (cta) stat("cta_click", { detail: cta.dataset.cta });
    if (t.closest("[data-open=post]")) { ev.preventDefault(); openPost(); return; }
    if (t.closest("[data-close]")) t.closest("dialog").close();
    if (t.tagName === "DIALOG") t.close();
  });
  $("#quick").onclick = (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    if (b.dataset.type) set({ type: state.type === b.dataset.type ? "" : b.dataset.type }, true);
    else set({ cat: state.cat === b.dataset.cat ? "" : b.dataset.cat }, true);
  };
  $("#typeSeg").onclick = (ev) => { const b = ev.target.closest("button"); if (b) set({ type: b.dataset.type }); };
  $("#cats").onclick = (ev) => { const b = ev.target.closest("button"); if (b) set({ cat: b.dataset.cat }); };
  $("#sort").onchange = (ev) => set({ sort: ev.target.value });
  $("#more").onclick = () => { state.limit += PAGE; render(); };
  let qTimer;
  $("#q").oninput = (ev) => { clearTimeout(qTimer); qTimer = setTimeout(() => set({ q: ev.target.value.trim() }), 160); };
  $("#where").onchange = (ev) => set({ where: ev.target.value });
  let lastQ = "";
  $("#searchForm").onsubmit = (ev) => {
    ev.preventDefault();
    set({ q: $("#q").value.trim(), where: $("#where").value }, true);
    if (state.q !== lastQ || state.where) stat("search", { detail: [state.q, state.where].filter(Boolean).join(" @ ").slice(0, 120) });
    lastQ = state.q;
  };
  $("#q").addEventListener("change", () => { const q = $("#q").value.trim(); if (q.length > 1 && q !== lastQ) { lastQ = q; stat("search", { detail: q }); } });
  $("#where").addEventListener("change", (ev) => stat("filter", { detail: "town:" + ev.target.value }));
  $("#typeSeg").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) stat("filter", { detail: "type:" + (b.dataset.type || "all") }); });
  $("#cats").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) stat("filter", { detail: "cat:" + (b.dataset.cat || "all") }); });
  $("#quick").addEventListener("click", (ev) => { const b = ev.target.closest("button"); if (b) stat("filter", { detail: "quick:" + (b.dataset.type || b.dataset.cat) }); });

  $("#postLink").href = mail("Post a job on Scout & Tell (free)", "Job title:\nCompany:\nTown:\nFull or part time:\nPay range:\nLink to apply:\n");
  $("#postLink").dataset.open = "post";
  function openPost() {
    stat("post_job_open");
    if (!ENDPOINT) { location.href = $("#postLink").href; return; }
    $("#postMsg").textContent = ""; $("#postForm").hidden = false;
    openDialog($("#postModal"));
  }
  $("#postForm").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target, btn = f.querySelector("button[type=submit]"), msg = $("#postMsg");
    const data = Object.fromEntries(new FormData(f).entries());
    if (!/^https?:\/\//i.test(data.applyUrl) && !/@/.test(data.applyUrl)) { msg.textContent = "Add a link or email where people can apply."; return; }
    btn.disabled = true; msg.textContent = "Sending…";
    try {
      await fetch(ENDPOINT, { method: "POST", mode: "no-cors", body: JSON.stringify({ kind: "job", ...data }) });
      stat("post_job_submit", { company: data.company, title: data.title, tier: data.tierWanted });
      f.reset(); f.hidden = true;
      msg.textContent = "Thanks! We'll review it and email you when it's live, usually within a day.";
    } catch (_) { msg.textContent = "Something went wrong. Please try again in a minute."; }
    finally { btn.disabled = false; postHeight(); }
  };
  $("#featureLink").href = mail("Featured job on Scout & Tell");
  $("#featureLink").dataset.cta = "get_featured";
  $("#presentingLink").href = mail("Presenting sponsor: Scout & Tell job board");
  $("#presentingLink").dataset.cta = "presenting_sponsor";

  window.addEventListener("resize", postHeight);
  new ResizeObserver(postHeight).observe(document.body);

  load().catch((err) => {
    console.error(err);
    $("#list").innerHTML = `<li class="j-empty">The job board couldn't load right now. Please refresh in a moment.</li>`;
  });
})();
