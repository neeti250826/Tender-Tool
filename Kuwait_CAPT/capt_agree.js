// Click "I AGREE" on CAPT (user approved), then capture the XHR calls the winning-bids page makes.
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const p = b.contexts()[0].pages().find(x => x.url().includes('capt.gov.kw'));
  const log = [];
  p.on('request', r => { if (['xhr', 'fetch'].includes(r.resourceType())) log.push({ m: r.method(), u: r.url(), body: r.postData(), h: r.headers() }); });
  p.on('response', async r => { if (['xhr', 'fetch'].includes(r.request().resourceType())) { try { fs.writeFileSync('capt_xhr_' + log.length + '.txt', (await r.text()).slice(0, 30000)); } catch (e) {} } });
  const btn = p.getByText('I AGREE', { exact: true });
  if (await btn.count()) { await btn.first().click(); console.log('clicked I AGREE'); }
  await p.waitForTimeout(8000);
  await p.screenshot({ path: 'capt_snap.png' });
  fs.writeFileSync('capt_page.html', await p.content());
  console.log(JSON.stringify(log.map(l => ({ m: l.m, u: l.u, body: (l.body || '').slice(0, 300) })), null, 1));
  process.exit(0);
})();
