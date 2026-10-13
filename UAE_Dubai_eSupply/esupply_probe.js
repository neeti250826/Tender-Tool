// Probe Dubai eSupply public opportunities pages; log XHR endpoints and links.
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await b.newContext({ ignoreHTTPSErrors: true });
  const p = await ctx.newPage(); const log = [];
  p.on('request', r => { if (['xhr', 'fetch', 'document'].includes(r.resourceType())) log.push(r.method() + ' ' + r.url()); });
  for (const u of ['https://esupply.dubai.gov.ae/', 'https://esupply.dubai.gov.ae/esop/guest/go/public/opportunity/past']) {
    const r = await p.goto(u, { timeout: 90000, waitUntil: 'domcontentloaded' }).catch(e => console.log('ERR', e.message.slice(0, 100)));
    await p.waitForTimeout(5000);
    console.log('==', u, r && r.status(), await p.title());
    const links = await p.evaluate(() => [...document.querySelectorAll('a')].map(a => a.innerText.trim().slice(0, 40) + ' -> ' + a.href).filter(x => /opportunit|past|award|tender|public/i.test(x)));
    console.log(links.slice(0, 25).join('\n'));
    fs.writeFileSync('esupply_' + (u.endsWith('past') ? 'past' : 'home') + '.html', await p.content());
  }
  console.log(log.slice(0, 30).join('\n'));
  await b.close();
})();
