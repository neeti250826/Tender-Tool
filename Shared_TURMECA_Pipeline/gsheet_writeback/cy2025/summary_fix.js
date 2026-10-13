// Summary tab: delete the other editor's M:T (#REF! formulas) and paste the static CY2025 summary block at M1.
const { chromium } = require('playwright-core');
const { execFileSync } = require('child_process'); const path = require('path');
(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', { channel: 'chrome', headless: false, viewport: { width: 1500, height: 900 } });
  const p = ctx.pages()[0] || await ctx.newPage();
  await p.goto('https://docs.google.com/spreadsheets/d/<MASTER_SHEET_ID>/edit', { timeout: 120000, waitUntil: 'domcontentloaded' });
  await p.waitForSelector('#t-name-box', { timeout: 120000 }); await p.waitForTimeout(5000);
  const jump = async (ref) => { await p.click('#t-name-box'); await p.keyboard.press('Control+A'); await p.keyboard.type(ref); await p.keyboard.press('Enter'); await p.waitForTimeout(700); };
  const fb = async () => (await p.locator('#t-formula-bar-input').innerText().catch(() => '')).trim();
  await p.locator('.docs-sheet-tab-name').filter({ hasText: /^Summary$/ }).first().click(); await p.waitForTimeout(2000);
  await jump('M1'); const m1 = await fb();
  if (/^CY2025 period: Yes/.test(m1)) {
    await p.keyboard.press('Control+Shift+ArrowRight'); await p.waitForTimeout(500);
    await p.getByRole('menuitem', { name: /^Edit$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Delete/ }).first().hover(); await p.waitForTimeout(600);
    const d = p.getByRole('menuitem', { name: /^Columns? [A-Z]+/ }).first(); console.log('deleting', (await d.innerText()).replace(/\s+/g, ' ')); await d.click(); await p.waitForTimeout(1500);
    await jump('L1'); await p.keyboard.press('Control+Shift+ArrowRight'); // nothing to the right now
  } else if (m1) { console.log('M1 unexpected:', m1); await ctx.close(); return; }
  await jump('M1');
  if (await p.$('.modal-dialog-bg')) { await p.keyboard.press('Escape'); await jump('L1');
    await p.getByRole('menuitem', { name: /^Insert$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Columns/ }).first().hover(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /Insert 1 column right/ }).first().click(); await p.waitForTimeout(1200); await jump('M1'); }
  execFileSync('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value ([IO.File]::ReadAllText('${path.join(__dirname, 'Summary_block.tsv')}', [Text.Encoding]::UTF8))`]);
  await p.keyboard.press('Control+V'); await p.waitForTimeout(4000);
  await jump('M1'); console.log('M1:', await fb()); await jump('S8'); console.log('S8:', (await fb()).slice(0, 60));
  await p.waitForTimeout(3000); await ctx.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
