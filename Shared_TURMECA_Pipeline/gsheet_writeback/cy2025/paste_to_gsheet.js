// Paste the CY2025 columns (cy2025/<tab>.tsv) into the live Google Sheet, one tab at a time, via the signed-in
// Chrome profile (headed - clipboard paste needs a real window). Usage: node paste_to_gsheet.js [tab filter]
const { chromium } = require('playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path');
const SHEET = 'https://docs.google.com/spreadsheets/d/<MASTER_SHEET_ID>/edit';
// tab name -> [tsv file, first new column letter]
const TABS = {
  'KSA - NUPCO': ['KSA_-_NUPCO.tsv', 'BC'], 'Turkey - EKAP': ['Turkey_-_EKAP.tsv', 'BG'], 'Pakistan - KP MCC': ['Pakistan_-_KP_MCC.tsv', 'BC'],
  'Pakistan - KP DGHS': ['Pakistan_-_KP_DGHS.tsv', 'BC'], 'Pakistan - Federal EPMS': ['Pakistan_-_Federal_EPMS.tsv', 'BC'],
  'Kuwait - CAPT': ['Kuwait_-_CAPT.tsv', 'BC'], 'UAE - Dubai eSupply': ['UAE_-_Dubai_eSupply.tsv', 'BC'],
};
const RESET = process.argv.includes('--reset');
const only = process.argv.filter(a => !a.startsWith('--'))[2];

function setClipboard(file) {
  execFileSync('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value ([IO.File]::ReadAllText('${file.replace(/'/g, "''")}', [Text.Encoding]::UTF8))`]);
}

(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', { channel: 'chrome', headless: false, viewport: { width: 1500, height: 900 } });
  const p = ctx.pages()[0] || await ctx.newPage();
  await p.goto(SHEET, { timeout: 120000, waitUntil: 'domcontentloaded' });
  await p.waitForSelector('#t-name-box', { timeout: 120000 });
  await p.waitForTimeout(5000);
  const jump = async (ref) => { await p.click('#t-name-box'); await p.keyboard.press('Control+A'); await p.keyboard.type(ref); await p.keyboard.press('Enter'); await p.waitForTimeout(800); };
  const formulaBar = async () => (await p.locator('#t-formula-bar-input').innerText().catch(() => '')).trim();
  const colNum = c => [...c].reduce((a, ch) => a * 26 + ch.charCodeAt(0) - 64, 0);
  const colStr = n => { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - 1 - m) / 26; } return s; };
  const closeModal = async () => { if (await p.$('.modal-dialog-bg')) { await p.keyboard.press('Escape'); await p.waitForTimeout(500); } };
  // insert n empty columns so that `col` becomes the first new column (select the n columns left of it, Insert > Columns > right)
  const ensureColumns = async (col, n) => {
    const last = colNum(col) - 1;
    await jump(`${colStr(last - n + 1)}1:${colStr(last)}1`);
    await p.getByRole('menuitem', { name: /^Insert$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Columns/ }).first().hover(); await p.waitForTimeout(600);
    const item = p.getByRole('menuitem', { name: new RegExp(`Insert ${n} columns? right`) }).first();
    await item.click(); await p.waitForTimeout(1500);
    await closeModal();
  };
  for (const [tab, [file, col]] of Object.entries(TABS)) {
    if (only && !tab.includes(only)) continue;
    const tsv = fs.readFileSync(path.join(__dirname, file), 'utf8');
    const nrows = tsv.trim().split('\n').length;
    // activate the tab
    const t = p.locator('.docs-sheet-tab-name', { hasText: tab }).filter({ hasText: new RegExp('^' + tab.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') }).first();
    await t.scrollIntoViewIfNeeded(); await t.click(); await p.waitForTimeout(2500);
    if (RESET) {                                   // delete every column from `col` to the grid end (other editor's block + ours)
      await jump(`${col}1`);
      if (!(await p.$('.modal-dialog-bg'))) {
        await p.keyboard.press('Control+Shift+ArrowRight'); await p.waitForTimeout(500);
        await p.getByRole('menuitem', { name: /^Edit$/ }).first().click(); await p.waitForTimeout(600);
        await p.getByRole('menuitem', { name: /^Delete/ }).first().hover(); await p.waitForTimeout(600);
        const del = p.getByRole('menuitem', { name: /^Columns? [A-Z]+/ }).first();
        const label = await del.innerText().catch(() => '?');
        await del.click(); await p.waitForTimeout(2500);
        console.log(`${tab}: deleted ${label.replace(/\s+/g, ' ')}`);
      } else await closeModal();
    }
    await jump(`${col}1`);
    if (await p.$('.modal-dialog-bg')) {          // column does not exist yet -> insert the 11 new columns
      await closeModal(); await ensureColumns(col, 11); await jump(`${col}1`);
    }
    const before = await formulaBar();
    if (before || await p.$('.modal-dialog-bg')) { console.log(`SKIP ${tab}: ${col}1 holds "${before.slice(0, 40)}" or a dialog is open`); await closeModal(); continue; }
    setClipboard(path.join(__dirname, file));
    await p.keyboard.press('Control+V');
    // wait for the paste to land and the doc to save
    await p.waitForTimeout(Math.min(60000, 3000 + nrows * 4));
    await p.waitForFunction(() => !/Saving/i.test(document.body.innerText.slice(0, 20000)), { timeout: 180000 }).catch(() => {});
    await jump(`${col}1`); const h = await formulaBar();
    await jump(`${col}${nrows}`); const last = await formulaBar();
    console.log(`${tab}: pasted ${nrows} rows at ${col}1 | header="${h}" | last-row first cell="${last}"`);
    await p.keyboard.press('Escape');
  }
  // README note (two rows: label | text) appended after the last filled row of column A
  if (!only || 'README'.includes(only)) {
    const t = p.locator('.docs-sheet-tab-name').filter({ hasText: /^README$/ }).first();
    await t.scrollIntoViewIfNeeded(); await t.click(); await p.waitForTimeout(2000);
    await jump('A1'); await p.keyboard.press('Control+ArrowDown'); await p.waitForTimeout(500);
    const lastTxt = await formulaBar();
    if (!/CY2025/.test(lastTxt)) {
      await p.keyboard.press('ArrowDown'); await p.waitForTimeout(300);
      setClipboard(path.join(__dirname, 'README_note.tsv'));
      await p.keyboard.press('Control+V'); await p.waitForTimeout(3000);
      console.log('README: note appended below "' + lastTxt.slice(0, 40) + '"');
    } else console.log('README: note already present');
  }
  await p.waitForTimeout(3000);
  await ctx.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
