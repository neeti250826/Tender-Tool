// Opens EKAP v2 in a visible Chrome (persistent profile, CDP on 9334) for the user to pass the
// human-verification check. Logs the site's own API calls (URL + request headers) so the extractor
// can reproduce them from inside the verified page. Stays open until the window is closed.
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
const LOG = path.join(__dirname, 'ekap_api_requests.jsonl');
(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-ekap',
    { channel: 'chrome', headless: false, viewport: null, args: ['--remote-debugging-port=9334', '--start-maximized'] });
  ctx.on('request', r => {
    const u = r.url();
    if (/ekapv2\.kik\.gov\.tr\/(b_|api)/.test(u))
      fs.appendFileSync(LOG, JSON.stringify({ t: Date.now(), m: r.method(), u, h: r.headers(), body: r.postData() }) + '\n');
  });
  ctx.on('response', async r => {
    const u = r.url();
    if (/ekapv2\.kik\.gov\.tr\/(b_|api)/.test(u))
      fs.appendFileSync(LOG, JSON.stringify({ t: Date.now(), resp: r.status(), u }) + '\n');
  });
  const page = ctx.pages()[0] || await ctx.newPage();
  await page.goto('https://ekapv2.kik.gov.tr/ekap/search', { timeout: 120000 }).catch(e => console.log('goto', e.message));
  console.log('EKAP session open on CDP 9334');
  await new Promise(res => ctx.on('close', res));
})();
