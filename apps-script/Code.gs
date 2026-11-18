/**
 * Scout & Tell — event submissions
 *
 * What this does
 *   1. The calendar's "Submit an event" form posts here.
 *   2. The submission is saved to a Google Sheet ("Scout & Tell Event Submissions")
 *      and you get an email with Approve / Deny buttons.
 *   3. Approve -> the event appears on the calendar right away.
 *      Deny    -> it stays in the sheet, marked denied, and never shows.
 *
 * One-time setup: see apps-script/SETUP.md in the GitHub repo.
 */

// Who gets the review emails. Leave blank to use the Google account that deploys this.
const NOTIFY_EMAIL = '';
// Email the person who submitted when their event is approved?
const EMAIL_SUBMITTER_ON_APPROVAL = true;

const SHEET_NAME = 'Submissions';
const COLUMNS = ['id', 'submittedAt', 'status', 'title', 'date', 'endDate', 'start', 'end',
  'venue', 'address', 'city', 'category', 'price', 'url', 'desc', 'contactName', 'contactEmail', 'reviewedAt'];

// ------------------------------------------------------------------ setup
/** Run this once from the editor (select "setup" ▸ Run). It creates the sheet and a secret key. */
function setup() {
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SECRET')) props.setProperty('SECRET', Utilities.getUuid() + Utilities.getUuid());
  let id = props.getProperty('SHEET_ID');
  if (!id) {
    const ss = SpreadsheetApp.create('Scout & Tell Event Submissions');
    const sh = ss.getSheets()[0];
    sh.setName(SHEET_NAME);
    sh.getRange(1, 1, 1, COLUMNS.length).setValues([COLUMNS]).setFontWeight('bold');
    sh.setFrozenRows(1);
    id = ss.getId();
    props.setProperty('SHEET_ID', id);
  }
  Logger.log('Submissions sheet: https://docs.google.com/spreadsheets/d/' + id);
}

function sheet_() {
  const id = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!id) throw new Error('Run setup() first.');
  return SpreadsheetApp.openById(id).getSheetByName(SHEET_NAME);
}

function notifyEmail_() { return NOTIFY_EMAIL || Session.getEffectiveUser().getEmail(); }

function sign_(id, action) {
  const secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  const raw = Utilities.computeHmacSha256Signature(id + ':' + action, secret);
  return Utilities.base64EncodeWebSafe(raw).replace(/=+$/, '').slice(0, 32);
}

// ------------------------------------------------------------------ intake
function doPost(e) {
  try {
    const d = JSON.parse((e.postData && e.postData.contents) || '{}');
    if (d.website) return json_({ ok: true }); // spam trap filled in by a bot

    const clean = (v, n) => String(v || '').replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, n);
    const rec = {
      id: Utilities.getUuid().slice(0, 8),
      submittedAt: new Date(),
      status: 'pending',
      title: clean(d.title, 160),
      date: clean(d.date, 10),
      endDate: clean(d.endDate, 10),
      start: clean(d.start, 5),
      end: clean(d.end, 5),
      venue: clean(d.venue, 120),
      address: clean(d.address, 160),
      city: clean(d.city, 60),
      category: clean(d.category, 40),
      price: clean(d.price, 80),
      url: clean(d.url, 500),
      desc: clean(d.desc, 600),
      contactName: clean(d.contactName, 80),
      contactEmail: clean(d.contactEmail, 120),
      reviewedAt: '',
    };
    if (!rec.title || !/^\d{4}-\d{2}-\d{2}$/.test(rec.date) || !/^https?:\/\//i.test(rec.url)) {
      return json_({ ok: false, error: 'missing fields' });
    }

    // Light flood protection: at most 20 submissions an hour.
    const cache = CacheService.getScriptCache();
    const n = Number(cache.get('hourly') || 0);
    if (n > 20) return json_({ ok: false, error: 'busy' });
    cache.put('hourly', String(n + 1), 3600);

    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try { sheet_().appendRow(COLUMNS.map((c) => (c === 'date' || c === 'endDate') ? "'" + rec[c] : rec[c])); }
    finally { lock.releaseLock(); }

    sendReviewEmail_(rec);
    return json_({ ok: true });
  } catch (err) {
    console.error(err);
    return json_({ ok: false, error: 'server' });
  }
}

