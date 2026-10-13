// Shared helpers: attach to the user's verified EKAP tab (Edge, CDP 9222) and call EKAP's API from inside it.
const { chromium } = require('playwright-core');
const crypto = require('crypto');
const API = 'https://ekapv2.kik.gov.tr/b_ihalearama/api';
const R8 = 'Qm2LtXR0aByP69vZNKef4wMJ'; // AES-192 key from the EKAP bundle (same as ekap_extract.py)

function secHeaders() {
  const guid = crypto.randomUUID(), ts = String(Date.now()), iv = crypto.randomBytes(16);
  const enc = v => { const c = crypto.createCipheriv('aes-192-cbc', Buffer.from(R8, 'utf8'), iv); return Buffer.concat([c.update(v, 'utf8'), c.final()]).toString('base64'); };
  return { 'X-Custom-Request-Ts': enc(ts), 'X-Custom-Request-Siv': iv.toString('base64'), 'X-Custom-Request-R8id': enc(guid), 'X-Custom-Request-Guid': guid };
}

async function attach(port = process.env.CDP_PORT || '9222') {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:' + port);
  const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes('ekapv2.kik.gov.tr'));
  if (!page) throw new Error('No EKAP tab open in the browser on port ' + port);
  return { browser, page };
}

const PACE_MS = +(process.env.EKAP_PACE_MS || 1200);
let last = 0;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Paced POST with exponential backoff on 429/5xx. Returns {status, json, text}.
async function post(page, path, body, tries = 6) {
  for (let a = 0; a < tries; a++) {
    const wait = last + PACE_MS - Date.now(); if (wait > 0) await sleep(wait);
    last = Date.now();
    const r = await postOnce(page, path, body);
    if (r.status === 428) {            // human verification lapsed: wait for the user to tick the check again
      await waitForVerification(page);
      a--; continue;
    }
    if (r.status !== 429 && r.status < 500) return r;
    const back = Math.min(180000, 30000 * (a + 1)); // EKAP allows ~1 call / 30 s
    console.error(`  ${r.status} on ${path} - backing off ${back / 1000}s`);
    await sleep(back);
  }
  return postOnce(page, path, body);
}

// Poll EKAP's own verification status until the user has passed the Cloudflare check (max 12 h).
async function waitForVerification(page) {
  console.error('  428: EKAP needs the human check again - waiting for it to be ticked in the browser...');
  const t0 = Date.now();
  while (Date.now() - t0 < 12 * 3600e3) {
    const st = await page.evaluate(async () => {
      try { return await (await fetch('/b_han/api/human-verification/status', { credentials: 'include' })).json(); } catch (e) { return {}; }
    }).catch(() => ({}));
    if (st && st.verified) { console.error('  verification passed - resuming'); return; }
    await sleep(30000);
  }
  throw new Error('human verification not passed within 12 h');
}

async function postOnce(page, path, body) {
  const headers = { 'Accept': 'application/json', 'Content-Type': 'application/json', 'api-version': 'v1', ...secHeaders() };
  return page.evaluate(async ({ url, headers, body }) => {
    const r = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), credentials: 'include' });
    const t = await r.text();
    let j = null; try { j = JSON.parse(t); } catch (e) {}
    return { status: r.status, json: j, text: j ? null : t.slice(0, 300) };
  }, { url: API + path, headers, body });
}

module.exports = { attach, post, API };
