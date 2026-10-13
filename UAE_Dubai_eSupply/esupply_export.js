// eSupply past opportunities: filter by buyer text using the page's own search functions, then export (?export=xls).
const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const term = process.argv[2] || 'Health';
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, acceptDownloads: true });
  const p = await ctx.newPage();
  await p.goto('https://esupply.dubai.gov.ae/esop/guest/go/public/opportunity/past', { timeout: 90000, waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(4000);
  await p.evaluate((term) => {
    const f = document.getElementById('OpportunityListManager');
    const i = f.querySelector('input[name="purchasingOrganizationInfo_FILTER"]'); i.disabled = false; i.value = term;
    const op = f.querySelector('select[name="purchasingOrganizationInfo_FILTER_OPERATOR"]'); if (op) { op.disabled = false; op.value = 'CONTAINS'; }
    f.querySelector('input[name="filterEnabled"]').value = 'true';
    setListUserAct('OpportunityListManager', 'search'); xhrPostListForm('OpportunityListManager', 'true');
  }, term);
  await p.waitForTimeout(10000);
  const txt = await p.evaluate(() => document.body.innerText);
  console.log('rows shown:', (txt.match(/\nAED\t[^\n]+/g) || []).length, '|', (txt.match(/\t(Dubai[^\t]{0,50})\t/g) || []).slice(0, 4));
  const r = await ctx.request.get('https://esupply.dubai.gov.ae/esop/toolkit/opportunity/past/list.si?export=xls', { timeout: 180000 });
  const body = await r.body();
  const out = `esupply_past_${term.replace(/\W+/g, '_')}.xls`;
  fs.writeFileSync(out, body);
  console.log('export', r.status(), r.headers()['content-type'], body.length, out);
  await b.close();
})();
