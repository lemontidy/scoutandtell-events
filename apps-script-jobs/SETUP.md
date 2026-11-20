# Turning on job board stats + "Post a job" (one time, about 5 minutes)

Same steps as the events submissions you already set up.

1. Go to **script.google.com** (signed in to the account that should get the emails). Click **New project**.
2. Delete the sample code, paste in everything from `Code.gs` (in this folder), and **Save**. Name the project "Scout & Tell Jobs".
3. In the function dropdown choose **setup**, then **Run**. Approve the permissions (Review permissions → your account → Advanced → Go to Scout & Tell Jobs → Allow). This creates a Google Sheet called *Scout & Tell Job Board Stats* in your Drive.
4. **Deploy → New deployment** → gear → **Web app**. Execute as: **Me**. Who has access: **Anyone**. Click **Deploy**.
5. Copy the **Web app URL** (ends in `/exec`) and send it to Claude. It goes in `docs/jobs/config.json`.

From then on:
- **Events tab:** every page view, search, job click, Apply click, sponsored view and click, and "Post a job" open.
- **Daily Summary tab:** rebuilt every night at 2am. One row per day with unique visitors, page views, job clicks, Apply clicks, sponsored impressions/clicks, jobs submitted and approved. This is the tab to show sponsors.
- **Job Submissions tab:** every job posted through the form. You get an email with Approve / Deny buttons; approved jobs show on the board within about 5 minutes and stay up 30 days.

No visitor names, emails or IP addresses are stored.

**If you edit Code.gs later:** Deploy → Manage deployments → pencil → Version: *New version* → Deploy (keeps the same URL).
