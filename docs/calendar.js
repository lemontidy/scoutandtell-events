/* Scout & Tell events calendar
 * Reads events.json (rebuilt nightly) plus reader submissions you've approved
 * (served by the Google Apps Script set in config.json).
 */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");

  const CITY_ORDER = ["Fort Collins", "Loveland", "Greeley", "Estes Park", "Windsor", "Berthoud"];
  const LIST_PAGE = 60;
  const EMBEDDED = window.parent !== window;
  let lastClickY = 0;

  const state = {
    events: [], ongoing: [], categories: [], cities: [],
    view: "list", when: "all", q: "",
    selCities: new Set(), selCats: new Set(),
    cursor: today(), listLimit: LIST_PAGE, config: {},
  };

  // ---------------------------------------------------------------- dates
  function today() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }
  function ymd(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
  function parseYmd(s) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function startOfWeek(d) { return addDays(d, -d.getDay()); }
  const fmtDay = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" });
  const fmtShort = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });
  const fmtMonth = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" });
  function fmtTime(t) {
    if (!t) return "";
    let [h, m] = t.split(":").map(Number);
    const ap = h >= 12 ? "pm" : "am"; h = h % 12 || 12;
    return m ? `${h}:${String(m).padStart(2, "0")}${ap}` : `${h}${ap}`;
  }
  function timeRange(e) { return e.start ? fmtTime(e.start) + (e.end ? `–${fmtTime(e.end)}` : "") : "All day"; }

  // ---------------------------------------------------------------- load
  async function load() {
    const [data, config] = await Promise.all([
      fetch("events.json", { cache: "no-cache" }).then((r) => r.json()),
      fetch("config.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    state.config = config || {};
    let events = data.events || [];
    state.categories = data.categories || [];

    if (safeUrl(state.config.submitEndpoint)) {
      try {
        const r = await fetch(state.config.submitEndpoint + "?action=approved");
        const sub = await r.json();
        events = events.concat((sub.events || []).map(normalizeSubmission).filter(Boolean));
      } catch (e) { /* submissions are a bonus; the calendar works without them */ }
    }

    const t = ymd(today());
    state.ongoing = events.filter((e) => e.runsThrough && e.runsThrough >= t);
    state.events = events.filter((e) => !e.runsThrough && e.date >= t)
      .sort((a, b) => (a.date + (a.start || "99")).localeCompare(b.date + (b.start || "99")) || a.title.localeCompare(b.title));

    const citySet = new Set([...state.events, ...state.ongoing].map((e) => e.city).filter(Boolean));
    state.cities = [...CITY_ORDER.filter((c) => citySet.has(c)), ...[...citySet].filter((c) => !CITY_ORDER.includes(c)).sort()];
    if (data.updated) $("#updated").textContent = "Updated " + new Date(data.updated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

    buildChips(); buildSubmitCategories(); render();
  }

  function normalizeSubmission(s) {
    if (!s || !s.title || !s.date) return null;
    const multi = s.endDate && s.endDate > s.date;
    return {
      id: "sub-" + s.id, title: s.title, date: s.date, start: s.start || null, end: s.end || null,
      venue: s.venue || "", address: s.address || "", city: s.city || "", category: s.category || "Community",
      url: safeUrl(s.url), infoUrl: "", source: "Scout & Tell reader submission", image: safeUrl(s.image) || null,
      price: s.price || "", desc: s.desc || "",
      runsThrough: multi && (parseYmd(s.endDate) - parseYmd(s.date)) / 864e5 >= 14 ? s.endDate : null,
    };
  }

  // ---------------------------------------------------------------- filters
  function buildChips() {
    const mk = (box, items, set) => {
      box.innerHTML = items.map((v) => `<button type="button" data-v="${esc(v)}">${esc(v)}</button>`).join("");
      box.onclick = (ev) => {
        const b = ev.target.closest("button"); if (!b) return;
        const v = b.dataset.v; set.has(v) ? set.delete(v) : set.add(v);
        b.classList.toggle("on"); state.listLimit = LIST_PAGE; render();
      };
    };
    const used = new Set([...state.events, ...state.ongoing].map((e) => e.category));
    mk($("#cities"), state.cities, state.selCities);
    mk($("#cats"), state.categories.filter((c) => used.has(c)), state.selCats);
  }

  function buildSubmitCategories() {
    $("#subCat").innerHTML = '<option value="">Choose…</option>' + state.categories.map((c) => `<option>${esc(c)}</option>`).join("");
  }

  function passes(e, ignoreWhen = false) {
    if (state.selCities.size && !state.selCities.has(e.city)) return false;
    if (state.selCats.size && !state.selCats.has(e.category)) return false;
    if (state.q) {
      const hay = `${e.title} ${e.venue} ${e.city} ${e.desc} ${e.category}`.toLowerCase();
      if (!state.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    if (ignoreWhen) return true;
    const t = today(), d = e.date;
    switch (state.when) {
      case "today": return d === ymd(t);
      case "7": return d <= ymd(addDays(t, 6));
      case "weekend": {
        const dow = t.getDay();
        const fri = dow === 0 ? addDays(t, -2) : addDays(t, 5 - dow);
        return d >= ymd(fri < t ? t : fri) && d <= ymd(addDays(fri, 2));
      }
      case "free": return /\bfree\b|^\$?0(\.00)?$/i.test(e.price || "");
      default: return true;
    }
  }

  // ---------------------------------------------------------------- render
  function render() {
    $$(".st-views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === state.view)));
    $("#nav").hidden = state.view === "list";
    const list = state.events.filter((e) => passes(e, state.view !== "list"));
    if (state.view === "list") renderList(list);
    else if (state.view === "week") renderWeek(list);
    else renderMonth(list);
    renderOngoing();
    postHeight();
  }

  function card(e) {
    const img = safeUrl(e.image)
      ? `<img class="st-thumb" src="${esc(e.image)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'st-thumb-empty'}))">`
      : `<div class="st-thumb-empty"></div>`;
    const where = [e.venue, e.city].filter(Boolean).join(" · ");
    const when = e.runsThrough
      ? `Through<small>${esc(fmtShort.format(parseYmd(e.runsThrough)))}</small>`
      : `${esc(e.start ? fmtTime(e.start) : "All day")}${e.end ? `<small>to ${esc(fmtTime(e.end))}</small>` : ""}`;
    return `<button type="button" class="st-card" data-id="${esc(e.id)}">
      <div class="st-time">${when}</div>
      <div><p class="st-title">${esc(e.title)}</p><div class="st-meta">${esc(where)}</div><span class="st-tag">${esc(e.category)}</span></div>
      ${img}</button>`;
  }

  function renderList(list) {
    const shown = list.slice(0, state.listLimit);
    $("#count").textContent = list.length ? `${list.length.toLocaleString()} event${list.length === 1 ? "" : "s"}` : "";
    if (!list.length) { $("#view").innerHTML = emptyMsg(); return; }
    const byDay = groupByDay(shown);
    let html = "";
    for (const [day, evs] of byDay) {
      html += `<div class="st-day"><div class="st-day-head"><h3>${esc(fmtDay.format(parseYmd(day)))}</h3><span>${evs.length} event${evs.length === 1 ? "" : "s"}</span></div>
        <div class="st-list">${evs.map(card).join("")}</div></div>`;
    }
    if (list.length > shown.length) html += `<button class="st-btn st-btn-ghost st-more" id="more">Show more events</button>`;
    $("#view").innerHTML = html;
    const more = $("#more"); if (more) more.onclick = () => { state.listLimit += LIST_PAGE; render(); };
  }

  function renderWeek(list) {
    const start = startOfWeek(state.cursor), end = addDays(start, 6);
    $("#range").textContent = `${fmtShort.format(start)} – ${fmtShort.format(end)}`;
    const byDay = groupByDay(list.filter((e) => e.date >= ymd(start) && e.date <= ymd(end)));
    const t = ymd(today());
    let total = 0, html = '<div class="st-week">';
    for (let i = 0; i < 7; i++) {
      const d = addDays(start, i), key = ymd(d), evs = byDay.get(key) || [];
      total += evs.length;
      html += `<div class="st-wcol${key === t ? " today" : ""}"><h4>${d.toLocaleDateString("en-US", { weekday: "short" })}<b>${d.getDate()}</b></h4>
        ${evs.slice(0, 12).map((e) => pill(e, true)).join("")}
        ${evs.length > 12 ? `<button class="st-pill-more" data-day="${key}">+${evs.length - 12} more</button>` : ""}</div>`;
    }
    $("#view").innerHTML = html + "</div>";
    $("#count").textContent = `${total} event${total === 1 ? "" : "s"} this week`;
  }

  function renderMonth(list) {
    const c = state.cursor, first = new Date(c.getFullYear(), c.getMonth(), 1);
    const gridStart = startOfWeek(first);
    $("#range").textContent = fmtMonth.format(first);
    const byDay = groupByDay(list);
    const t = ymd(today());
    let total = 0;
    let html = '<div class="st-month">' + ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => `<div class="st-dow">${d}</div>`).join("");
    for (let i = 0; i < 42; i++) {
      const d = addDays(gridStart, i), key = ymd(d), evs = byDay.get(key) || [];
      if (i >= 35 && d.getMonth() !== c.getMonth()) break;
      const inMonth = d.getMonth() === c.getMonth();
      if (inMonth) total += evs.length;
      html += `<div class="st-cell${inMonth ? "" : " out"}${key === t ? " today" : ""}" data-day="${key}">
        <span class="st-num">${d.getDate()}</span>
        ${evs.slice(0, 3).map((e) => pill(e, false)).join("")}
        ${evs.length > 3 ? `<button class="st-pill-more" data-day="${key}">+${evs.length - 3} more</button>` : ""}
        ${evs.length ? `<span class="st-dots">${evs.length} event${evs.length === 1 ? "" : "s"}</span>` : ""}</div>`;
    }
    $("#view").innerHTML = html + "</div>";
    $("#count").textContent = `${total} event${total === 1 ? "" : "s"} in ${fmtMonth.format(first).split(" ")[0]}`;
  }

  function pill(e, withTime) {
    return `<button type="button" class="st-pill" data-id="${esc(e.id)}" title="${esc(e.title)}">${esc(e.title)}${withTime ? `<i>${esc(timeRange(e))}${e.city ? " · " + esc(e.city) : ""}</i>` : ""}</button>`;
  }

  function renderOngoing() {
    const list = state.ongoing.filter((e) => passes(e, true)).sort((a, b) => a.runsThrough.localeCompare(b.runsThrough));
    $("#ongoingWrap").hidden = !list.length;
    $("#ongoingCount").textContent = `(${list.length})`;
    $("#ongoing").innerHTML = list.map(card).join("");
  }

  function groupByDay(list) {
    const m = new Map();
    for (const e of list) { if (!m.has(e.date)) m.set(e.date, []); m.get(e.date).push(e); }
    return m;
  }

  function emptyMsg() {
    return `<div class="st-empty">Nothing matches those filters yet. Try another town or type, or <a href="#" data-open="submit">submit an event</a>.</div>`;
  }

  // ---------------------------------------------------------------- detail
  function openEvent(id) {
    const e = [...state.events, ...state.ongoing].find((x) => x.id === id);
    if (!e) return;
    const dateLine = e.runsThrough
      ? `Now through ${fmtDay.format(parseYmd(e.runsThrough))}`
      : `${fmtDay.format(parseYmd(e.date))}`;
    const where = [e.venue, e.address, e.city].filter(Boolean);
    const map = where.length ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(where.join(", ") + ", CO")}` : "";
    const link = safeUrl(e.url);
    const info = safeUrl(e.infoUrl);
    $("#eventBody").innerHTML = `
      ${safeUrl(e.image) ? `<img class="st-ev-img" src="${esc(e.image)}" alt="" onerror="this.remove()">` : ""}
      <div class="st-ev">
        <span class="st-tag">${esc(e.category)}</span>
        <h2 id="evTitle">${esc(e.title)}</h2>
        <dl>
          <dt>When</dt><dd>${esc(dateLine)}${e.runsThrough ? "" : `<br>${esc(timeRange(e))}`}</dd>
          ${where.length ? `<dt>Where</dt><dd>${esc(where.join(", "))}${map ? ` · <a href="${map}" target="_blank" rel="noopener">Map</a>` : ""}</dd>` : ""}
          ${e.price ? `<dt>Cost</dt><dd>${esc(e.price)}</dd>` : ""}
        </dl>
        ${e.desc ? `<p>${esc(e.desc)}</p>` : ""}
        <div class="st-actions">
          ${link ? `<a class="st-btn st-btn-solid" href="${esc(link)}" target="_blank" rel="noopener">Event details &amp; tickets →</a>` : ""}
          <div class="st-addcal"><button class="st-btn st-btn-ghost" type="button" id="addCalBtn">Add to calendar</button></div>
        </div>
        <p class="st-src">Listed by ${info && info !== link ? `<a href="${esc(info)}" target="_blank" rel="noopener">${esc(e.source)}</a>` : esc(e.source)}. Confirm details with the host before you go.</p>
      </div>`;
    $("#addCalBtn").onclick = (ev) => toggleAddCal(ev.currentTarget.parentElement, e);
    openDialog($("#eventModal"));
    track("event_open", e);
  }

  function toggleAddCal(wrap, e) {
    const existing = $(".st-addcal-menu", wrap);
    if (existing) { existing.remove(); return; }
    const { start, end, allDay } = calTimes(e);
    const g = new URL("https://calendar.google.com/calendar/render");
    g.searchParams.set("action", "TEMPLATE"); g.searchParams.set("text", e.title);
    g.searchParams.set("dates", `${start}/${end}`);
    g.searchParams.set("details", [e.desc, e.url].filter(Boolean).join("\n\n"));
    g.searchParams.set("location", [e.venue, e.address, e.city].filter(Boolean).join(", "));
    const o = new URL("https://outlook.live.com/calendar/0/deeplink/compose");
    o.searchParams.set("subject", e.title); o.searchParams.set("body", [e.desc, e.url].filter(Boolean).join("\n\n"));
    o.searchParams.set("location", [e.venue, e.address, e.city].filter(Boolean).join(", "));
    o.searchParams.set("startdt", isoLocal(e, false)); o.searchParams.set("enddt", isoLocal(e, true));
    if (allDay) o.searchParams.set("allday", "true");
    const menu = document.createElement("div");
    menu.className = "st-addcal-menu";
    menu.innerHTML = `<a href="${esc(g)}" target="_blank" rel="noopener">Google Calendar</a>
      <a href="${esc(o)}" target="_blank" rel="noopener">Outlook</a>
      <a href="#" id="icsLink">Apple / other (.ics)</a>`;
    wrap.appendChild(menu);
    $("#icsLink").onclick = (ev) => { ev.preventDefault(); downloadIcs(e); };
  }

  function calTimes(e) {
    const d = e.date.replace(/-/g, "");
    if (!e.start) {
      const nd = ymd(addDays(parseYmd(e.date), 1)).replace(/-/g, "");
      return { start: d, end: nd, allDay: true };
    }
    const s = e.start.replace(":", "") + "00";
    const en = (e.end || addHour(e.start)).replace(":", "") + "00";
    return { start: `${d}T${s}`, end: `${d}T${en}`, allDay: false };
  }
  function addHour(t) { const [h, m] = t.split(":").map(Number); return `${String(Math.min(h + 2, 23)).padStart(2, "0")}:${String(m).padStart(2, "0")}`; }
  function isoLocal(e, isEnd) { return e.start ? `${e.date}T${isEnd ? (e.end || addHour(e.start)) : e.start}:00` : e.date; }

  function downloadIcs(e) {
    const { start, end, allDay } = calTimes(e);
    const fold = (s) => String(s || "").replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/[,;]/g, (c) => "\\" + c);
    const ics = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Scout & Tell//Events//EN", "BEGIN:VEVENT",
      `UID:${e.id}@scoutandtell.com`, `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").split(".")[0]}Z`,
      allDay ? `DTSTART;VALUE=DATE:${start}` : `DTSTART;TZID=America/Denver:${start}`,
      allDay ? `DTEND;VALUE=DATE:${end}` : `DTEND;TZID=America/Denver:${end}`,
      `SUMMARY:${fold(e.title)}`, `LOCATION:${fold([e.venue, e.address, e.city].filter(Boolean).join(", "))}`,
      `DESCRIPTION:${fold([e.desc, e.url].filter(Boolean).join("\n\n"))}`, e.url ? `URL:${e.url}` : "",
      "END:VEVENT", "END:VCALENDAR",
    ].filter(Boolean).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
    a.download = e.title.replace(/[^a-z0-9]+/gi, "-").slice(0, 60) + ".ics";
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ---------------------------------------------------------------- submit
  async function submit(ev) {
    ev.preventDefault();
    const form = ev.currentTarget, msg = $("#submitMsg");
    const data = Object.fromEntries(new FormData(form));
    if (data.website) return; // spam trap
    if (!safeUrl(state.config.submitEndpoint)) {
      msg.className = "st-form-msg err"; msg.textContent = "Submissions aren't switched on yet. Please check back soon.";
      return;
    }
    const btn = $("button[type=submit]", form);
    btn.disabled = true; msg.className = "st-form-msg"; msg.textContent = "Sending…";
    try {
      // text/plain keeps this a "simple" request that Apps Script accepts without CORS preflight.
      await fetch(state.config.submitEndpoint, { method: "POST", mode: "no-cors", headers: { "Content-Type": "text/plain;charset=utf-8" }, body: JSON.stringify(data) });
      form.reset();
      msg.className = "st-form-msg ok"; msg.textContent = "Thanks! Your event is in for review. Once it's approved, it'll show up on the calendar.";
    } catch (e) {
      msg.className = "st-form-msg err"; msg.textContent = "Something went wrong. Please try again in a minute.";
    } finally { btn.disabled = false; postHeight(); }
  }

  // ---------------------------------------------------------------- embed
  // Tell the Scout & Tell page how tall the calendar is, so the iframe fits.
  let lastH = 0;
  function postHeight() {
    requestAnimationFrame(() => {
      const h = Math.ceil(document.documentElement.scrollHeight);
      if (window.parent !== window && Math.abs(h - lastH) > 4) { lastH = h; window.parent.postMessage({ type: "st-cal-height", height: h }, "*"); }
    });
  }
  function track(name, e) { try { window.parent.postMessage({ type: "st-cal-event", name, title: e.title }, "*"); } catch (_) {} }

  // When embedded, the calendar frame is as tall as the whole page, so a centered
  // dialog would open far from where the reader is. Open it next to the click instead.
  function openDialog(dlg) {
    if (EMBEDDED) {
      dlg.style.position = "absolute";
      dlg.style.margin = "0 auto";
      dlg.style.top = Math.max(16, lastClickY - 140) + "px";
      dlg.style.maxHeight = "none";
    }
    dlg.showModal();
    if (EMBEDDED) dlg.scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("pointerdown", (ev) => { lastClickY = ev.pageY; }, true);

  // ---------------------------------------------------------------- wire up
  document.addEventListener("click", (ev) => {
    const id = ev.target.closest("[data-id]")?.dataset.id;
    if (id) return openEvent(id);
    const more = ev.target.closest(".st-pill-more, .st-cell");
    if (more?.dataset.day && (ev.target.closest(".st-pill-more") || window.innerWidth <= 760)) {
      state.view = "list"; state.when = "all"; state.listLimit = LIST_PAGE;
      $$("#quick button").forEach((b) => b.classList.toggle("on", b.dataset.when === "all"));
      render();
      const day = $$(".st-day-head h3").find((h) => h.textContent === fmtDay.format(parseYmd(more.dataset.day)));
      day?.scrollIntoView({ block: "start" });
      return;
    }
    if (ev.target.closest("[data-close]")) ev.target.closest("dialog").close();
    if (ev.target.closest("[data-open=submit]")) { ev.preventDefault(); openDialog($("#submitModal")); }
    if (ev.target.tagName === "DIALOG") ev.target.close(); // click on backdrop
  });
  $$(".st-views button").forEach((b) => (b.onclick = () => { state.view = b.dataset.view; render(); }));
  $("#quick").onclick = (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.when = b.dataset.when; state.listLimit = LIST_PAGE;
    $$("#quick button").forEach((x) => x.classList.toggle("on", x === b));
    if (state.view !== "list") state.view = "list";
    render();
  };
  let qTimer;
  $("#q").oninput = (ev) => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = ev.target.value.trim().toLowerCase(); state.listLimit = LIST_PAGE; render(); }, 150); };
  $("#prev").onclick = () => shift(-1);
  $("#next").onclick = () => shift(1);
  $("#todayBtn").onclick = () => { state.cursor = today(); render(); };
  function shift(n) {
    const c = state.cursor;
    state.cursor = state.view === "week" ? addDays(c, 7 * n) : new Date(c.getFullYear(), c.getMonth() + n, 1);
    render();
  }
  $("#submitForm").onsubmit = submit;
  window.addEventListener("resize", postHeight);
  new ResizeObserver(postHeight).observe(document.body);

  load().catch((err) => {
    console.error(err);
    $("#view").innerHTML = `<div class="st-empty">The calendar couldn't load right now. Please refresh in a moment.</div>`;
  });
})();
