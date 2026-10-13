// Fetch winning-bids results from inside the CAPT tab. Usage: node capt_get.js "<query string>" out.html
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const [qs, out] = process.argv.slice(2);
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const p = b.contexts()[0].pages().find(x => x.url().includes('capt.gov.kw'));
  const r = await p.evaluate(async (qs) => { const x = await fetch('/en/tenders/winning-bids/?' + qs, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'include' }); return { s: x.status, ct: x.headers.get('content-type'), t: await x.text() }; }, qs);
  fs.writeFileSync(out, r.t); console.log(r.s, r.ct, r.t.length);
  process.exit(0);
})();
