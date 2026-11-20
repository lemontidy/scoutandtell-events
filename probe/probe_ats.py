"""One-off: find which hiring system each NoCo employer uses."""
import json, re, sys
from urllib.parse import urljoin, urlparse
import requests

EMPLOYERS = {
 "City of Fort Collins": ["https://www.fcgov.com/jobs", "https://fcgov.csod.com/ux/ats/careersite/12/home?c=fcgov"],
 "Larimer County": ["https://www.larimer.gov/jobs"],
 "City of Loveland": ["https://www.lovelandco.gov/jobs", "https://www.lovelandco.gov"],
 "City of Greeley": ["https://greeleyco.gov/jobs", "https://greeleygov.com/jobs"],
 "Town of Windsor": ["https://www.windsorgov.com/jobs", "https://www.windsorgov.com"],
 "Town of Estes Park": ["https://www.estespark.colorado.gov/jobs", "https://estespark.colorado.gov"],
 "Weld County": ["https://www.weld.gov/Government/Departments/Human-Resources", "https://www.weld.gov"],
 "Town of Wellington": ["https://www.wellingtoncolorado.gov"],
 "Town of Timnath": ["https://timnath.org"],
 "Town of Berthoud": ["https://www.berthoud.org"],
 "Town of Johnstown": ["https://www.townofjohnstown.com"],
 "Colorado State University": ["https://hr.colostate.edu/prospective-employees/", "https://jobs.colostate.edu"],
 "University of Northern Colorado": ["https://www.unco.edu/human-resources/careers/", "https://www.unco.edu/jobs"],
 "Aims Community College": ["https://www.aims.edu/about/employment", "https://www.aims.edu"],
 "Front Range Community College": ["https://www.frontrange.edu/about/employment", "https://www.frontrange.edu"],
 "Poudre School District": ["https://www.psdschools.org/careers"],
 "Thompson School District": ["https://www.tsd.org/careers", "https://www.tsd.org"],
 "Greeley-Evans School District 6": ["https://www.greeleyschools.org/careers", "https://www.greeleyschools.org"],
 "Weld RE-4 School District": ["https://www.weldre4.org"],
 "Poudre Fire Authority": ["https://www.poudre-fire.org/careers", "https://www.poudre-fire.org"],
 "Poudre River Public Library": ["https://www.poudrelibraries.org/about/jobs", "https://www.poudrelibraries.org"],
 "Platte River Power Authority": ["https://www.prpa.org/careers", "https://www.prpa.org"],
 "UCHealth": ["https://www.uchealth.org/careers/", "https://careers.uchealth.org"],
 "Banner Health": ["https://www.bannerhealth.com/careers", "https://jobs.bannerhealth.com"],
 "Columbine Health Systems": ["https://www.columbinehealth.com/careers", "https://www.columbinehealth.com"],
 "SummitStone Health Partners": ["https://summitstonehealth.org/careers", "https://summitstonehealth.org"],
 "Woodward": ["https://www.woodward.com/en/careers", "https://www.woodward.com"],
 "New Belgium Brewing": ["https://www.newbelgium.com/company/careers/", "https://www.newbelgium.com"],
 "Odell Brewing": ["https://www.odellbrewing.com/careers", "https://www.odellbrewing.com"],
 "Broadcom": ["https://www.broadcom.com/company/careers"],
 "JBS USA": ["https://jbssa.com/careers", "https://jbssa.com"],
 "Leprino Foods": ["https://www.leprinofoods.com/careers", "https://www.leprinofoods.com"],
 "Vestas": ["https://www.vestas.com/en/careers"],
 "Advanced Energy": ["https://www.advancedenergy.com/en-us/about/careers/", "https://www.advancedenergy.com"],
 "OtterBox": ["https://www.otterbox.com/en-us/careers.html", "https://careers.otterbox.com"],
 "Water Pik": ["https://www.waterpik.com/careers/", "https://www.waterpik.com"],
 "Hach": ["https://www.hach.com/careers", "https://jobs.danaher.com"],
 "Heska": ["https://www.heska.com/careers", "https://www.heska.com"],
 "Hewlett Packard Enterprise": ["https://careers.hpe.com"],
 "Elevations Credit Union": ["https://www.elevationscu.com/careers", "https://www.elevationscu.com"],
 "Canvas Credit Union": ["https://www.canvas.org/careers", "https://www.canvas.org"],
 "Bank of Colorado": ["https://www.bankofcolorado.com/careers", "https://www.bankofcolorado.com"],
 "Kaiser Permanente": ["https://www.kaiserpermanentejobs.org"],
 "Envision / Front Range Clinic": ["https://www.frontrangeclinic.com/careers"],
 "Sunrise Community Health": ["https://www.sunrisecommunityhealth.org/careers", "https://www.sunrisecommunityhealth.org"],
 "Salud Family Health": ["https://www.saludclinic.org/careers", "https://www.saludclinic.org"],
 "Colorado Department of Transportation": ["https://www.governmentjobs.com/careers/colorado"],
 "Vail Resorts / Estes": [],
}

