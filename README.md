# Scout & Tell events calendar

The calendar at **scoutandtell.com/events**.

## How it works

| Piece | Where | What it does |
|---|---|---|
| Collector | `scripts/collect_events.py` | Every night, pulls the next 90 days of events from Visit Fort Collins, Visit Greeley and Visit Estes Park (Visit Loveland is turned off because its calendar host blocks GitHub), then writes `docs/events.json`. |
| Nightly job | `.github/workflows/update-events.yml` | Runs the collector at about 4am Mountain on GitHub's servers and saves the result. |
| Calendar page | `docs/` | The calendar itself (list, week and month views, filters, event details, add to calendar, submit form). Hosted free by GitHub Pages. |
| Submissions | `apps-script/` | Google Apps Script: saves reader submissions to a Google Sheet and emails approve/deny buttons. Approved events appear on the calendar right away. |
| Beehiiv page | scoutandtell.com/events | An HTML block that shows the GitHub Pages calendar inside the Scout & Tell site. |

## Links people click

- **Visit Fort Collins, Greeley, Estes Park:** the organizer's own website (ticket or venue page) when the listing has one, otherwise the Visit [city] listing.
- **Reader submissions:** the link the submitter entered.

## Everyday tasks

- **Refresh events now:** GitHub → Actions → *Update events* → **Run workflow**.
- **See whether a source failed:** open `docs/events.json` and look at `"sources"` near the top. A source that fails keeps the previous night's events, so the calendar never goes blank.
- **Change how far ahead it looks:** `DAYS_AHEAD` in `scripts/collect_events.py`.
- **Change categories:** `CATEGORIES` in the same file. Each category has a list of matching keywords.
- **Change colors or fonts:** the top of `docs/calendar.css`.

---

# Scout & Tell job board

The job board at **lemontidy.github.io/scoutandtell-events/jobs/** (to be shown at scoutandtell.com/jobs).

| Piece | Where | What it does |
|---|---|---|
| Collector | `scripts/collect_jobs.py` | Pulls Northern Colorado openings, drops recruiters/staffing agencies and anything outside NoCo, removes duplicates, and writes `docs/jobs/jobs.json`. |
| Daily job | `.github/workflows/update-jobs.yml` | Runs every morning on GitHub's servers. Adzuna runs Sundays only; Google Jobs (SerpApi) only Mondays and Thursdays. Both stay inside their free plans. |
| Board page | `docs/jobs/` | Search (job/employer + town), Spotlight, Featured, the full list with filters, browse boxes, and the employer tiers. |
| Paid placements | `docs/jobs/sponsored.json` | Spotlight (max 2), Featured and Gold-row employers. Each entry hides itself after its `ends` date. |

## Keys (one-time setup)

GitHub → this repo → **Settings → Secrets and variables → Actions → New repository secret**. Add three:

| Name | Where to find it |
|---|---|
| `ADZUNA_APP_ID` | developer.adzuna.com → Dashboard → API Access Details |
| `ADZUNA_APP_KEY` | same page |
| `SERPAPI_KEY` | serpapi.com → Dashboard → "Your Private API Key" |

A missing key just skips that source.

## Free plans

**Adzuna:** 25 calls a month. The collector makes 5 calls (up to 250 jobs) once a week on Sundays, about 22 a month, and stops at 24.

**SerpApi:**
The free plan is 250 searches a month. The collector does 22 searches per run, only on Mondays and Thursdays (~200 a month), checks SerpApi's own count before running, and stops at 230 so it can never go over. To change the searches, edit `SERPAPI_SEARCHES`; to change the cap, `SERPAPI_BUDGET`.

## Everyday tasks

- **Refresh jobs now:** Actions → *Update jobs* → **Run workflow**. Tick the boxes to include Google Jobs (~22 of 250 searches) and/or Adzuna (5 of 25 calls).
- **See whether a source failed or how many SerpApi searches are used this month:** open `docs/jobs/jobs.json` and look at `"sources"`, `"serpapi_usage"` and `"adzuna_usage"` at the top.
- **Hide an employer:** add its name to `HIDE_COMPANIES` in the collector. Recruiter keywords are in `STAFFING`.
- **Sell a placement:** add an entry to `docs/jobs/sponsored.json` (an example is in the file) and commit. It shows up within a minute or two.
- **Link to a filtered view** (great for the newsletter): `…/jobs/?where=Loveland`, `?type=Part time`, `?cat=Healthcare`, `?q=barista`.
