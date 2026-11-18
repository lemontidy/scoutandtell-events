# Turning on event submissions (one time, about 5 minutes)

1. Go to **script.google.com** while signed in to the Google account that should get the review emails. Click **New project**.
2. Delete the sample code, paste in everything from `Code.gs` (in this folder), and click the **Save** icon. Name the project "Scout & Tell Events".
3. In the function dropdown at the top, choose **setup**, then click **Run**. Google will ask for permission: click **Review permissions**, pick your account, then **Advanced → Go to Scout & Tell Events (unsafe) → Allow**. This is normal for your own scripts. It creates a Google Sheet called *Scout & Tell Event Submissions* in your Drive.
4. Click **Deploy → New deployment**. Click the gear next to "Select type" and choose **Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
5. Click **Deploy** and copy the **Web app URL** (it ends in `/exec`). Send that URL to Claude, which puts it in `docs/config.json`.

That's it. From then on:
- Each submission lands in the sheet and emails you **Approve** / **Deny** buttons.
- Approved events show up on scoutandtell.com/events within about 5 minutes.
- You can also change the `status` column in the sheet by hand (`approved` / `denied`).

**If you edit Code.gs later:** use Deploy → Manage deployments → pencil icon → Version: *New version* → Deploy. That keeps the same URL.