SIGS = {
 "workday": r"https?://[\w.-]+\.myworkdayjobs\.com/[\w/.-]*",
 "greenhouse": r"https?://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/[\w-]+",
 "lever": r"https?://jobs\.lever\.co/[\w-]+",
 "ashby": r"https?://jobs\.ashbyhq\.com/[\w-]+",
 "smartrecruiters": r"https?://(?:careers|jobs)\.smartrecruiters\.com/[\w-]+",
 "icims": r"https?://[\w.-]+\.icims\.com[\w/.-]*",
 "neogov": r"https?://www\.governmentjobs\.com/careers/[\w-]+",
 "cornerstone": r"https?://[\w.-]+\.csod\.com/[\w/.?=&-]*",
 "applitrack": r"https?://www\.applitrack\.com/[\w-]+/onlineapp[\w/.-]*",
 "tedk12": r"https?://[\w.-]+\.tedk12\.com/hire[\w/.?=&-]*",
 "schoolspring": r"https?://[\w.-]+\.schoolspring\.com[\w/.?=&-]*",
 "ukg": r"https?://recruiting\d?\.ultipro\.com/[\w/.-]*",
 "paycom": r"https?://www\.paycomonline\.net/v4/ats/web\.php/jobs[\w/.?=&-]*",
 "adp": r"https?://workforcenow\.adp\.com/[\w/.?=&%-]*",
 "jobvite": r"https?://jobs\.jobvite\.com/[\w-]+",
 "taleo": r"https?://[\w.-]+\.taleo\.net/[\w/.?=&-]*",
 "oracle": r"https?://[\w.-]+\.oraclecloud\.com/hcmUI/CandidateExperience/[\w/.-]*",
 "successfactors": r"https?://[\w.-]+\.successfactors\.(?:com|eu)/[\w/.?=&-]*|https?://jobs\.sap\.com[\w/.-]*",
 "paylocity": r"https?://recruiting\.paylocity\.com/[\w/.?=&-]*",
 "bamboohr": r"https?://[\w-]+\.bamboohr\.com/careers",
 "jazzhr": r"https?://[\w-]+\.applytojob\.com",
 "breezy": r"https?://[\w-]+\.breezy\.hr",
 "phenom": r"phenompeople|cdn\.phenompeople\.com",
 "radancy": r"tbcdn\.talentbrew\.com|radancy",
 "dayforce": r"https?://jobs\.dayforcehcm\.com/[\w/.-]*",
 "isolved": r"https?://[\w.-]+\.isolvedhire\.com",
 "hiringthing": r"https?://[\w-]+\.hiringthing\.com",
 "applicantpro": r"https?://[\w-]+\.applicantpro\.com",
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

def scan(html):
    out = {}
    for k, rx in SIGS.items():
        m = sorted(set(re.findall(rx, html, re.I)))
        if m: out[k] = m[:5]
    return out

def links(base, html):
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        t = re.sub("<[^>]+>", " ", text).lower()
        if re.search(r"career|jobs|employment|join our team|work (with|for) us|openings", t + " " + href.lower()):
            out.append(urljoin(base, href))
    return list(dict.fromkeys(out))[:8]

report = {}
s = requests.Session(); s.headers.update(UA)
for name, urls in EMPLOYERS.items():
    rec = {"tried": [], "found": {}}
    seen = set()
    queue = list(urls)
    depth = {u: 0 for u in urls}
    while queue and len(seen) < 8:
        u = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            r = s.get(u, timeout=20, allow_redirects=True)
            rec["tried"].append([u, r.status_code, r.url])
            f = scan(r.text + " " + r.url)
            for k, v in f.items(): rec["found"].setdefault(k, []).extend(x for x in v if x not in rec["found"].get(k, []))
            if depth[u] < 1 and r.ok:
                for l in links(r.url, r.text):
                    if l not in depth: depth[l] = depth[u] + 1; queue.append(l)
        except Exception as e:
            rec["tried"].append([u, "ERR", str(e)[:120]])
    report[name] = rec
    print(name, list(rec["found"].keys()), flush=True)
json.dump(report, open("probe/report.json", "w"), indent=1)
