#!/usr/bin/env python3
"""
Scout & Tell jobs collector.

Pulls Northern Colorado job openings from:
  - Adzuna      (free API, runs every night)
  - SerpApi     (Google Jobs, which includes Indeed, ZipRecruiter, LinkedIn and
                 employers' own sites). Free plan = 250 searches a month, so it
                 only runs on Mondays and Thursdays and never goes over BUDGET.

Writes docs/jobs/jobs.json, which the job board page reads.
Runs from .github/workflows/update-jobs.yml.

Keys come from GitHub secrets (Settings -> Secrets and variables -> Actions):
  ADZUNA_APP_ID, ADZUNA_APP_KEY, SERPAPI_KEY
A missing key just skips that source; the board keeps working.

Each source is kept separately. If a source fails or is skipped, its jobs from
the last good run stay on the board until they age out.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "jobs" / "jobs.json"
TZ = ZoneInfo("America/Denver")

# ---------------------------------------------------------------- settings
# Towns that count as Northern Colorado. Anything else is dropped.
TOWNS = [
    "Fort Collins", "Loveland", "Greeley", "Windsor", "Berthoud", "Estes Park",
    "Wellington", "Timnath", "Johnstown", "Evans", "Severance", "Milliken",
    "Laporte", "Eaton", "Ault", "Mead", "Red Feather Lakes", "Bellvue",
]
_TOWN_FIX = {"la porte": "Laporte", "ft collins": "Fort Collins", "ft. collins": "Fort Collins"}

# Adzuna: town -> number of 50-job pages to pull each night (~16 calls a night;
# the free tier allows well over that).
ADZUNA_TOWNS = {
    "Fort Collins": 4, "Greeley": 3, "Loveland": 3, "Windsor": 1, "Estes Park": 1,
    "Berthoud": 1, "Wellington": 1, "Johnstown": 1, "Timnath": 1,
}

# SerpApi: one search each. 22 searches x ~9 runs a month = ~200, under the 250 free.
SERPAPI_SEARCHES = [
    ("restaurant jobs", "Fort Collins"), ("retail jobs", "Fort Collins"),
    ("salon spa jobs", "Fort Collins"), ("construction trades jobs", "Fort Collins"),
    ("healthcare jobs", "Fort Collins"), ("office admin jobs", "Fort Collins"),
    ("restaurant jobs", "Loveland"), ("retail jobs", "Loveland"),
    ("trades jobs", "Loveland"), ("office jobs", "Loveland"),
    ("restaurant jobs", "Greeley"), ("retail jobs", "Greeley"),
    ("trades jobs", "Greeley"), ("office jobs", "Greeley"),
    ("jobs", "Windsor"), ("restaurant retail jobs", "Windsor"),
    ("jobs", "Estes Park"), ("hospitality jobs", "Estes Park"),
    ("jobs", "Berthoud"), ("jobs", "Wellington"), ("jobs", "Timnath"),
    ("jobs", "Johnstown"),
]
SERPAPI_DAYS = {0, 3}          # Monday, Thursday (Mountain time)
SERPAPI_BUDGET = 230           # hard stop per calendar month; leaves ~20 for testing

# How long a job stays after its source last showed it.
KEEP_DAYS = {"Adzuna": 3, "Google Jobs": 9}
MAX_AGE_DAYS = 45              # drop anything posted longer ago than this

# Recruiters and staffing agencies are left off (they aren't local employers).
STAFFING = [
    "staffing", "recruit", "talent", "workforce", "employment agency", "robert half",
    "aerotek", "kelly services", "adecco", "randstad", "manpower", "express employment",
    "labor finders", "insight global", "teksystems", "jobot", "cybercoders", "kforce",
    "allegis", "spherion", "amergis", "aya healthcare", "amn healthcare", "cross country",
    "trusted health", "vivian health", "medical solutions", "fusion medical", "incredible health",
    "lucid staffing", "actalent", "apex systems", "peopleready", "trueblue", "snagajob",
    "jobs for humanity", "dice", "clickjobs", "lensa", "joblist", "talentify",
]
# Leave national chains on (they hire locally). Add names here to hide one.
HIDE_COMPANIES: list[str] = []

CATEGORIES = [
    ("Restaurants & Bars", ["cook", "chef", "server", "bartender", "barista", "dishwasher", "host",
                           "restaurant", "kitchen", "food", "busser", "pizza", "brewery", "taproom", "catering", "baker"]),
    ("Healthcare", ["nurse", "rn", "lpn", "cna", "medical", "health", "clinic", "dental", "pharmac", "therap",
                    "hospital", "caregiver", "patient", "physician", "veterinar", "vet tech", "behavioral"]),
    ("Trades & Construction", ["electric", "plumb", "hvac", "technician", "mechanic", "construction", "carpent",
                               "welder", "laborer", "landscap", "maintenance", "installer", "roof", "driver", "cdl",
                               "warehouse", "forklift", "operator", "painter", "concrete"]),
    ("Retail", ["retail", "sales associate", "cashier", "store", "merchandis", "stocker", "shop"]),
    ("Salons & Wellness", ["stylist", "salon", "barber", "esthetic", "massage", "nail", "spa", "fitness", "trainer", "yoga"]),
    ("Education & Childcare", ["teacher", "tutor", "school", "childcare", "child care", "preschool", "nanny", "educat", "para"]),
    ("Hospitality & Tourism", ["hotel", "housekeep", "front desk", "resort", "lodge", "guest", "tour", "event", "ranger"]),
    ("Office & Admin", ["admin", "office", "receptionist", "assistant", "coordinator", "bookkeep", "account",
                        "customer service", "clerk", "manager", "hr ", "human resources", "billing", "payroll"]),
    ("Tech & Engineering", ["software", "developer", "engineer", "it ", "data", "analyst", "cyber", "network"]),
]

AGGREGATORS = ["indeed", "linkedin", "ziprecruiter", "glassdoor", "monster", "simplyhired", "talent.com",
               "jooble", "careerbuilder", "lensa", "adzuna", "snagajob", "joblist", "learn4good", "salary.com",
               "bebee", "jobrapido", "whatjobs", "tallo", "upward", "jobilize", "builtin", "dice"]

UA = "ScoutAndTellJobs/1.0 (+https://www.scoutandtell.com/jobs)"


# ---------------------------------------------------------------- helpers
def now() -> datetime:
    return datetime.now(TZ)


def clean(s, limit: int = 0) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return s


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def make_id(title: str, company: str, town: str) -> str:
    company = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co|the)\b\.?", "", (company or "").lower())
    return hashlib.sha1("|".join(norm(p) for p in (title, company, town)).encode()).hexdigest()[:12]


def find_town(*texts: str) -> str:
    for t in texts:
        low = (t or "").lower()
        for k, v in _TOWN_FIX.items():
            if k in low:
                return v
        for town in TOWNS:
            if re.search(r"\b" + re.escape(town.lower()) + r"\b", low):
                return town
    return ""


def is_staffing(company: str) -> bool:
    c = (company or "").lower()
    return any(w in c for w in STAFFING) or any(h.lower() == c for h in HIDE_COMPANIES)


def pick_category(title: str, desc: str = "") -> str:
    t = f" {title.lower()} "
    for name, words in CATEGORIES:
        if any(w in t for w in words):
            return name
    d = f" {desc.lower()[:400]} "
    for name, words in CATEGORIES:
        if any(w in d for w in words):
            return name
    return "Other"


def job_type(*texts: str) -> str:
    t = " ".join(texts).lower().replace("-", " ").replace("_", " ")
    if "part time" in t:
        return "Part time"
    if any(w in t for w in ("contract", "temporary", "seasonal", "per diem", "prn")):
        return "Contract / Seasonal"
    if "full time" in t:
        return "Full time"
    return ""


def money(n: float) -> str:
    if n >= 1000:
        k = n / 1000
        return f"${k:.0f}k" if k >= 10 else f"${k:.1f}k".replace(".0k", "k")
    return f"${n:.2f}".replace(".00", "")


def fmt_pay(lo: float | None, hi: float | None, unit: str = "") -> tuple[str, float]:
    """Returns (label, yearly value used for sorting)."""
    vals = [v for v in (lo, hi) if v]
    if not vals:
        return "", 0
    lo, hi = min(vals), max(vals)
    if not unit:
        unit = "hr" if hi < 200 else "yr"
    yearly = hi * 2080 if unit == "hr" else hi
    label = money(lo) if lo == hi else f"{money(lo)}–{money(hi)}"
    return f"{label}/{unit}", yearly


_PAY_RE = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(k)?\s*(?:-|–|to)\s*\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(k)?"
    r"(?:\s*(?:per|an|a|/)\s*(hour|hr|year|yr|annually|annual))?",
    re.I,
)


def pay_from_text(text: str) -> tuple[str, float]:
    m = _PAY_RE.search(text or "")
    if not m:
        return "", 0
    lo = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    hi = float(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1)
    if lo <= 0 or hi < lo or hi > 1_000_000:
        return "", 0
    unit = (m.group(5) or "").lower()
    unit = "hr" if unit.startswith("h") else "yr" if unit else ""
    if not unit and hi < 200:
        unit = "hr"
    if unit == "hr" and hi < 7:     # not a wage
        return "", 0
    return fmt_pay(lo, hi, unit)


def with_utm(url: str) -> str:
    try:
        p = urlparse(url)
        if not p.scheme.startswith("http"):
            return url
        q = parse_qsl(p.query, keep_blank_values=True)
        if any(k.startswith("utm_") for k, _ in q):
            return url
        q += [("utm_source", "scoutandtell"), ("utm_medium", "jobboard")]
        return urlunparse(p._replace(query=urlencode(q)))
    except Exception:
        return url


def is_aggregator(url_or_name: str) -> bool:
    s = (url_or_name or "").lower()
    return any(a in s for a in AGGREGATORS)


def posted_from_relative(text: str) -> str | None:
    """'3 days ago' -> ISO date."""
    m = re.search(r"(\d+)\+?\s*(hour|day|week|month)", (text or "").lower())
    if not m:
        return now().date().isoformat() if "just" in (text or "").lower() or "today" in (text or "").lower() else None
    n, unit = int(m.group(1)), m.group(2)
    days = {"hour": 0, "day": n, "week": n * 7, "month": n * 30}[unit]
    return (now() - timedelta(days=days)).date().isoformat()


def http() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    return s


# ---------------------------------------------------------------- Adzuna
def collect_adzuna() -> list[dict]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("no ADZUNA_APP_ID / ADZUNA_APP_KEY secret yet")
    s, jobs = http(), []
    for town, pages in ADZUNA_TOWNS.items():
        for page in range(1, pages + 1):
            r = s.get(
                f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                params={
                    "app_id": app_id, "app_key": app_key, "where": f"{town}, Colorado",
                    "distance": 8, "results_per_page": 50, "max_days_old": 30,
                    "sort_by": "date", "content-type": "application/json",
                },
                timeout=30,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            for d in results:
                job = adzuna_to_job(d)
                if job:
                    jobs.append(job)
            if len(results) < 50:
                break
    return jobs


def adzuna_to_job(d: dict) -> dict | None:
    title = clean(d.get("title"), 120)
    company = clean((d.get("company") or {}).get("display_name"), 80)
    loc = d.get("location") or {}
    town = find_town(loc.get("display_name", ""), " ".join(loc.get("area") or []))
    if not (title and company and town) or is_staffing(company):
        return None
    desc = clean(d.get("description"), 600)
    if str(d.get("salary_is_predicted")) == "1":
        pay, pay_sort = pay_from_text(desc)
    else:
        pay, pay_sort = fmt_pay(d.get("salary_min"), d.get("salary_max"))
        if not pay:
            pay, pay_sort = pay_from_text(desc)
    posted = (d.get("created") or "")[:10] or None
    return {
        "id": make_id(title, company, town),
        "title": title, "company": company, "town": town,
        "type": job_type(d.get("contract_time") or "", d.get("contract_type") or "", title),
        "category": pick_category(title, desc),
        "pay": pay, "pay_sort": pay_sort,
        "posted": posted, "description": desc,
        "apply_url": d.get("redirect_url") or "", "via": "Adzuna",
        "source": "Adzuna",
    }


# ---------------------------------------------------------------- SerpApi
class SkipSource(Exception):
    pass


def collect_serpapi(state: dict, force: bool) -> list[dict]:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise SkipSource("no SERPAPI_KEY secret yet")
    today = now()
    if not force and today.weekday() not in SERPAPI_DAYS:
        raise SkipSource("only runs Mondays and Thursdays (free plan)")
    month = today.strftime("%Y-%m")
    if state.get("month") != month:
        state.update({"month": month, "used": 0})
    s = http()

    left = SERPAPI_BUDGET - state["used"]
    try:  # account check is free and doesn't use a search
        acct = s.get("https://serpapi.com/account.json", params={"api_key": key}, timeout=20).json()
        real_left = acct.get("total_searches_left", acct.get("plan_searches_left"))
        if isinstance(real_left, int):
            left = min(left, real_left - 5)
    except Exception:
        pass
    if left <= 0:
        raise SkipSource(f"monthly budget used ({state['used']} searches in {month})")

    jobs = []
    for q, town in SERPAPI_SEARCHES[: max(0, left)]:
        r = s.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_jobs", "q": f"{q} {town} CO",
                "location": f"{town}, Colorado, United States",
                "hl": "en", "gl": "us", "chips": "date_posted:week", "api_key": key,
            },
            timeout=60,
        )
        state["used"] += 1
        if r.status_code == 429:
            break
        r.raise_for_status()
        for d in r.json().get("jobs_results", []):
            job = serp_to_job(d)
            if job:
                jobs.append(job)
    return jobs


def serp_to_job(d: dict) -> dict | None:
    title = clean(d.get("title"), 120)
    company = clean(d.get("company_name"), 80)
    town = find_town(d.get("location", ""))
    if not (title and company and town) or is_staffing(company):
        return None
    ext = d.get("detected_extensions") or {}
    desc = clean(d.get("description"), 600)
    pay, pay_sort = pay_from_text(ext.get("salary", "")) if ext.get("salary") else ("", 0)
    if not pay:
        pay, pay_sort = pay_from_text(d.get("description", ""))
    options = d.get("apply_options") or []
    # Prefer the employer's own site over Indeed and friends.
    direct = [o for o in options if o.get("link") and not is_aggregator(o.get("link")) and not is_aggregator(o.get("title"))]
    best = (direct or options or [{}])[0]
    url = best.get("link") or d.get("share_link") or ""
    via = clean(best.get("title") or d.get("via") or "", 40).replace("via ", "")
    return {
        "id": make_id(title, company, town),
        "title": title, "company": company, "town": town,
        "type": job_type(ext.get("schedule_type", ""), " ".join(d.get("extensions") or []), title),
        "category": pick_category(title, desc),
        "pay": pay, "pay_sort": pay_sort,
        "posted": posted_from_relative(ext.get("posted_at", "")),
        "description": desc,
        "apply_url": url, "via": via or "Google Jobs",
        "direct": bool(direct),
        "source": "Google Jobs",
    }


# ---------------------------------------------------------------- merge
def richness(j: dict) -> int:
    return (3 if j.get("direct") else 0) + (2 if j.get("pay") else 0) + (1 if j.get("type") else 0) + len(j.get("description", "")) // 200


def main() -> int:
    force_serp = "--serpapi" in sys.argv or os.environ.get("FORCE_SERPAPI") == "true"
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except Exception:
            old = {}
    serp_state = old.get("serpapi_usage", {})
    stamp = now()
    today = stamp.date().isoformat()

    by_source: dict[str, list[dict]] = {}
    status: dict[str, dict] = {}
    for name, fn in (("Adzuna", collect_adzuna), ("Google Jobs", lambda: collect_serpapi(serp_state, force_serp))):
        try:
            got = fn()
            for j in got:
                j["last_seen"] = today
            by_source[name] = got
            status[name] = {"ok": True, "count": len(got), "ran": today}
            print(f"{name}: {len(got)} jobs")
        except SkipSource as e:
            prev = (old.get("sources") or {}).get(name, {})
            status[name] = {**prev, "skipped": str(e)}
            print(f"{name}: skipped ({e})")
        except Exception as e:
            traceback.print_exc()
            prev = (old.get("sources") or {}).get(name, {})
            status[name] = {**prev, "ok": False, "error": str(e)[:200], "failed": today}

    # Start from last run's jobs, then lay this run's on top.
    merged: dict[str, dict] = {}
    for j in old.get("jobs", []):
        merged[j["id"]] = j
    for src_jobs in by_source.values():
        for j in src_jobs:
            prev = merged.get(j["id"])
            if prev:
                j["first_seen"] = prev.get("first_seen", today)
                j["posted"] = min(filter(None, [j.get("posted"), prev.get("posted")]), default=None)
                if richness(prev) > richness(j):
                    prev["last_seen"] = today
                    continue
            else:
                j["first_seen"] = today
            merged[j["id"]] = j

    # Age out.
    keep = []
    cutoff_posted = (stamp - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
    for j in merged.values():
        days = KEEP_DAYS.get(j.get("source"), 7)
        ok_seen = j.get("last_seen", "") >= (stamp - timedelta(days=days)).date().isoformat()
        ok_age = (j.get("posted") or j.get("first_seen") or today) >= cutoff_posted
        if ok_seen and ok_age:
            j["apply_url"] = with_utm(j.get("apply_url", "")) if j.get("direct") else j.get("apply_url", "")
            keep.append(j)
    keep.sort(key=lambda j: (j.get("posted") or j.get("first_seen") or "", j["title"]), reverse=True)

    out = {
        "updated": stamp.isoformat(timespec="minutes"),
        "sources": status,
        "serpapi_usage": serp_state,
        "towns": sorted({j["town"] for j in keep}, key=lambda t: TOWNS.index(t) if t in TOWNS else 99),
        "categories": [c for c, _ in CATEGORIES if any(j["category"] == c for j in keep)] + (["Other"] if any(j["category"] == "Other" for j in keep) else []),
        "jobs": keep,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f"Wrote {len(keep)} jobs to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