function sendReviewEmail_(r) {
  const base = ScriptApp.getService().getUrl();
  const link = (action) => base + '?action=' + action + '&id=' + r.id + '&t=' + sign_(r.id, action);
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const when = r.date + (r.endDate ? ' to ' + r.endDate : '') + (r.start ? ', ' + r.start + (r.end ? '–' + r.end : '') : '');
  const row = (k, v) => v ? '<tr><td style="padding:4px 12px 4px 0;color:#5E6B63;vertical-align:top">' + k + '</td><td style="padding:4px 0">' + v + '</td></tr>' : '';
  const btn = (href, label, bg) => '<a href="' + href + '" style="display:inline-block;background:' + bg +
    ';color:#fff;text-decoration:none;padding:12px 22px;font-weight:600;margin-right:10px;font-family:Arial,sans-serif">' + label + '</a>';

  const html =
    '<div style="font-family:Arial,sans-serif;color:#1F3D2D;max-width:560px">' +
    '<p style="color:#C24B2A;font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin:0 0 6px">New event submission</p>' +
    '<h2 style="margin:0 0 14px;font-family:Georgia,serif">' + esc(r.title) + '</h2>' +
    '<table style="font-size:14px;border-collapse:collapse">' +
    row('When', esc(when)) + row('Where', esc([r.venue, r.address, r.city].filter(String).join(', '))) +
    row('Type', esc(r.category)) + row('Price', esc(r.price)) +
    row('Link', '<a href="' + esc(r.url) + '">' + esc(r.url) + '</a>') + row('About', esc(r.desc)) +
    row('From', esc(r.contactName) + ' &lt;' + esc(r.contactEmail) + '&gt;') +
    '</table><p style="margin:22px 0">' + btn(link('approve'), 'Approve', '#1F3D2D') + btn(link('deny'), 'Deny', '#C24B2A') + '</p>' +
    '<p style="font-size:12px;color:#5E6B63">Each button opens a confirmation page, so nothing changes until you click once more there.</p></div>';

  MailApp.sendEmail({
    to: notifyEmail_(),
    subject: 'Event submission: ' + r.title + ' (' + r.date + ')',
    htmlBody: html,
    replyTo: r.contactEmail || undefined,
    name: 'Scout & Tell Events',
  });
}

// ------------------------------------------------------------------ review + feed
function doGet(e) {
  const p = e.parameter || {};
  if (p.action === 'approved') return json_({ events: approvedEvents_() });
  if (p.action === 'approve' || p.action === 'deny') return review_(p);
  return HtmlService.createHtmlOutput('Scout &amp; Tell events: OK');
}

