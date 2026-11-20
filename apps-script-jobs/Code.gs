/**
 * Scout & Tell — job board traffic stats + "Post a job" submissions
 *
 * What this does
 *   1. Counts traffic on the job board: page views, unique visitors, searches,
 *      job clicks, Apply clicks, sponsored impressions and clicks, and
 *      "Post a job" form opens. Everything lands in a Google Sheet
 *      ("Scout & Tell Job Board Stats") so it can be reported to sponsors.
 *   2. The "Post a job" form posts here. Each submission is saved to the
 *      same spreadsheet and you get an email with Approve / Deny buttons.
 *      Approved jobs appear on the board within about 5 minutes.
 *
 * No names, emails or IP addresses of visitors are stored. A visitor is a
 * random ID kept in their own browser, used only to count unique visitors.
 *
 * One-time setup: see apps-script-jobs/SETUP.md in the GitHub repo.
 */

const NOTIFY_EMAIL = '';            // blank = the Google account that deploys this
const EMAIL_POSTER_ON_APPROVAL = true;

const EVENT_COLS = ['time', 'date', 'visitor', 'event', 'jobId', 'company', 'title', 'tier', 'slot', 'detail', 'embedded', 'referrer', 'utm'];
const JOB_COLS = ['id', 'submittedAt', 'status', 'title', 'company', 'town', 'type', 'pay', 'applyUrl', 'description',
  'tierWanted', 'contactName', 'contactEmail', 'contactPhone', 'reviewedAt'];
const EVENTS = ['page_view', 'search', 'filter', 'job_open', 'apply_click', 'sponsored_view', 'sponsored_open',
  'sponsored_apply', 'cta_click', 'post_job_open', 'post_job_submit', 'browse_click'];

// ------------------------------------------------------------------ setup
/** Run once from the editor (select "setup" ▸ Run). Creates the spreadsheet and a secret key. */
function setup() {
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SECRET')) props.setProperty('SECRET', Utilities.getUuid() + Utilities.getUuid());
  let id = props.getProperty('SHEET_ID');
  if (!id) {
    const ss = SpreadsheetApp.create('Scout & Tell Job Board Stats');
    const ev = ss.getSheets()[0];
    ev.setName('Events');
    ev.getRange(1, 1, 1, EVENT_COLS.length).setValues([EVENT_COLS]).setFontWeight('bold');
    ev.setFrozenRows(1);
    const jobs = ss.insertSheet('Job Submissions');
    jobs.getRange(1, 1, 1, JOB_COLS.length).setValues([JOB_COLS]).setFontWeight('bold');
    jobs.setFrozenRows(1);
    ss.insertSheet('Daily Summary');
    id = ss.getId();
    props.setProperty('SHEET_ID', id);
  }
  // Rebuild the Daily Summary tab every night.
  ScriptApp.getProjectTriggers().forEach((t) => t.getHandlerFunction() === 'buildDailySummary' && ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('buildDailySummary').timeBased().atHour(2).everyDays(1).inTimezone('America/Denver').create();
  Logger.log('Stats spreadsheet: https://docs.google.com/spreadsheets/d/' + id);
}

function ss_() {
  const id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!id) throw new Error('Run setup() first.');
  return SpreadsheetApp.openById(id);
}
function notifyEmail_() { return NOTIFY_EMAIL || Session.getEffectiveUser().getEmail(); }
function sign_(id, action) {
  const secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  return Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(id + ':' + action, secret)).replace(/=+$/, '').slice(0, 32);
}
const clean_ = (v, n) => String(v == null ? '' : v).replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, n);

// ------------------------------------------------------------------ intake
function doPost(e) {
  try {
    const d = JSON.parse((e.postData && e.postData.contents) || '{}');
    if (d.kind === 'event') return logEvents_(Array.isArray(d.events) ? d.events : [d]);
    if (d.kind === 'job') return submitJob_(d);
    return json_({ ok: false, error: 'unknown' });
  } catch (err) {
    console.error(err);
    return json_({ ok: false, error: 'server' });
  }
}

