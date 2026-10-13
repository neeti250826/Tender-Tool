// Remove the other editor's README rows (17, then 8-15) that describe the deleted CY2025 block; keep row 16 (SOP link).
const { chromium } = require('playwright-core');
(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', { channel: 'chrome', headless: false, viewport: { width: 1500, height: 900 } });
  const p = ctx.pages()[0] || await ctx.newPage();
  await p.goto('https://docs.google.com/spreadsheets/d/<MASTER_SHEET_ID>/edit', { timeout: 120000, waitUntil: 'domcontentloaded' });
  await p.waitForSelector('#t-name-box', { timeout: 120000 }); await p.waitForTimeout(5000);
  const jump = async (ref) => { await p.click('#t-name-box'); await p.keyboard.press('Control+A'); await p.keyboard.type(ref); await p.keyboard.press('Enter'); await p.waitForTimeout(700); };
  const fb = async () => (await p.locator('#t-formula-bar-input').innerText().catch(() => '')).trim();
  const t = p.locator('.docs-sheet-tab-name').filter({ hasText: /^README$/ }).first(); await t.click(); await p.waitForTimeout(2000);
  const delRows = async (range) => {
    await jump(range);
    await p.getByRole('menuitem', { name: /^Edit$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Delete/ }).first().hover(); await p.waitForTimeout(600);
    const item = p.getByRole('menuitem', { name: /^Rows? \d/ }).first(); const label = await item.innerText(); await item.click(); await p.waitForTimeout(1500);
    console.log('deleted', label.replace(/\s+/g, ' '));
  };
  await jump('A17'); const a17 = await fb(); await jump('A8'); const a8 = await fb(); await jump('A15'); const a15 = await fb();
  if (!/^Refresh control/.test(a17) || !/^CY2025 assessment/.test(a8) || !/^CY2025 Summary/.test(a15)) { console.log('layout changed - aborting:', a8, '|', a15, '|', a17); await ctx.close(); return; }
  await delRows('A17:A17'); await delRows('A8:A15');
  await jump('A8'); console.log('A8 now:', (await fb()).slice(0, 40)); await jump('A9'); console.log('A9 now:', (await fb()).slice(0, 50));
  await p.waitForTimeout(3000); await ctx.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