function review_(p) {
  if (!p.id || p.t !== sign_(p.id, p.action)) return page_('That link is not valid.', '');
  const sh = sheet_();
  const data = sh.getDataRange().getValues();
  const rowIdx = data.findIndex((r, i) => i > 0 && String(r[0]) === String(p.id));
  if (rowIdx < 0) return page_('Submission not found.', '');
  const rec = {}; COLUMNS.forEach((c, i) => (rec[c] = data[rowIdx][i]));
  const safeTitle = h_(rec.title);
  const verb = p.action === 'approve' ? 'Approve' : 'Deny';

  // First visit shows a confirm button, so email link-scanners can't approve by accident.
  if (p.confirm !== '1') {
    const url = ScriptApp.getService().getUrl() + '?action=' + p.action + '&id=' + p.id + '&t=' + p.t + '&confirm=1';
    return page_(verb + ' "' + safeTitle + '"?',
      'Currently: <b>' + rec.status + '</b><br><br><a target="_top" href="' + url + '" style="display:inline-block;background:' +
      (p.action === 'approve' ? '#1F3D2D' : '#C24B2A') + ';color:#fff;padding:12px 22px;text-decoration:none;font-weight:600">Yes, ' + verb.toLowerCase() + '</a>');
  }

  const status = p.action === 'approve' ? 'approved' : 'denied';
  sh.getRange(rowIdx + 1, COLUMNS.indexOf('status') + 1).setValue(status);
  sh.getRange(rowIdx + 1, COLUMNS.indexOf('reviewedAt') + 1).setValue(new Date());
  CacheService.getScriptCache().remove('approved');

  if (status === 'approved' && EMAIL_SUBMITTER_ON_APPROVAL && /@/.test(rec.contactEmail) && rec.status !== 'approved') {
    MailApp.sendEmail({
      to: rec.contactEmail,
      subject: 'Your event is on the Scout & Tell calendar',
      htmlBody: '<div style="font-family:Arial,sans-serif;color:#1F3D2D">Hi ' + (rec.contactName || 'there') +
        ',<br><br>Thanks for sending in <b>' + safeTitle + '</b>. It\'s now live on the Scout &amp; Tell events calendar: ' +
        '<a href="https://www.scoutandtell.com/events">scoutandtell.com/events</a>.<br><br>Scout &amp; Tell</div>',
      name: 'Scout & Tell',
    });
  }
  return page_(status === 'approved' ? 'Approved ✓' : 'Denied',
    status === 'approved' ? '"' + safeTitle + '" is now on the calendar.' : '"' + safeTitle + '" will not be shown.');
}

function approvedEvents_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('approved');
  if (hit) return JSON.parse(hit);
  const tz = 'America/Denver';
  const today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  const fmt = (v) => v instanceof Date ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : String(v || '');
  const fmtT = (v) => v instanceof Date ? Utilities.formatDate(v, tz, 'HH:mm') : String(v || '');
  const rows = sheet_().getDataRange().getValues().slice(1);
  const out = [];
  rows.forEach((r) => {
    const rec = {}; COLUMNS.forEach((c, i) => (rec[c] = r[i]));
    if (rec.status !== 'approved') return;
    const date = fmt(rec.date), endDate = fmt(rec.endDate);
    if ((endDate || date) < today) return;
    out.push({
      id: String(rec.id), title: rec.title, date: date, endDate: endDate,
      start: fmtT(rec.start), end: fmtT(rec.end), venue: rec.venue, address: rec.address, city: rec.city,
      category: rec.category, price: rec.price, url: rec.url, desc: rec.desc,
    });
  });
  // Multi-day events (under two weeks) show on each day they run.
  const expanded = [];
  out.forEach((ev) => {
    if (!ev.endDate || ev.endDate <= ev.date) return expanded.push(ev);
    const start = new Date(ev.date + 'T12:00:00'), end = new Date(ev.endDate + 'T12:00:00');
    const days = Math.round((end - start) / 864e5);
    if (days >= 14) return expanded.push(ev); // the calendar shows these under "Ongoing"
    for (let i = 0; i <= days; i++) {
      const d = Utilities.formatDate(new Date(start.getTime() + i * 864e5), tz, 'yyyy-MM-dd');
      if (d >= today) expanded.push(Object.assign({}, ev, { id: ev.id + '-' + i, date: d, endDate: '' }));
    }
  });
  cache.put('approved', JSON.stringify(expanded), 300);
  return expanded;
}

function h_(s) {
  return String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function page_(title, body) {
  return HtmlService.createHtmlOutput(
    '<div style="font-family:Arial,sans-serif;color:#1F3D2D;max-width:520px;margin:60px auto;padding:0 20px">' +
    '<p style="color:#C24B2A;font-size:12px;letter-spacing:.12em;text-transform:uppercase">Scout &amp; Tell events</p>' +
    '<h2 style="font-family:Georgia,serif">' + title + '</h2><p>' + body + '</p></div>'
  ).setTitle('Scout & Tell events');
}
