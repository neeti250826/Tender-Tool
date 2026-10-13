// In the CAPT tab: list ministry options, then submit the winning-bids ajax form once and record the request/response.
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const p = b.contexts()[0].pages().find(x => x.url().includes('capt.gov.kw'));
  const opts = await p.evaluate(() => [...document.querySelectorAll('form.ajax-form select[name="ministry_code"]')].map(s => [...s.options].map(o => o.value + '=' + o.text.trim())));
  fs.writeFileSync('capt_ministries.json', JSON.stringify(opts, null, 1));
  console.log(opts.map(o => o.length), (opts[0] || []).filter(x => /health|صحة|medical/i.test(x)));
  const forms = await p.evaluate(() => [...document.querySelectorAll('form.ajax-form')].map((f, i) => i + ': ' + [...f.elements].map(e => `${e.name}[${e.type}]`).join(' ') + ' | ' + (f.closest('section,div')?.innerText || '').slice(0, 80).replace(/\n/g, ' ')));
  console.log(forms.join('\n'));
  const log = [];
  p.on('request', r => { if (['xhr', 'fetch'].includes(r.resourceType())) log.push({ m: r.method(), u: r.url(), body: r.postData() }); });
  p.on('response', async r => { if (['xhr', 'fetch'].includes(r.request().resourceType())) { try { fs.writeFileSync('capt_xhr_resp.txt', await r.text()); } catch (e) {} } });
  await p.evaluate(() => { const f = document.querySelectorAll('form.ajax-form')[0]; f.requestSubmit ? f.requestSubmit() : f.submit(); });
  await p.waitForTimeout(8000);
  console.log(JSON.stringify(log, null, 1).slice(0, 2500));
  process.exit(0);
})();
