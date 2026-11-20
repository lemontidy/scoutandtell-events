"""
Direct feeds from Northern Colorado employers' own hiring systems.

Every feed here is free and has no monthly limit, so these run every night.
Each employer is tried separately: one site being down never stops the rest.

To add an employer, add a line to the matching list below. To find which
system an employer uses, open its careers page and look at the address of
the job list (myworkdayjobs.com = Workday, csod.com = Cornerstone, etc.).
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime

import requests

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# name, host, tenant, site, search words ("" = everything), town if the whole site is one town
WORKDAY = [
    ("Colorado State University", "csusystem.wd12.myworkdayjobs.com", "csusystem", "fortcollins_careers", [""], "Fort Collins"),
    ("Aims Community College", "aims.wd1.myworkdayjobs.com", "aims", "Jobs", [""], None),
    ("Banner Health", "bannerhealth.wd108.myworkdayjobs.com", "bannerhealth", "Careers", ["Loveland", "Greeley", "Fort Collins", "Windsor"], None),
    ("Woodward", "woodward.wd5.myworkdayjobs.com", "woodward", "woodward", ["Fort Collins", "Loveland", "Windsor"], None),
    ("New Belgium Brewing", "newbelgium.wd108.myworkdayjobs.com", "newbelgium", "NBBCareers", [""], None),
    ("Water Pik", "churchdwight.wd1.myworkdayjobs.com", "churchdwight", "waterpikcareers", [""], None),
    ("Hach", "veralto.wd1.myworkdayjobs.com", "veralto", "HachJobs", ["Loveland"], None),
    ("Hewlett Packard Enterprise", "hpe.wd5.myworkdayjobs.com", "hpe", "Jobsathpe", ["Fort Collins"], None),
]

# name, host, corp code, career site id
CORNERSTONE = [
    ("City of Fort Collins", "fcgov.csod.com", "fcgov", 12),
    ("University of Northern Colorado", "unco.csod.com", "unco", 1),
]

# name, ADP client id
ADP = [
    ("SummitStone Health Partners", "efc2917c-9851-47b5-9929-8d0a710b4ca2"),
    ("Odell Brewing", "d30b7861-ea36-4a20-9426-8f090e74d18a"),
    ("Sunrise Community Health", "a70b4e51-0f48-41f7-bde6-f9a90b335781"),
]

# name, SmartRecruiters company id
SMARTRECRUITERS = [
    ("Salud Family Health", "SaludFamilyHealthCenters"),
]

# name, SchoolSpring site, town
SCHOOLSPRING = [
    ("Poudre School District", "psdschools.schoolspring.com", "Fort Collins"),
]

# name, AppliTrack district code, town
APPLITRACK = [
    ("Greeley-Evans School District 6", "greeley", "Greeley"),
]

PUBLIC = {"Colorado State University", "Aims Community College", "City of Fort Collins",
          "University of Northern Colorado", "Poudre School District", "Greeley-Evans School District 6"}


def _clean(s, limit=600):
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return s


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                      "Accept-Language": "en-US,en;q=0.9"})
    return s


def _get(s, url, tries=3, **kw):
    for i in range(tries):
        r = s.get(url, timeout=40, **kw)
        if r.status_code != 429:
            return r
        time.sleep(8 * (i + 1))
    return r


def _post(s, url, tries=4, **kw):
    for i in range(tries):
        r = s.post(url, timeout=40, **kw)
        if r.status_code != 429:
            return r
        time.sleep(8 * (i + 1))
    return r


def _mdy(s):
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date().isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------- Workday
def workday(c, old: dict, log) -> list[dict]:
    out = []
    for name, host, tenant, site, searches, fixed_town in WORKDAY:
        try:
            s = _session()
            base = f"https://{host}/{site}"
            _get(s, base)  # picks up the cookies Workday expects
            s.headers.update({"Content-Type": "application/json", "Origin": f"https://{host}", "Referer": base})
            api = f"https://{host}/wday/cxs/{tenant}/{site}"
            seen, n = set(), 0
            for q in searches:
                for page in range(20):
                    r = _post(s, api + "/jobs", json={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": q})
                    r.raise_for_status()
                    posts = r.json().get("jobPostings", [])
                    for p in posts:
                        ep = p.get("externalPath")
                        if not ep or ep in seen:
                            continue
                        seen.add(ep)
                        title = _clean(p.get("title"), 120)
                        town = fixed_town or c.find_town(p.get("locationsText", ""))
                        if not town and "location" not in (p.get("locationsText") or "").lower():
                            continue  # one location, and it isn't in NoCo
                        jid = c.make_id(title, name, town or "?")
                        prev = old.get(jid)
                        if prev and prev.get("description") and town:
                            job = dict(prev)
                        else:
                            time.sleep(0.6)
                            d = _get(s, api + ep)
                            if not d.ok:
                                continue
                            info = d.json().get("jobPostingInfo", {})
                            locs = " | ".join([info.get("location", "")] + list(info.get("additionalLocations") or []))
                            town = fixed_town or c.find_town(locs)
                            if not town:
                                continue
                            desc_html = info.get("jobDescription", "")
                            pay, pay_sort = c.pay_from_text(_clean(desc_html, 0))
                            job = {
                                "title": title, "company": name, "town": town,
                                "type": c.job_type(info.get("timeType", ""), title),
                                "category": c.pick_category(title, _clean(desc_html, 800)),
                                "pay": pay, "pay_sort": pay_sort,
                                "posted": info.get("startDate") or c.posted_from_relative(p.get("postedOn", "")),
                                "description": _clean(desc_html),
                                "apply_url": info.get("externalUrl") or f"https://{host}/{site}{ep}",
                            }
                        job.update({"id": c.make_id(title, name, town), "via": name, "direct": True, "source": "Employer sites"})
                        out.append(job)
                        n += 1
                    if len(posts) < 20:
                        break
                    time.sleep(1)
            log(f"  Workday · {name}: {n}")
        except Exception as e:
            log(f"  Workday · {name}: FAILED {e}")
    return out


# ---------------------------------------------------------------- Cornerstone
def cornerstone(c, old, log) -> list[dict]:
    out = []
    for name, host, corp, site in CORNERSTONE:
        try:
            s = _session()
            page = _get(s, f"https://{host}/ux/ats/careersite/{site}/home?c={corp}").text
            tok = re.search(r'"token"\s*:\s*"([^"]+)"', page).group(1)
            ep = re.search(r'"cloudEndpoint"\s*:\s*"([^"]+)"', page)
            api = (ep.group(1) if ep else "https://us.api.csod.com/").rstrip("/") + "/rec-job-search/external/jobs"
            hdr = {"Authorization": "Bearer " + tok, "csod-accept-language": "en-US", "Content-Type": "application/json"}
            n = 0
            for pg in range(1, 20):
                body = {"careerSiteId": site, "careerSitePageId": site, "pageNumber": pg, "pageSize": 25, "cultureId": 1,
                        "searchText": "", "cultureName": "en-US", "states": [], "countryCodes": [], "cities": [],
                        "placeID": "", "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [],
                        "customFieldDropdowns": [], "customFieldRadios": []}
                r = _post(s, api, json=body, headers=hdr)
                r.raise_for_status()
                reqs = (r.json().get("data") or {}).get("requisitions", [])
                for q in reqs:
                    title = _clean(q.get("displayJobTitle"), 120)
                    locs = " | ".join(f"{l.get('city', '')}" for l in q.get("locations") or [])
                    town = c.find_town(locs)
                    if not (title and town):
                        continue
                    desc = _clean(q.get("externalDescription"), 0)
                    pay, pay_sort = c.pay_from_text(desc)
                    out.append({
                        "id": c.make_id(title, name, town), "title": title, "company": name, "town": town,
                        "type": c.job_type(title, desc[:600]), "category": c.pick_category(title, desc),
                        "pay": pay, "pay_sort": pay_sort, "posted": _mdy(q.get("postingEffectiveDate", "")),
                        "description": _clean(desc), "via": name, "direct": True, "source": "Employer sites",
                        "apply_url": f"https://{host}/ux/ats/careersite/{site}/home/requisition/{q.get('requisitionId')}?c={corp}",
                    })
                    n += 1
                if len(reqs) < 25:
                    break
            log(f"  Cornerstone · {name}: {n}")
        except Exception as e:
            log(f"  Cornerstone · {name}: FAILED {e}")
    return out


# ---------------------------------------------------------------- ADP
def adp(c, old, log) -> list[dict]:
    out = []
    for name, cid in ADP:
        try:
            s, n = _session(), 0
            for skip in range(0, 400, 20):
                url = (f"https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
                       f"?cid={cid}&timeStamp={int(time.time() * 1000)}&lang=en_US&ccId=19000101_000001&locale=en_US&$top=20&$skip={skip}")
                r = _get(s, url)
                r.raise_for_status()
                reqs = r.json().get("jobRequisitions", [])
                for q in reqs:
                    title = _clean(q.get("requisitionTitle"), 120)
                    locs = " | ".join((l.get("address") or {}).get("cityName", "") + " " + (l.get("nameCode") or {}).get("shortName", "")
                                      for l in q.get("requisitionLocations") or [])
                    town = c.find_town(locs)
                    if not (title and town):
                        continue
                    rng = q.get("payGradeRange") or {}
                    lo = (rng.get("minimumRate") or {}).get("amountValue")
                    hi = (rng.get("maximumRate") or {}).get("amountValue")
                    pay, pay_sort = c.fmt_pay(lo, hi) if (lo or hi) else ("", 0)
                    ext = next((f.get("stringValue") for f in (q.get("customFieldGroup") or {}).get("stringFields", [])
                                if (f.get("nameCode") or {}).get("codeValue") == "ExternalJobID"), None)
                    level = (q.get("workLevelCode") or {}).get("shortName", "")
                    out.append({
                        "id": c.make_id(title, name, town), "title": title, "company": name, "town": town,
                        "type": c.job_type(level, title), "category": c.pick_category(title),
                        "pay": pay, "pay_sort": pay_sort, "posted": (q.get("postDate") or "")[:10] or None,
                        "description": "", "via": name, "direct": True, "source": "Employer sites",
                        "apply_url": (f"https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
                                      f"?cid={cid}&ccId=19000101_000001&lang=en_US" + (f"&jobId={ext}" if ext else "")),
                    })
                    n += 1
                if len(reqs) < 20:
                    break
            log(f"  ADP · {name}: {n}")
        except Exception as e:
            log(f"  ADP · {name}: FAILED {e}")
    return out


# ---------------------------------------------------------------- SmartRecruiters
def smartrecruiters(c, old, log) -> list[dict]:
    out = []
    for name, company in SMARTRECRUITERS:
        try:
            s, n = _session(), 0
            for offset in range(0, 1000, 100):
                r = _get(s, f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset={offset}")
                r.raise_for_status()
                content = r.json().get("content", [])
                for p in content:
                    title = _clean(p.get("name"), 120)
                    town = c.find_town((p.get("location") or {}).get("city", ""))
                    if not (title and town):
                        continue
                    out.append({
                        "id": c.make_id(title, name, town), "title": title, "company": name, "town": town,
                        "type": c.job_type((p.get("typeOfEmployment") or {}).get("label", ""), title),
                        "category": c.pick_category(title), "pay": "", "pay_sort": 0,
                        "posted": (p.get("releasedDate") or "")[:10] or None, "description": "",
                        "via": name, "direct": True, "source": "Employer sites",
                        "apply_url": f"https://jobs.smartrecruiters.com/{company}/{p.get('id')}",
                    })
                    n += 1
                if len(content) < 100:
                    break
            log(f"  SmartRecruiters · {name}: {n}")
        except Exception as e:
            log(f"  SmartRecruiters · {name}: FAILED {e}")
    return out


# ---------------------------------------------------------------- SchoolSpring
def schoolspring(c, old, log) -> list[dict]:
    out = []
    for name, domain, default_town in SCHOOLSPRING:
        try:
            s, n = _session(), 0
            for page in range(1, 30):
                url = (f"https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch?domainName={domain}&keyword=&location="
                       f"&category=&gradelevel=&jobtype=&organization=&swLat=&swLon=&neLat=&neLon=&page={page}&size=50&sortDateAscending=false")
                r = _get(s, url)
                r.raise_for_status()
                jobs = ((r.json().get("value") or {}).get("jobsList")) or []
                for j in jobs:
                    title = _clean(j.get("title"), 140)
                    town = c.find_town(j.get("location", "")) or default_town
                    out.append({
                        "id": c.make_id(title, name, town), "title": title, "company": name, "town": town,
                        "type": c.job_type(title), "category": c.pick_category(title) if c.pick_category(title) != "Other" else "Education & Childcare",
                        "pay": "", "pay_sort": 0, "posted": (j.get("displayDate") or "")[:10] or None, "description": "",
                        "via": name, "direct": True, "source": "Employer sites",
                        "apply_url": f"https://{domain}/?jobid={j.get('jobId')}",
                    })
                    n += 1
                if len(jobs) < 50:
                    break
            log(f"  SchoolSpring · {name}: {n}")
        except Exception as e:
            log(f"  SchoolSpring · {name}: FAILED {e}")
    return out


# ---------------------------------------------------------------- AppliTrack
_AT_RE = re.compile(
    r"id='wrapword'[^>]*>(?P<title>.*?)</td>.*?JobID:\s*(?P<id>\d+).*?Date Posted:.*?<span class=\"normal\">(?P<date>[\d/]+)</span>"
    r".*?Location:.*?<span class=\"normal\">(?P<loc>.*?)</span>",
    re.S)


def applitrack(c, old, log) -> list[dict]:
    out = []
    for name, code, default_town in APPLITRACK:
        try:
            s = _session()
            r = _get(s, f"https://www.applitrack.com/{code}/onlineapp/jobpostings/Output.asp?all=1")
            r.raise_for_status()
            text = r.text.replace("\\'", "'")
            n = 0
            for m in _AT_RE.finditer(text):
                title = _clean(m.group("title"), 140)
                town = c.find_town(_clean(m.group("loc"))) or default_town
                if not title or "internal only" in title.lower():
                    continue
                out.append({
                    "id": c.make_id(title, name, town), "title": title, "company": name, "town": town,
                    "type": c.job_type(title), "category": c.pick_category(title) if c.pick_category(title) != "Other" else "Education & Childcare",
                    "pay": "", "pay_sort": 0, "posted": _mdy(m.group("date")), "description": "",
                    "via": name, "direct": True, "source": "Employer sites",
                    "apply_url": f"https://www.applitrack.com/{code}/onlineapp/default.aspx?AppliTrackJobId={m.group('id')}",
                })
                n += 1
            log(f"  AppliTrack · {name}: {n}")
        except Exception as e:
            log(f"  AppliTrack · {name}: FAILED {e}")
    return out


def collect_all(c, old: dict, log=print) -> list[dict]:
    jobs = []
    for fn in (workday, cornerstone, adp, smartrecruiters, schoolspring, applitrack):
        jobs += fn(c, old, log)
    for j in jobs:
        if j["category"] == "Other" and j["company"] in PUBLIC:
            j["category"] = "Government & Public Service"
    if not jobs:
        raise RuntimeError("no employer feed returned any jobs")
    return jobs
