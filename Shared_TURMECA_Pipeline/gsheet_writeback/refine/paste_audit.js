// Write the category-audit results to the working sheet: OU/Sub-OU/Category, Included/Exclusion Reason, Company, Family,
// the 8 mapping/identification columns, the recomputed Summary blocks and the README notes.  Usage: node paste_audit.js [tab filter]
const { chromium } = require('playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'); const path = require('path');
const SHEET = 'https://docs.google.com/spreadsheets/d/<WORKING_SHEET_ID>/edit';
const stats = JSON.parse(fs.readFileSync(path.join(__dirname, 'stats.json'), 'utf8'));
const only = process.argv[2];
const colStr = n => { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - 1 - m) / 26; } return s; };
const safe = t => t.replace(/[^\w-]+/g, '_');
const read = f => fs.readFileSync(path.join(__dirname, f), 'utf8').replace(/\r/g, '').replace(/\n$/, '');
const body = f => read(f).split('\n').slice(1).join('\n');
function clip(text) {
  const tmp = path.join(__dirname, '_clip.tsv'); fs.writeFileSync(tmp, text, 'utf8');
  execFileSync('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value ([IO.File]::ReadAllText('${tmp.replace(/'/g, "''")}', [Text.Encoding]::UTF8))`]);
}

(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', { channel: 'chrome', headless: false, viewport: { width: 1500, height: 900 } });
  const p = ctx.pages()[0] || await ctx.newPage();
  await p.goto(SHEET, { timeout: 120000, waitUntil: 'domcontentloaded' });
  await p.waitForSelector('#t-name-box', { timeout: 120000 }); await p.waitForTimeout(5000);
  const jump = async ref => { await p.click('#t-name-box'); await p.keyboard.press('Control+A'); await p.keyboard.type(ref); await p.keyboard.press('Enter'); await p.waitForTimeout(800); };
  const fbar = async () => (await p.locator('#t-formula-bar-input').innerText().catch(() => '')).trim();
  const modal = async () => !!(await p.$('.modal-dialog-bg'));
  const closeModal = async () => { if (await modal()) { await p.keyboard.press('Escape'); await p.waitForTimeout(500); } };
  const saved = async ms => { await p.waitForTimeout(ms); await p.waitForFunction(() => !/Saving/i.test(document.body.innerText.slice(0, 20000)), { timeout: 180000 }).catch(() => {}); };
  const paste = async (ref, text, n) => { clip(text); await jump(ref); await p.keyboard.press('Control+V'); await saved(Math.min(60000, 2500 + n * 3)); };
  const tab = async name => { const t = p.locator('.docs-sheet-tab-name').filter({ hasText: new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') }).first(); await t.scrollIntoViewIfNeeded(); await t.click(); await p.waitForTimeout(2500); };
  const insertCols = async (firstNew, n) => {
    await jump(`${colStr(firstNew - n)}1:${colStr(firstNew - 1)}1`);
    await p.getByRole('menuitem', { name: /^Insert$/ }).first().click(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: /^Columns/ }).first().hover(); await p.waitForTimeout(600);
    await p.getByRole('menuitem', { name: new RegExp(`Insert ${n} columns? right`) }).first().click(); await p.waitForTimeout(1500);
    await closeModal();
  };
  const head = async (col, want) => { await jump(`${colStr(col)}1`); const v = await fbar(); return v === want ? null : v; };

  for (const [name, s] of Object.entries(stats)) {
    if (only && !name.includes(only)) continue;
    await tab(name);
    const bad = [];
    for (const [c, w] of [[s.ou_col, 'OU'], [s.ou_col + 2, 'Device Category'], [s.incl_col, 'Included/Review/Excluded'], [s.incl_col + 1, 'Exclusion Reason'],
      [s.company_col, 'Company'], [s.family_col, 'Family Name'], [s.last_col + 1, 'Expected Company']]) { const v = await head(c, w); if (v !== null) bad.push(`${colStr(c)}1="${v}" (want ${w})`); }
    if (bad.length) { console.log(`SKIP ${name}: ${bad.join('; ')}`); continue; }
    const b = safe(name), n = s.rows;
    await paste(`${colStr(s.ou_col)}2`, read(`${b}__cat.tsv`), n);
    await paste(`${colStr(s.incl_col)}2`, read(`${b}__incl.tsv`), n);
    await paste(`${colStr(s.company_col)}2`, body(`${b}__company.tsv`), n);
    await paste(`${colStr(s.family_col)}2`, body(`${b}__family.tsv`), n);
    const first = s.last_col + 1;                     // 'Expected Company'
    if ((s.grid_width || 0) < first + 7) { await insertCols(first + 5, first + 7 - s.grid_width); await p.waitForTimeout(1500); }
    await jump(`${colStr(first + 5)}1`); const occ = await fbar();
    if (occ && occ !== 'Identified Manufacturer (incl. outside taxonomy)') { console.log(`SKIP new cols ${name}: ${colStr(first + 5)}1="${occ}"`); continue; }
    await paste(`${colStr(first)}1`, read(`${b}__new.tsv`), n);
    const chk = [];
    for (const ref of [`${colStr(s.ou_col + 2)}${n + 1}`, `${colStr(s.incl_col)}${n + 1}`, `${colStr(s.company_col)}${n + 1}`, `${colStr(first + 3)}${n + 1}`, `${colStr(first + 7)}1`, `${colStr(first + 7)}${n + 1}`]) { await jump(ref); chk.push(`${ref}="${(await fbar()).slice(0, 38)}"`); }
    console.log(`${name}: ${chk.join(' | ')}`);
    await p.keyboard.press('Escape');
  }
  if (!only || 'Summary'.includes(only)) {
    await tab('Summary');
    const a1 = await head(1, 'Tab'), m1 = await head(13, 'Active in 2025: Yes'), a10 = await head(1, 'Tab');
    await jump('A10'); const t10 = await fbar();
    if (a1 === null && m1 === null && t10 === 'Tab') {
      await paste('A1', read('Summary_top.tsv'), 10);
      await paste('A10', read('Summary_ou.tsv'), 50);
      await jump('D2'); console.log('Summary D2 =', await fbar()); await jump('A49'); console.log('Summary A49 =', await fbar());
    } else console.log('SKIP Summary: unexpected layout', a1, m1, t10);
  }
  if (!only || 'README'.includes(only)) {
    await tab('README');
    await jump('A1'); await p.keyboard.press('Control+ArrowDown'); await p.waitForTimeout(500);
    const last = await fbar();
    if (!/Category audit|Identification columns/.test(last)) {
      await p.keyboard.press('ArrowDown'); await p.waitForTimeout(300);
      clip(read('README_audit_note.tsv')); await p.keyboard.press('Control+V'); await saved(3000);
      console.log('README: audit notes appended below "' + last.slice(0, 40) + '"');
    } else console.log('README: audit notes already present');
  }
  await p.waitForTimeout(3000);
  await ctx.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
