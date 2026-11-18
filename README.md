# Scout & Tell events calendar

The calendar at **scoutandtell.com/events**.

## How it works

| Piece | Where | What it does |
|---|---|---|
| Collector | `scripts/collect_events.py` | Every night, pulls the next 90 days of events from Visit Fort Collins, Visit Loveland, Visit Greeley and Visit Estes Park, then writes `docs/events.json`. |
| Nightly job | `.github/workflows/update-events.yml` | Runs the collector at about 4am Mountain on GitHub's servers and saves the result. |
| Calendar page | `docs/` | The calendar itself (list, week and month views, filters, event details, add to calendar, submit form). Hosted free by GitHub Pages. |
| Submissions | `apps-script/` | Google Apps Script: saves reader submissions to a Google Sheet and emails approve/deny buttons. Approved events appear on the calendar right away. |
| Beehiiv page | scoutandtell.com/events | An HTML block that shows the GitHub Pages calendar inside the Scout & Tell site. |

## Links people click

- **Visit Fort Collins, Greeley, Estes Park:** the organizer's own website (ticket or venue page) when the listing has one, otherwise the Visit [city] listing.
- **Visit Loveland:** the event's public Yodel page, the same one Visit Loveland uses.
- **Reader submissions:** the link the submitter entered.

## Everyday tasks

- **Refresh events now:** GitHub → Actions → *Update events* → **Run workflow**.
- **See whether a source failed:** open `docs/events.json` and look at `"sources"` near the top. A source that fails keeps the previous night's events, so the calendar never goes blank.
- **Change how far ahead it looks:** `DAYS_AHEAD` in `scripts/collect_events.py`.
- **Change categories:** `CATEGORIES` in the same file. Each category has a list of matching keywords.
- **Change colors or fonts:** the top of `docs/calendar.css`.
