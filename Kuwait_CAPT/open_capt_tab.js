// Open CAPT winning-bids in a NEW tab of the user's debug Edge (port 9222); leaves EKAP tab untouched.
const { chromium } = require('playwright-core');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = b.contexts()[0];
  let p = ctx.pages().find(x => x.url().includes('capt.gov.kw'));
  if (!p) { p = await ctx.newPage(); await p.goto('https://capt.gov.kw/en/tenders/winning-bids/', { timeout: 90000 }).catch(e => console.log(e.message)); }
  await p.bringToFront();
  await p.waitForTimeout(8000);
  console.log(p.url(), '|', await p.title());
  await p.screenshot({ path: 'capt_snap.png' });
  process.exit(0);
})();
