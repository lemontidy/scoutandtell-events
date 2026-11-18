#!/usr/bin/env python3
"""
Scout & Tell events collector.

Pulls upcoming events from:
  - Visit Fort Collins  (Simpleview API)
  - Visit Estes Park    (Simpleview API)
  - Visit Greeley       (Simpleview API)
  - Visit Loveland      (off: its Yodel widget blocks GitHub's servers)

Writes docs/events.json, which the calendar page reads.
Runs nightly from .github/workflows/update-events.yml.

Each source is collected independently. If one source fails, the others are
still written, and the failed source keeps yesterday's events so the calendar
never goes empty because one site had a bad night.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urljoin
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "events.json"
TZ = ZoneInfo("America/Denver")
DAYS_AHEAD = 90
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

SIMPLEVIEW_SOURCES = [
    {"key": "fortcollins", "name": "Visit Fort Collins", "base": "https://www.visitftcollins.com", "city": "Fort Collins"},
    {"key": "estespark", "name": "Visit Estes Park", "base": "https://www.visitestespark.com", "city": "Estes Park"},
    {"key": "greeley", "name": "Visit Greeley", "base": "https://www.visitgreeley.com", "city": "Greeley"},
]
INCLUDE_LOVELAND = False
LOVELAND = {
    "key": "loveland",
    "name": "Visit Loveland",
    "widget": "https://events.yodel.today/y/widget/68dbdffe17fb4973f7a16bef",
    "city": "Loveland",
}

# ---------------------------------------------------------------- categories
# One shared set of categories for the calendar's filter chips.
CATEGORIES = [
    ("Community", r"food drive|toy drive|coat drive|blood drive|volunteer|fundraiser|benefit for"),
    ("Music", r"music|concert|on tour|\btour\b.*(live|band)|band|live|jazz|symphony|orchestra|choir|bluegrass|dj\b|open mic|singer|songwriter"),
    ("Comedy", r"comedy|comedian|improv|stand-?up"),
    ("Theater & Dance", r"theat|theatre|play\b|musical|ballet|dance|opera|performing|nutcracker|broadway"),
    ("Arts & Exhibits", r"\bart\b|arts|exhibit|gallery|museum|sculpture|paint|craft|photograph|artist"),
    ("Food & Drink", r"food|drink|beer|brew|wine|cider|distill|tasting|dinner|brunch|culinary|chef|taproom|restaurant|cocktail"),
    ("Festivals & Markets", r"festival|fest\b|market|fair\b|bazaar|parade|celebration|holiday lights|tree lighting"),
    ("Family & Kids", r"kid|family|child|youth|teen|storytime|santa|toddler|all ages"),
    ("Outdoors & Active", r"outdoor|hike|trail|run\b|5k|10k|race|bike|ride|yoga|nature|park|ski|snowshoe|climb|walk\b|fishing|wildlife"),
    ("Sports", r"sport|hockey|football|basketball|baseball|soccer|rodeo|game\b|tournament|wrestling|volleyball"),
    ("Classes & Workshops", r"class|workshop|lesson|lecture|seminar|course|learn|talk\b|walking tour|guided tour|audio tour"),
    ("Community", r"community|volunteer|fundraiser|benefit|charity|meeting|networking|drive\b|library|club"),
]
_CAT_RE = [(name, re.compile(pat, re.I)) for name, pat in CATEGORIES]


def pick_category(source_cats: list[str], title: str, desc: str = "") -> str:
    # Source categories are the strongest signal, then the title, then the description.
    for text in (" | ".join(source_cats), title, desc[:300]):
        for name, rx in _CAT_RE:
            if text and rx.search(text):
                return name
    return "Community"


# ------------------------------------------------------------------- helpers
def clean_text(s: str | None, limit: int = 280) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def hhmm(t: str | None) -> str | None:
    """'19:00:00' -> '19:00'; anything odd -> None."""
    if not t:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})", t.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 0 and mi == 0:
        return None  # midnight almost always means "no time given"
    return f"{h:02d}:{mi:02d}"


def local_date(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).date().isoformat()


def local_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


_CITY_FIX = {
    "ft collins": "Fort Collins", "ft. collins": "Fort Collins", "fort collind": "Fort Collins",
    "ftc": "Fort Collins", "fort": "Fort Collins", "foco": "Fort Collins", "estes": "Estes Park", "la porte": "Laporte",
}


def norm_city(c: str | None) -> str:
    c = clean_text(c, 60).strip(" ,.")
    if not c:
        return ""
    c = re.sub(r",?\s*(co|colorado)(\s+\d{5})?$", "", c, flags=re.I).strip()
    fixed = _CITY_FIX.get(c.lower())
    if fixed:
        return fixed
    return " ".join(w.capitalize() if w.isupper() or w.islower() else w for w in c.split())


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"})
    return s


# ---------------------------------------------------------------- simpleview
SV_FIELDS = {
    "title": 1, "url": 1, "linkUrl": 1, "date": 1, "startDate": 1, "endDate": 1,
    "startTime": 1, "endTime": 1, "location": 1, "address1": 1, "city": 1,
    "categories": 1, "media_raw": 1, "admission": 1, "description": 1,
    "recurrence": 1, "recid": 1, "listing.title": 1,
}


def day_boundary(d: datetime) -> str:
    # Simpleview's firewall rejects arbitrary timestamps; send local midnight.
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=TZ)
    return local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def collect_simpleview(src: dict) -> list[dict]:
    """
    Simpleview returns each event once per requested date range, so a daily
    exhibit would only show on its first day. Asking one day at a time returns
    every event happening that day, which gives us each date it runs.
    """
    s = session()
    base = src["base"]
    tok = s.get(f"{base}/plugins/core/get_simple_token/", timeout=30).text.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", tok):
        raise RuntimeError(f"{src['name']}: unexpected token response")

    today = datetime.now(TZ)
    events, failures = [], 0
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        start, end = day_boundary(day), day_boundary(day + timedelta(days=1))
        skip, page = 0, 100
        while True:
            q = {
                "filter": {"active": True, "date_range": {"start": {"$date": start}, "end": {"$date": end}}},
                "options": {
                    "limit": page, "skip": skip, "count": True, "castDocs": False,
                    "fields": SV_FIELDS, "sort": {"date": 1, "rank": 1, "title_sort": 1},
                },
            }
            url = (f"{base}/includes/rest_v2/plugins_events_events_by_date/find/"
                   f"?json={quote(json.dumps(q, separators=(',', ':')))}&token={tok}")
            try:
                r = s.get(url, timeout=60)
                r.raise_for_status()
                data = r.json()["docs"]
            except Exception as e:
                failures += 1
                if failures > 10:
                    raise RuntimeError(f"too many failed requests ({e})")
                time.sleep(3)
                break
            docs = data.get("docs", [])
            day_iso = day.date().isoformat()
            for d in docs:
                ev = simpleview_to_event(d, src, day_iso)
                if ev:
                    events.append(ev)
            skip += page
            if not docs or skip >= data.get("count", 0):
                break
        time.sleep(0.3)
    return events


def simpleview_to_event(d: dict, src: dict, day_iso: str | None = None) -> dict | None:
    title = clean_text(d.get("title"), 160)
    date = day_iso or local_date(d.get("date"))
    if not title or not date:
        return None
    detail = urljoin(src["base"], d.get("url") or "")
    link = (d.get("linkUrl") or "").strip()
    if link and not re.match(r"^https?://", link, re.I):
        link = "https://" + link.lstrip("/")
    cats = [c.get("catName", "") for c in (d.get("categories") or []) if isinstance(c, dict)]
    media = d.get("media_raw") or []
    image = media[0].get("mediaurl") if media and isinstance(media[0], dict) else None
    desc = clean_text(d.get("description"))
    last = local_date(d.get("endDate"))
    venue = clean_text(d.get("location") or (d.get("listing") or {}).get("title"), 120)
    return {
        "id": make_id(src["key"], str(d.get("recid") or d.get("_id") or title), date),
        "title": title,
        "date": date,
        "start": hhmm(d.get("startTime")),
        "end": hhmm(d.get("endTime")),
        "venue": venue,
        "address": clean_text(d.get("address1"), 160),
        "city": norm_city(d.get("city")) or src["city"],
        "category": pick_category(cats, title, desc),
        "url": link or detail,          # the organizer's own page when there is one
        "infoUrl": detail,              # the Visit [city] listing, as a backup
        "source": src["name"],
        "image": image,
        "price": clean_text(d.get("admission"), 80),
        "desc": desc,
        "runsThrough": None,
        "_series": make_id(src["key"], str(d.get("recid") or title)),
        "_seriesEnd": last,
    }


# ------------------------------------------------------------------ loveland
def collect_loveland(src: dict) -> list[dict]:
    from playwright.sync_api import sync_playwright

    horizon = datetime.now(TZ) + timedelta(days=DAYS_AHEAD)
    links: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        page.goto(src["widget"], wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_selector('a[href*="/y/event/"]', timeout=45_000)
        except Exception:
            print(f"  Loveland: no event links after load; title={page.title()!r} "
                  f"text={page.inner_text('body')[:200]!r}", file=sys.stderr)
        stalls = 0
        for _ in range(60):  # each click loads roughly 24 more events
            before = page.locator('a[href*="/y/event/"]').count()
            btn = page.get_by_text("Load More Events", exact=False)
            if btn.count() == 0:
                break
            try:
                btn.first.click(timeout=10_000)
                page.wait_for_timeout(2500)
            except Exception:
                break
            after = page.locator('a[href*="/y/event/"]').count()
            stalls = stalls + 1 if after == before else 0
            if stalls >= 2:
                break
            # Stop once the last card is past our horizon.
            last_month_day = page.evaluate(_LAST_CARD_DATE_JS)
            if last_month_day and _card_date(last_month_day) and _card_date(last_month_day) > horizon.date():
                break
        cards = page.evaluate(_CARDS_JS)
        print(f"  Loveland: {len(cards)} event links found in widget", file=sys.stderr)
        browser.close()

    for c in cards:
        href = c.get("href")
        if href and href not in links:
            links[href] = c

    s = session()
    events = []
    for href, card in links.items():
        url = urljoin("https://events.yodel.today", href)
        ld = None
        try:
            r = s.get(url, timeout=30)
            if r.ok:
                ld = _first_event_ld(r.text)
        except requests.RequestException:
            pass
        ev = loveland_to_event(url, card, ld, src)
        if ev:
            d = datetime.fromisoformat(ev["date"]).date()
            if d <= horizon.date():
                events.append(ev)
        time.sleep(0.25)
    return events


_CARDS_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('a[href*="/y/event/"]').forEach(a => {
    let card = a;
    for (let i = 0; i < 8 && card.parentElement; i++) {
      card = card.parentElement;
      if (card.innerText.split('\n').filter(Boolean).length >= 4) break;
    }
    const lines = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);
    const img = card.querySelector('img');
    out.push({
      href: new URL(a.href).pathname,
      lines: lines.slice(0, 8),
      image: img ? img.src : null,
    });
  });
  return out;
}
"""

