"""One-off: try each hiring system's job feed and save samples."""
import json, re, os
import requests
os.makedirs("probe/samples", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "application/json, text/html;q=0.9,*/*;q=0.8"}
s = requests.Session(); s.headers.update(UA)
out = {}
def save(name, text): open(f"probe/samples/{name}", "w").write(text[:200000])
def rec(k, **kw): out[k] = kw; print(k, {a: (b if not isinstance(b, str) else b[:150]) for a, b in kw.items()}, flush=True)

WD = {
 "csu": "https://csusystem.wd12.myworkdayjobs.com/fortcollins_careers",
 "aims": "https://aims.wd1.myworkdayjobs.com/Jobs",
 "banner": "https://bannerhealth.wd108.myworkdayjobs.com/Careers",
 "woodward": "https://woodward.wd5.myworkdayjobs.com/woodward",
 "newbelgium": "https://newbelgium.wd108.myworkdayjobs.com/NBBCareers",
 "waterpik": "https://churchdwight.wd1.myworkdayjobs.com/waterpikcareers",
 "hach": "https://veralto.wd1.myworkdayjobs.com/HachJobs",
 "hpe": "https://hpe.wd5.myworkdayjobs.com/Jobsathpe",
 "uchealth_guess1": "https://uchealth.wd1.myworkdayjobs.com/uchealth",
}
for k, base in WD.items():
    host = base.split("/")[2]; tenant = host.split(".")[0]; site = base.rstrip("/").split("/")[-1]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    for q in ("", "Fort Collins", "Colorado"):
        try:
            r = s.post(api, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q}, timeout=30)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            rec(f"wd:{k}:{q or 'all'}", status=r.status_code, total=j.get("total"), sample=[(p.get("title"), p.get("locationsText"), p.get("postedOn")) for p in j.get("jobPostings", [])[:4]])
            if q == "Colorado" and j.get("jobPostings"):
                save(f"wd_{k}.json", r.text)
                ep = j["jobPostings"][0]["externalPath"]
                d = s.get(f"https://{host}/wday/cxs/{tenant}/{site}{ep}", timeout=30)
                save(f"wd_{k}_detail.json", d.text)
        except Exception as e:
            rec(f"wd:{k}:{q or 'all'}", error=str(e)[:150])

# SmartRecruiters (official public API)
try:
    r = s.get("https://api.smartrecruiters.com/v1/companies/SaludFamilyHealthCenters/postings?limit=100", timeout=30)
    j = r.json(); save("sr_salud.json", r.text)
    rec("sr:salud", status=r.status_code, total=j.get("totalFound"), sample=[(p["name"], p.get("location", {}).get("city")) for p in j.get("content", [])[:5]])
except Exception as e: rec("sr:salud", error=str(e))

# ADP Workforce Now
for k, cid in {"summitstone": "efc2917c-9851-47b5-9929-8d0a710b4ca2", "odell": "d30b7861-ea36-4a20-9426-8f090e74d18a", "sunrise": "a70b4e51-0f48-41f7-bde6-f9a90b335781"}.items():
    try:
        r = s.get(f"https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?cid={cid}&timeStamp=1&lang=en_US&ccId=19000101_000001&locale=en_US&$top=100", timeout=30)
        save(f"adp_{k}.json", r.text)
        j = r.json() if r.ok else {}
        rec(f"adp:{k}", status=r.status_code, n=len(j.get("jobRequisitions", [])), sample=[(x.get("requisitionTitle"), [l.get("address", {}).get("cityName") for l in x.get("requisitionLocations", [])]) for x in j.get("jobRequisitions", [])[:4]])
    except Exception as e: rec(f"adp:{k}", error=str(e)[:150])

# NEOGOV: try agencies and a few feed URLs
for agency in ("estespark", "larimer", "larimercounty", "weld", "weldcounty", "windsorco", "windsor", "loveland", "lovelandco", "greeley", "greeleyco", "johnstown", "poudrefire", "pfa", "colorado"):
    for url in (f"https://www.governmentjobs.com/careers/{agency}", f"https://www.governmentjobs.com/SearchEngine/JobsFeed?agency={agency}"):
        try:
            r = s.get(url, timeout=30, allow_redirects=True)
            n = len(re.findall(r'class="item-details-link"|/careers/[\w]+/jobs/\d+', r.text))
            rec(f"neogov:{agency}:{url.split('/')[3]}", status=r.status_code, final=r.url, links=n, title=re.search(r"<title>(.*?)</title>", r.text, re.S).group(1).strip()[:80] if "<title>" in r.text else "")
            if n and agency == "estespark": save(f"neogov_{agency}_{url.split('/')[3]}.html", r.text)
        except Exception as e: rec(f"neogov:{agency}", error=str(e)[:150])
for url in ("https://www.governmentjobs.com/careers/home/index?agency=estespark&sort=PositionTitle&isDescendingSort=false&_=1",):
    try:
        r = s.get(url, timeout=30, headers={"X-Requested-With": "XMLHttpRequest"}); save("neogov_ajax.html", r.text)
        rec("neogov:ajax", status=r.status_code, n=len(re.findall(r"/jobs/\d+", r.text)))
    except Exception as e: rec("neogov:ajax", error=str(e))

