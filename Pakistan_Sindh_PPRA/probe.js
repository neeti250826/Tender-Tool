// Load Sindh PPRA in headless Chrome, list links that look like BER / evaluation / award pages.
const { chromium } = require('playwright-core');
(async () => {
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const ctx = await b.newContext({ ignoreHTTPSErrors: true });
  const p = await ctx.newPage();
  for (const u of ['https://pprasindh.gov.pk/', 'https://www.pprasindh.gov.pk/ber.php', 'https://pprasindh.gov.pk/ber.php']) {
    try {
      const r = await p.goto(u, { timeout: 60000, waitUntil: 'domcontentloaded' });
      console.log('==', u, r && r.status(), await p.title());
      const links = await p.evaluate(() => [...document.querySelectorAll('a')].map(a => (a.innerText.trim().slice(0, 50) + ' -> ' + a.href)).filter(x => /ber|evaluat|award|contract|result|export|bid/i.test(x)));
      console.log(links.slice(0, 40).join('\n'));
    } catch (e) { console.log('ERR', u, e.message.slice(0, 120)); }
  }
  await b.close();
})();
