// Walk eSupply past opportunities backwards in time for buyers containing <term>:
// filter "Publication Date BEFORE d" + buyer, export (max 2000 rows), set d = oldest publication date seen, repeat until < STOP.
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
const term = process.argv[2] || 'Health', STOP = process.argv[3] || '2024-01-01';
const OUT = path.join(__dirname, 'exports'); fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  let before = process.argv[4] || null, n = 0;
  while (true) {
    const ctx = await b.newContext({ ignoreHTTPSErrors: true });
    const p = await ctx.newPage();
    await p.goto('https://esupply.dubai.gov.ae/esop/guest/go/public/opportunity/past', { timeout: 120000, waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(4000);
    await p.evaluate(({ term, before }) => {
      const f = document.getElementById('OpportunityListManager');
      const set = (n, v) => { const e = f.querySelector(`[name="${n}"]`); if (e) { e.disabled = false; e.value = v; } };
      set('purchasingOrganizationInfo_FILTER', term); set('purchasingOrganizationInfo_FILTER_OPERATOR', 'CONTAINS');
      if (before) { set('firstPublishingDate_FILTER_OPERATOR', 'BEFORE'); set('firstPublishingDate_FILTER', before); }
      set('filterEnabled', 'true');
      setListUserAct('OpportunityListManager', 'search'); xhrPostListForm('OpportunityListManager', 'true');
    }, { term, before });
    await p.waitForTimeout(12000);
    const r = await ctx.request.get('https://esupply.dubai.gov.ae/esop/toolkit/opportunity/past/list.si?export=xls', { timeout: 300000 });
    const file = path.join(OUT, `export_${String(n).padStart(3, '0')}_${(before || 'latest').replace(/\//g, '-')}.xlsx`);
    fs.writeFileSync(file, await r.body());
    await ctx.close();
    // oldest publication date in this export (python helper reads the xlsx)
    const res = require('child_process').execSync(`python "${path.join(__dirname, 'oldest_date.py')}" "${file}"`, { encoding: 'utf8' }).trim();
    const [rows, oldest] = res.split(' ');
    console.log(n, 'before', before, '-> rows', rows, 'oldest', oldest, flush = true);
    if (!oldest || oldest === 'None' || +rows === 0) break;
    const [dd, mm, yy] = oldest.split('/');
    if (`${yy}-${mm}-${dd}` < STOP) break;
    if (before === oldest) { // a single day has >2000 rows: step one day back to avoid looping
      const d = new Date(`${yy}-${mm}-${dd}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - 1);
      before = `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${d.getUTCFullYear()}`;
    } else before = oldest;
    n++;
  }
  await b.close();
})();