# AppliTrack (Greeley D6)
for url in ("https://www.applitrack.com/greeley/onlineapp/jobpostings/rss.asp", "https://www.applitrack.com/greeley/onlineapp/jobpostings/Output.asp?all=1", "https://www.applitrack.com/greeley/onlineapp/default.aspx?all=1"):
    try:
        r = s.get(url, timeout=30); name = "applitrack_" + url.split("/")[-1].split("?")[0]; save(name, r.text)
        rec("applitrack:" + url.split("/")[-1], status=r.status_code, items=len(re.findall(r"<item>", r.text)), postings=len(re.findall(r"AppliTrackPostingID|JobID", r.text)))
    except Exception as e: rec("applitrack", error=str(e))

# SchoolSpring (PSD) + Thompson guess
for url in ("https://psdschools.schoolspring.com/", "https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch?domainName=psdschools.schoolspring.com&keyword=&location=&category=&gradelevel=&jobtype=&organization=&swLat=&swLon=&neLat=&neLon=&page=1&size=50&sortDateAscending=false", "https://thompson.schoolspring.com/", "https://tsd.schoolspring.com/"):
    try:
        r = s.get(url, timeout=30); save("ss_" + url.split("/")[2].split(".")[0] + ("_api" if "api." in url else "") + ".txt", r.text)
        rec("schoolspring:" + url[:70], status=r.status_code, size=len(r.text), head=r.text[:150])
    except Exception as e: rec("schoolspring", error=str(e))

# Cornerstone (Fort Collins, UNC): grab page and look for token
for k, url in {"fortcollins": "https://fcgov.csod.com/ux/ats/careersite/12/home?c=fcgov", "unco": "https://unco.csod.com/ux/ats/careersite/1/home?c=unco"}.items():
    try:
        r = s.get(url, timeout=30); save(f"csod_{k}.html", r.text)
        tok = re.search(r'"token"\s*:\s*"([^"]+)"', r.text)
        rec(f"csod:{k}", status=r.status_code, token=bool(tok))
        if tok:
            host = url.split("/")[2]; corp = url.split("c=")[1]; site = re.search(r"careersite/(\d+)", url).group(1)
            api = re.search(r'"cloudEndpoint"\s*:\s*"([^"]+)"', r.text)
            base = (api.group(1) if api else "https://us.api.csod.com/").rstrip("/")
            body = {"careerSiteId": int(site), "careerSitePageId": int(site), "pageNumber": 1, "pageSize": 25, "cultureId": 1, "searchText": "", "cultureName": "en-US", "states": [], "countryCodes": [], "cities": [], "placeID": "", "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [], "customFieldDropdowns": [], "customFieldRadios": []}
            j = s.post(base + "/rec-job-search/external/jobs", json=body, headers={"Authorization": "Bearer " + tok.group(1), "csod-accept-language": "en-US"}, timeout=30)
            save(f"csod_{k}_jobs.json", j.text)
            jj = j.json() if j.ok else {}
            rec(f"csod:{k}:jobs", status=j.status_code, total=(jj.get("data") or {}).get("totalCount"), sample=[(x.get("title"), x.get("locations")) for x in (jj.get("data") or {}).get("requisitions", [])[:3]])
    except Exception as e: rec(f"csod:{k}", error=str(e)[:150])

# iCIMS (OtterBox)
try:
    r = s.get("https://careers-otterproducts.icims.com/jobs/search?ss=1&in_iframe=1&pr=0", timeout=30); save("icims_otter.html", r.text)
    rec("icims:otter", status=r.status_code, links=len(set(re.findall(r"/jobs/(\d+)/[\w-]+/job", r.text))))
except Exception as e: rec("icims:otter", error=str(e))

# Town sites (plain HTML job pages)
for k, url in {"wellington": "https://www.wellingtoncolorado.gov/jobs.aspx", "timnath": "https://timnath.org/job-openings/", "berthoud": "https://www.berthoud.org/187/Employment-Opportunities", "prpa": "https://prpa.org/careers/", "library": "https://poudrelibraries.org/careers/", "frcc": "https://www.frontrange.edu/careers/index.html", "canvas": "https://www.canvas.org/careers", "bankofco": "https://www.bankofcolorado.com/careers/jobs"}.items():
    try:
        r = s.get(url, timeout=30); save(f"page_{k}.html", r.text)
        f = {}
        for pat in ("myworkdayjobs", "paylocity", "paycom", "ultipro", "applytojob", "bamboohr", "isolvedhire", "governmentjobs", "applicantpro", "hiringthing", "workforcenow", "icims", "dayforce", "ukg", "jobvite", "csod", "neogov", "schoolspring", "applitrack", "taleo", "oraclecloud", "careerplug", "indeed.com", "adp.com"):
            if pat in r.text: f[pat] = re.findall(r"https?://[^\"'\s<>]*" + re.escape(pat) + r"[^\"'\s<>]*", r.text)[:2]
        rec(f"page:{k}", status=r.status_code, found=f)
    except Exception as e: rec(f"page:{k}", error=str(e)[:120])

json.dump(out, open("probe/report2.json", "w"), indent=1)