function logEvents_(list) {
  // Basic flood protection: at most 3,000 events an hour.
  const cache = CacheService.getScriptCache();
  const n = Number(cache.get('evhour') || 0);
  if (n > 3000) return json_({ ok: false, error: 'busy' });
  cache.put('evhour', String(n + list.length), 3600);

  const now = new Date();
  const date = Utilities.formatDate(now, 'America/Denver', 'yyyy-MM-dd');
  const rows = list.slice(0, 25).filter((x) => EVENTS.indexOf(x.event) >= 0).map((x) => [
    now, date, clean_(x.visitor, 24), x.event, clean_(x.jobId, 40), clean_(x.company, 80), clean_(x.title, 120),
    clean_(x.tier, 20), clean_(x.slot, 20), clean_(x.detail, 120), x.embedded ? 'yes' : '', clean_(x.referrer, 80), clean_(x.utm, 60),
  ]);
  if (!rows.length) return json_({ ok: true });
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = ss_().getSheetByName('Events');
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, EVENT_COLS.length).setValues(rows);
  } finally { lock.releaseLock(); }
  return json_({ ok: true });
}

function submitJob_(d) {
  if (d.website) return json_({ ok: true }); // spam trap
  const rec = {
    id: Utilities.getUuid().slice(0, 8), submittedAt: new Date(), status: 'pending',
    title: clean_(d.title, 120), company: clean_(d.company, 100), town: clean_(d.town, 40), type: clean_(d.type, 30),
    pay: clean_(d.pay, 60), applyUrl: clean_(d.applyUrl, 500), description: clean_(d.description, 1500),
    tierWanted: clean_(d.tierWanted, 20), contactName: clean_(d.contactName, 80), contactEmail: clean_(d.contactEmail, 120),
    contactPhone: clean_(d.contactPhone, 30), reviewedAt: '',
  };
  if (!rec.title || !rec.company || !rec.town || !/@/.test(rec.contactEmail) || !(/^https?:\/\//i.test(rec.applyUrl) || /@/.test(rec.applyUrl))) {
    return json_({ ok: false, error: 'missing fields' });
  }
  const cache = CacheService.getScriptCache();
  const n = Number(cache.get('jobhour') || 0);
  if (n > 20) return json_({ ok: false, error: 'busy' });
  cache.put('jobhour', String(n + 1), 3600);

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try { ss_().getSheetByName('Job Submissions').appendRow(JOB_COLS.map((c) => rec[c])); }
  finally { lock.releaseLock(); }
  sendReviewEmail_(rec);
  return json_({ ok: true });
}

function sendReviewEmail_(r) {
  const base = ScriptApp.getService().getUrl();
  const link = (a) => base + '?action=' + a + '&id=' + r.id + '&t=' + sign_(r.id, a);
  const row = (k, v) => v ? '<tr><td style="padding:4px 12px 4px 0;color:#5E6B63;vertical-align:top">' + k + '</td><td style="padding:4px 0">' + v + '</td></tr>' : '';
  const btn = (href, label, bg) => '<a href="' + href + '" style="display:inline-block;background:' + bg +
    ';color:#fff;text-decoration:none;padding:12px 22px;font-weight:600;margin-right:10px;font-family:Arial,sans-serif">' + label + '</a>';
  const html = '<div style="font-family:Arial,sans-serif;color:#1F3D2D;max-width:560px">' +
    '<p style="color:#C24B2A;font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin:0 0 6px">New job posting</p>' +
    '<h2 style="margin:0 0 14px;font-family:Georgia,serif">' + h_(r.title) + ' · ' + h_(r.company) + '</h2>' +
    '<table style="font-size:14px;border-collapse:collapse">' +
    row('Town', h_(r.town)) + row('Type', h_(r.type)) + row('Pay', h_(r.pay)) +
    row('Apply', h_(r.applyUrl)) + row('About', h_(r.description)) +
    row('Wants', '<b>' + h_(r.tierWanted || 'Standard (free)') + '</b>') +
    row('From', h_(r.contactName) + ' &lt;' + h_(r.contactEmail) + '&gt; ' + h_(r.contactPhone)) +
    '</table><p style="margin:22px 0">' + btn(link('approve'), 'Approve', '#1F3D2D') + btn(link('deny'), 'Deny', '#C24B2A') + '</p>' +
    '<p style="font-size:12px;color:#5E6B63">Approve puts it on the board as a Standard listing. If they asked for a paid level, reply to set it up.</p></div>';
  MailApp.sendEmail({ to: notifyEmail_(), subject: 'Job posting: ' + r.title + ' at ' + r.company, htmlBody: html,
    replyTo: r.contactEmail || undefined, name: 'Scout & Tell Jobs' });
}

// ------------------------------------------------------------------ review + feed
function doGet(e) {
  const p = e.parameter || {};
  if (p.action === 'jobs') return json_({ jobs: approvedJobs_() });
  if (p.action === 'approve' || p.action === 'deny') return review_(p);
  return HtmlService.createHtmlOutput('Scout &amp; Tell jobs: OK');
}

function review_(p) {
  if (!p.id || p.t !== sign_(p.id, p.action)) return page_('That link is not valid.', '');
  const sh = ss_().getSheetByName('Job Submissions');
  const data = sh.getDataRange().getValues();
  const i = data.findIndex((r, k) => k > 0 && String(r[0]) === String(p.id));
  if (i < 0) return page_('Posting not found.', '');
  const rec = {}; JOB_COLS.forEach((c, k) => (rec[c] = data[i][k]));
  const verb = p.action === 'approve' ? 'Approve' : 'Deny';
  if (p.confirm !== '1') {
    const url = ScriptApp.getService().getUrl() + '?action=' + p.action + '&id=' + p.id + '&t=' + p.t + '&confirm=1';
    return page_(verb + ' "' + h_(rec.title) + '"?', 'Currently: <b>' + rec.status + '</b><br><br><a target="_top" href="' + url +
      '" style="display:inline-block;background:' + (p.action === 'approve' ? '#1F3D2D' : '#C24B2A') +
      ';color:#fff;padding:12px 22px;text-decoration:none;font-weight:600">Yes, ' + verb.toLowerCase() + '</a>');
  }
  const status = p.action === 'approve' ? 'approved' : 'denied';
  sh.getRange(i + 1, JOB_COLS.indexOf('status') + 1).setValue(status);
  sh.getRange(i + 1, JOB_COLS.indexOf('reviewedAt') + 1).setValue(new Date());
  CacheService.getScriptCache().remove('approvedJobs');
  if (status === 'approved' && EMAIL_POSTER_ON_APPROVAL && /@/.test(rec.contactEmail) && rec.status !== 'approved') {
    MailApp.sendEmail({ to: rec.contactEmail, subject: 'Your job is live on Scout & Tell',
      htmlBody: '<div style="font-family:Arial,sans-serif;color:#1F3D2D">Hi ' + h_(rec.contactName || 'there') +
        ',<br><br>Your <b>' + h_(rec.title) + '</b> posting is now live on the Scout &amp; Tell job board: ' +
        '<a href="https://www.scoutandtell.com/jobs">scoutandtell.com/jobs</a>. It stays up for 30 days.<br><br>Thanks,<br>Matt, Scout &amp; Tell</div>',
      name: 'Scout & Tell' });
  }
  return page_(status === 'approved' ? 'Approved ✓' : 'Denied',
    status === 'approved' ? '"' + h_(rec.title) + '" is now on the job board.' : '"' + h_(rec.title) + '" will not be shown.');
}

function approvedJobs_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('approvedJobs');
  if (hit) return JSON.parse(hit);
  const tz = 'America/Denver';
  const cutoff = new Date(Date.now() - 30 * 864e5);
  const out = [];
  ss_().getSheetByName('Job Submissions').getDataRange().getValues().slice(1).forEach((r) => {
    const rec = {}; JOB_COLS.forEach((c, k) => (rec[c] = r[k]));
    if (rec.status !== 'approved') return;
    const when = rec.reviewedAt instanceof Date ? rec.reviewedAt : rec.submittedAt;
    if (when < cutoff) return;
    out.push({ id: 'post-' + rec.id, title: rec.title, company: rec.company, town: rec.town, type: rec.type, pay: rec.pay,
      apply_url: /@/.test(rec.applyUrl) && !/^https?:/i.test(rec.applyUrl) ? 'mailto:' + rec.applyUrl : rec.applyUrl,
      description: rec.description, posted: Utilities.formatDate(when, tz, 'yyyy-MM-dd'), source: 'Posted on Scout & Tell', direct: true });
  });
  cache.put('approvedJobs', JSON.stringify(out), 300);
  return out;
}

