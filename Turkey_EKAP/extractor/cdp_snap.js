// Attach to the EKAP session browser (CDP 9334): print URL/title/visible text, save a screenshot.
const { chromium } = require('playwright-core');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:' + (process.env.CDP_PORT || '9222') + '');
  const p = b.contexts()[0].pages().find(p => p.url().includes('ekap')) || b.contexts()[0].pages()[0];
  console.log(p.url(), '|', await p.title());
  console.log((await p.evaluate(() => document.body.innerText)).slice(0, 800));
  await p.screenshot({ path: process.argv[2] || 'snap.png' });
  process.exit(0); // never b.close(): over CDP that shuts the user's browser
})();