_LAST_CARD_DATE_JS = r"""
() => {
  const a = [...document.querySelectorAll('a[href*="/y/event/"]')].pop();
  if (!a) return null;
  let card = a;
  for (let i = 0; i < 8 && card.parentElement; i++) {
    card = card.parentElement;
    if (card.innerText.split('\n').filter(Boolean).length >= 4) break;
  }
  const l = card.innerText.split('\n').map(s => s.trim()).filter(Boolean);
  return l.length > 1 ? l[0] + ' ' + l[1] : null;
}
"""

_MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _card_date(text: str):
    m = re.match(r"([A-Za-z]{3})\s+(\d{1,2})", text or "")
    if not m or m.group(1).upper() not in _MONTHS:
        return None
    today = datetime.now(TZ).date()
    month, day = _MONTHS[m.group(1).upper()], int(m.group(2))
    year = today.year if (month, day) >= (today.month, today.day) or month >= today.month - 1 else today.year + 1
    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None


def _first_event_ld(page_html: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for it in items:
            if isinstance(it, dict) and "Event" in str(it.get("@type", "")):
                return it
    return None


def loveland_to_event(url: str, card: dict, ld: dict | None, src: dict) -> dict | None:
    lines = card.get("lines") or []
    title = clean_text((ld or {}).get("name") or (lines[2] if len(lines) > 2 else ""), 160)
    if not title:
        return None

    start_dt = local_dt((ld or {}).get("startDate"))
    end_dt = local_dt((ld or {}).get("endDate"))
    if start_dt:
        date = start_dt.date().isoformat()
    else:
        cd = _card_date(" ".join(lines[:2]))
        if not cd:
            return None
        date = cd.isoformat()

    # Multi-day listings start in the past; show them from today.
    today = datetime.now(TZ).date()
    runs_through = None
    if end_dt and start_dt and (end_dt.date() - start_dt.date()).days >= 1:
        if start_dt.date() < today:
            date = today.isoformat()
        if (end_dt.date() - start_dt.date()).days >= 14:
            runs_through = end_dt.date().isoformat()

    start = start_dt.strftime("%H:%M") if start_dt and start_dt.strftime("%H:%M") != "00:00" else None
    end = end_dt.strftime("%H:%M") if end_dt and end_dt.date() == (start_dt.date() if start_dt else None) else None

    loc = (ld or {}).get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = loc.get("address") if isinstance(loc, dict) else None
    street = addr.get("streetAddress") if isinstance(addr, dict) else (addr if isinstance(addr, str) else "")
    city = norm_city(addr.get("addressLocality") if isinstance(addr, dict) else None) or src["city"]
    venue = clean_text(loc.get("name") if isinstance(loc, dict) else "", 120)
    if not venue:
        promoted = next((l for l in lines if l.lower().startswith("promoted by")), "")
        venue = clean_text(promoted.split(":", 1)[-1], 120)

    img = (ld or {}).get("image") or card.get("image")
    if isinstance(img, list):
        img = img[0] if img else None
    if isinstance(img, dict):
        img = img.get("url")

    desc = clean_text((ld or {}).get("description"))
    return {
        "id": make_id(src["key"], url.rsplit("/", 1)[-1], date),
        "title": title,
        "date": date,
        "start": start,
        "end": end,
        "venue": venue,
        "address": clean_text(street, 160),
        "city": clean_text(city, 60),
        "category": pick_category([], title, desc),
        "url": url,
        "infoUrl": url,
        "source": src["name"],
        "image": img,
        "price": "",
        "desc": desc,
        "runsThrough": runs_through,
    }


# ---------------------------------------------------------------------- main
def dedupe(events: list[dict]) -> list[dict]:
    """The same event often appears on two Visit sites. Keep the richer copy."""
    best: dict[tuple, dict] = {}
    for ev in events:
        k = (norm_title(ev["title"]), ev["date"])
        cur = best.get(k)
        if cur is None or _richness(ev) > _richness(cur):
            best[k] = ev
    return list(best.values())


def _richness(ev: dict) -> int:
    return sum(bool(ev.get(f)) for f in ("start", "venue", "image", "desc", "price")) + (ev["url"] != ev["infoUrl"]) * 2


def collapse_daily_series(events: list[dict]) -> list[dict]:
    """
    Simpleview lists one row per day for exhibits and daily runs, which would
    bury the calendar. A series that shows up on 20+ days in the window becomes
    a single "ongoing" listing. Weekly shows (fewer dates) keep every date.
    """
    groups: dict[str, list[dict]] = {}
    for ev in events:
        groups.setdefault(ev.get("_series") or ev["id"], []).append(ev)
    out = []
    today = datetime.now(TZ).date().isoformat()
    for evs in groups.values():
        if len(evs) >= 20:
            evs.sort(key=lambda e: e["date"])
            first = dict(evs[0])
            first["date"] = max(first["date"], today)
            first["runsThrough"] = first.get("_seriesEnd") or evs[-1]["date"]
            out.append(first)
        else:
            out += evs
    for ev in out:
        ev.pop("_series", None)
        ev.pop("_seriesEnd", None)
    return out


def main() -> int:
    previous = {}
    if OUT.exists():
        try:
            for ev in json.loads(OUT.read_text()).get("events", []):
                previous.setdefault(ev.get("source"), []).append(ev)
        except Exception:
            pass

    all_events, status = [], {}
    jobs = [(s["name"], (lambda s=s: collect_simpleview(s))) for s in SIMPLEVIEW_SOURCES]
    # Visit Loveland is turned off: its calendar host (Yodel) blocks GitHub's servers.
    # To try it again, set INCLUDE_LOVELAND = True near the top of this file.
    if INCLUDE_LOVELAND:
        jobs.append((LOVELAND["name"], lambda: collect_loveland(LOVELAND)))

    for name, job in jobs:
        try:
            evs = job()
            if not evs:
                raise RuntimeError("returned no events")
            all_events += evs
            status[name] = {"ok": True, "count": len(evs)}
            print(f"[ok]   {name}: {len(evs)} events")
        except Exception as e:
            kept = previous.get(name, [])
            all_events += kept
            status[name] = {"ok": False, "error": str(e)[:200], "kept": len(kept)}
            print(f"[FAIL] {name}: {e} (kept {len(kept)} from last run)", file=sys.stderr)
            traceback.print_exc()

    today = datetime.now(TZ).date().isoformat()
    events = [e for e in dedupe(collapse_daily_series(all_events)) if e["date"] >= today]
    events.sort(key=lambda e: (e["date"], e["start"] or "99:99", e["title"].lower()))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(TZ).isoformat(timespec="minutes"),
        "sources": status,
        "categories": [c for c in dict.fromkeys(c for c, _ in CATEGORIES) if c != "Community"] + ["Community"],
        "events": events,
    }, ensure_ascii=False, indent=0))
    print(f"Wrote {len(events)} events to {OUT}")
    return 0 if any(v["ok"] for v in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