// ------------------------------------------------------------------ reporting
/** Rebuilds the "Daily Summary" tab: one row per day with every count a sponsor would ask about. Runs nightly. */
function buildDailySummary() {
  const ss = ss_();
  const ev = ss.getSheetByName('Events').getDataRange().getValues().slice(1);
  const jobs = ss.getSheetByName('Job Submissions').getDataRange().getValues().slice(1);
  const days = {};
  const day = (d) => (days[d] = days[d] || { visitors: {}, page_view: 0, search: 0, filter: 0, job_open: 0, apply_click: 0,
    sponsored_view: 0, sponsored_open: 0, sponsored_apply: 0, cta_click: 0, post_job_open: 0, post_job_submit: 0, browse_click: 0, submitted: 0, approved: 0 });
  ev.forEach((r) => {
    const d = r[1] instanceof Date ? Utilities.formatDate(r[1], 'America/Denver', 'yyyy-MM-dd') : String(r[1]);
    const x = day(d);
    if (r[2]) x.visitors[r[2]] = 1;
    if (x[r[3]] != null) x[r[3]]++;
  });
  jobs.forEach((r) => {
    const d = Utilities.formatDate(new Date(r[1]), 'America/Denver', 'yyyy-MM-dd');
    day(d).submitted++;
    if (r[2] === 'approved') day(d).approved++;
  });
  const head = ['date', 'unique visitors', 'page views', 'searches', 'filter clicks', 'job clicks', 'apply clicks',
    'sponsored impressions', 'sponsored clicks', 'sponsored apply clicks', 'advertise/CTA clicks', 'post-a-job opens', 'jobs submitted', 'jobs approved'];
  const rows = Object.keys(days).sort().map((d) => {
    const x = days[d];
    return [d, Object.keys(x.visitors).length, x.page_view, x.search, x.filter, x.job_open, x.apply_click,
      x.sponsored_view, x.sponsored_open, x.sponsored_apply, x.cta_click, x.post_job_open, x.submitted, x.approved];
  });
  const sh = ss.getSheetByName('Daily Summary');
  sh.clear();
  sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
  if (rows.length) sh.getRange(2, 1, rows.length, head.length).setValues(rows);
  sh.setFrozenRows(1);
}

// ------------------------------------------------------------------ helpers
function h_(s) { return String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function json_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
function page_(title, body) {
  return HtmlService.createHtmlOutput('<div style="font-family:Arial,sans-serif;color:#1F3D2D;max-width:520px;margin:60px auto;padding:0 20px">' +
    '<p style="color:#C24B2A;font-size:12px;letter-spacing:.12em;text-transform:uppercase">Scout &amp; Tell jobs</p>' +
    '<h2 style="font-family:Georgia,serif">' + title + '</h2><p>' + body + '</p></div>').setTitle('Scout & Tell jobs');
}
