// Write the refined Company / Family columns and the 5 new mapping columns into the working Google Sheet
// (Working_ON_TURMECA_Master_Mapped_Data) by clipboard paste, then append README notes.
// Usage: node paste_refined.js [tab filter]
const { chromium } = require('playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path');
const SHEET = 'https://docs.google.com/spreadsheets/d/<WORKING_SHEET_ID>/edit';
const stats = JSON.parse(fs.readFileSync(path.join(__dirname, 'stats.json'), 'utf8'));
const only = process.argv[2];
const colStr = n => { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - 1 - m) / 26; } return s; };
const safe = t => t.replace(/[^\w-]+/g, '_');

function clip(text) {
  const tmp = path.join(__dirname, '_clip.tsv'); fs.writeFileSync(tmp, text, 'utf8');
  execFileSync('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value ([IO.File]::ReadAllText('${tmp.replace(/'/g, "''")}', [Text.Encoding]::UTF8))`]);
}
const body = f => fs.readFileSync(f, 'utf8').replace(/\r/g, '').split('\n').slice(1).filter((l, i, a) => i < a.length - 1 || l).join('\n');

(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', { channel: 'chrome', headless: false, viewport: { width: 1500, height: 900 } });
  const p = ctx.pages()[0] || await ctx.newPage();
  await p.goto(SHEET, { timeout: 120000, waitUntil: 'domcontentloaded' });
  await p.waitForSelector('#t-name-box', { timeout: 120000 }); await p.waitForTimeout(5000);
  const jump = async ref => { await p.click('#t-name-box'); await p.keyboard.press('Control+A'); await p.keyboard.type(ref); await p.keyboard.press('Enter'); await p.waitForTimeout(800); };
  const fbar = async () => (await p.locator('#t-formula-bar-input').innerText().catch(() => '')).trim();
  const modal = async () => !!(await p.$('.modal-dialog-bg'));
  const closeModal = async () => { if (await modal()) { await p.keyboard.press('Escape'); await p.waitForTimeout(500); } };
  const saved = async (ms) => { await p.waitForTimeout(ms); await p.waitForFunction(() => !/Saving/i.test(document.body.innerText.slice(0, 20000)), { timeout: 180000 }).catch(() => {}); };
  const paste = async (ref, text, nrows) => { clip(text); await jump(ref); await p.keyboard.press('Control+V'); await saved(Math.min(60000, 2500 + nrows * 3)); };
  const insertCols = async (firstNew, n) => {             // make `firstNew` exist: select n columns left of it, Insert n columns right
    await jump(`${colStr(firstNew - n)}1:${colStr(firstNew - 1)}1`);
    await p.getByRole('menuitem', { name: /^Insert$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Columns/ }).first().hover(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: new RegExp(`Insert ${n} columns? right`) }).first().click(); await p.waitForTimeout(1500);
    await closeModal();
  };

  for (const [tab, s] of Object.entries(stats)) {
    if (only && !tab.includes(only)) continue;
    const t = p.locator('.docs-sheet-tab-name').filter({ hasText: new RegExp('^' + tab.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') }).first();
    await t.scrollIntoViewIfNeeded(); await t.click(); await p.waitForTimeout(2500);
    const C = colStr(s.company_col), F = colStr(s.family_col), N = s.last_col + 1, NC = colStr(N);
    // guard: headers where we expect them
    await jump(`${C}1`); const hc = await fbar(); await jump(`${F}1`); const hf = await fbar();
    if (hc !== 'Company' || hf !== 'Family Name') { console.log(`SKIP ${tab}: ${C}1="${hc}" ${F}1="${hf}"`); continue; }
    // company + family (data rows only, from row 2)
    const base = path.join(__dirname, safe(tab));
    await paste(`${C}2`, body(base + '__company.tsv'), s.rows);
    await paste(`${F}2`, body(base + '__family.tsv'), s.rows);
    // 5 new columns
    await jump(`${NC}1`);
    if (await modal()) { await closeModal(); await insertCols(N, 5); await jump(`${NC}1`); }
    const before = await fbar();
    if (before && before !== 'Expected Company') { console.log(`SKIP new cols on ${tab}: ${NC}1 holds "${before}"`); continue; }
    await paste(`${NC}1`, fs.readFileSync(base + '__new.tsv', 'utf8').replace(/\r/g, '').replace(/\n$/, ''), s.rows);
    // verify
    const chk = [];
    for (const ref of [`${C}2`, `${C}${s.rows + 1}`, `${F}${s.rows + 1}`, `${NC}1`, `${colStr(N + 2)}${s.rows + 1}`, `${colStr(N + 4)}1`]) { await jump(ref); chk.push(`${ref}="${(await fbar()).slice(0, 40)}"`); }
    console.log(`${tab}: ${chk.join(' | ')}`);
    await p.keyboard.press('Escape');
  }
  if (!only || 'README'.includes(only)) {
    const t = p.locator('.docs-sheet-tab-name').filter({ hasText: /^README$/ }).first();
    await t.scrollIntoViewIfNeeded(); await t.click(); await p.waitForTimeout(2000);
    await jump('A1'); await p.keyboard.press('Control+ArrowDown'); await p.waitForTimeout(500);
    const last = await fbar();
    if (!/Mapping refinement/.test(last)) {
      await p.keyboard.press('ArrowDown'); await p.waitForTimeout(300);
      clip(fs.readFileSync(path.join(__dirname, 'README_mapping_note.tsv'), 'utf8').replace(/\r/g, '').replace(/\n$/, ''));
      await p.keyboard.press('Control+V'); await saved(3000);
      console.log('README: notes appended below "' + last.slice(0, 40) + '"');
    } else console.log('README: notes already present');
  }
  await p.waitForTimeout(3000);
  await ctx.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
