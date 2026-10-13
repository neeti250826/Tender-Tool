// Open CAPT winning-bids page, log XHR/fetch calls (url, method, post body) and a sample response.
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, locale: 'en-US' });
  const p = await ctx.newPage(); const log = [];
  p.on('request', r => { if (['xhr', 'fetch'].includes(r.resourceType())) log.push({ m: r.method(), u: r.url(), body: r.postData() }); });
  p.on('response', async r => { if (['xhr', 'fetch'].includes(r.request().resourceType())) { try { const t = await r.text(); fs.writeFileSync('capt_resp_' + log.length + '.txt', t.slice(0, 20000)); } catch (e) {} } });
  const r = await p.goto('https://capt.gov.kw/en/tenders/winning-bids/', { timeout: 90000, waitUntil: 'networkidle' }).catch(e => console.log('goto', e.message));
  console.log('status', r && r.status(), await p.title());
  fs.writeFileSync('capt_page.html', await p.content());
  console.log(JSON.stringify(log, null, 1).slice(0, 3000));
  const forms = await p.evaluate(() => [...document.querySelectorAll('input,select,button')].map(e => `${e.tagName} ${e.name || ''} ${e.id || ''} ${(e.innerText || e.value || '').slice(0, 30)}`));
  console.log(forms.slice(0, 40).join('\n'));
  await b.close();
})();
