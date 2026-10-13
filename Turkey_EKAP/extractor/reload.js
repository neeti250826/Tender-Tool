// Reload the EKAP tab in the user's Edge so the Cloudflare check is shown again (does not close anything).
const { attach } = require('./ekap_lib');
(async () => { const { page } = await attach(); await page.reload({ waitUntil: 'domcontentloaded', timeout: 90000 }); await page.waitForTimeout(8000); await page.screenshot({ path: 'snap.png' }); process.exit(0); })().catch(e => { console.error(e.message); process.exit(1); });
