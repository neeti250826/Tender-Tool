// eSupply past opportunities for buyers containing <term>, one export per publication DAY (filter EQUAL), so the
// 2000-row export cap never truncates (the list is sorted by closing date, so date-stepping would skip rows).
// Usage: node esupply_daily.js Health 2024-01-01 2026-10-01 [workers]
// Output: uae/daily/<yyyy-mm-dd>.xlsx (skipped if present -> resumable)
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
const [term = 'Health', from = '2024-01-01', to = '2026-10-01', W = '3'] = process.argv.slice(2);
const OUT = path.join(__dirname, 'daily'); fs.mkdirSync(OUT, { recursive: true });

const days = [];
for (let d = new Date(from + 'T00:00:00Z'); d <= new Date(to + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1)) days.push(new Date(d));
const iso = d => d.toISOString().slice(0, 10);
const dmy = d => `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${d.getUTCFullYear()}`;

async function one(b, d) {
  const file = path.join(OUT, iso(d) + '.xlsx');
  if (fs.existsSync(file)) return;
  const ctx = await b.newContext({ ignoreHTTPSErrors: true });
  try {
    const p = await ctx.newPage();
    await p.goto('https://esupply.dubai.gov.ae/esop/guest/go/public/opportunity/past', { timeout: 120000, waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(3000);
    await p.evaluate(({ term, day }) => {
      const f = document.getElementById('OpportunityListManager');
      const set = (n, v) => { const e = f.querySelector(`[name="${n}"]`); if (e) { e.disabled = false; e.value = v; } };
      set('purchasingOrganizationInfo_FILTER', term); set('purchasingOrganizationInfo_FILTER_OPERATOR', 'CONTAINS');
      set('firstPublishingDate_FILTER_OPERATOR', 'EQUAL'); set('firstPublishingDate_FILTER', day);
      set('filterEnabled', 'true');
      setListUserAct('OpportunityListManager', 'search'); xhrPostListForm('OpportunityListManager', 'true');
    }, { term, day: dmy(d) });
    await p.waitForTimeout(8000);
    const r = await ctx.request.get('https://esupply.dubai.gov.ae/esop/toolkit/opportunity/past/list.si?export=xls', { timeout: 300000 });
    const body = await r.body();
    if (r.status() === 200 && body.slice(0, 2).toString() === 'PK') fs.writeFileSync(file, body);
    else console.log('bad export', iso(d), r.status());
  } catch (e) { console.log('ERR', iso(d), e.message.slice(0, 100)); }
  finally { await ctx.close(); }
}

(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  let i = 0, done = 0;
  await Promise.all([...Array(+W)].map(async () => {
    while (i < days.length) { const d = days[i++]; await one(b, d); if (++done % 20 === 0) console.log('done', done, '/', days.length, iso(d)); }
  }));
  await b.close();
  console.log('finished', days.length);
})();
