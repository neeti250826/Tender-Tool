// One raw list call from the EKAP tab; print status, headers and body to see why EKAP throttles.
const { attach } = require('./ekap_lib');
const lib = require('./ekap_lib');
(async () => {
  const { page } = await attach();
  const r = await page.evaluate(async () => {
    const s = await fetch('/b_han/api/human-verification/status', { credentials: 'include' });
    return { st: s.status, body: (await s.text()).slice(0, 400) };
  });
  console.log('verification status:', r.st, r.body);
  console.log('page url:', page.url());
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
