// CAPT (Kuwait) winning bids, month by month 2024-01 .. 2026-10, fetched from inside the user's CAPT tab (Edge, CDP 9222).
// Rows: Sr | Meeting Date | Tender No | Subject | Organisation | Winner | Total (KD) | Notes. Rows with data-has-items=True
// link a popup listing item-level winners; popups are fetched for Ministry of Health (and other health) awards.
// Output: kuwait/capt_awards.json, kuwait/capt_popups/<id>.html
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'capt_awards.json'); const POP = path.join(__dirname, 'capt_popups'); fs.mkdirSync(POP, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const HEALTH = /health|medical|hospital|صحة|طبي|مستشفى/i;

function parse(html) {
  const rows = [];
  const re = /<div class="table-row tbody" data-has-items="(\w+)">([\s\S]*?)(?=<div class="table-row tbody"|<\/div>\s*<\/div>\s*<\/div>|$)/g;
  let m;
  while ((m = re.exec(html))) {
    const cells = [...m[2].matchAll(/<div class="table-cell[^"]*">([\s\S]*?)<\/div>/g)].map(c => c[1].replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim());
    const pop = (m[2].match(/winning-bids-popup\/([^"'\s]+)/) || [])[1] || '';
    if (cells.length >= 6) rows.push({ sr: cells[0], date: cells[1], tender_no: cells[2], subject: cells[3], org: cells[4], winner: cells[5], total: cells[6] || '', notes: cells[7] || '', has_items: m[1] === 'True', popup: pop });
  }
  return rows;
}

(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const p = b.contexts()[0].pages().find(x => x.url().includes('capt.gov.kw'));
  const get = async (u) => { for (let a = 0; a < 4; a++) { try { const r = await p.evaluate(async (u) => { const x = await fetch(u, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'include' }); return { s: x.status, t: await x.text() }; }, u); if (r.s === 200) return r.t; console.log('status', r.s, u); } catch (e) { console.log('err', e.message.slice(0, 80)); } await sleep(5000 * (a + 1)); } return ''; };
  const all = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, 'utf8')) : {};
  for (let y = 2024; y <= 2026; y++) for (let mo = 1; mo <= 12; mo++) {
    if (y === 2026 && mo > 10) break;
    const key = `${y}-${String(mo).padStart(2, '0')}`;
    if (all[key]) continue;
    const last = new Date(Date.UTC(y, mo, 0)).getUTCDate();
    const q = `meeting_date_from=${key}-01&meeting_date_to=${key}-${last}&form=date`;
    let page = 1, rows = [], seen = new Set();
    while (page < 200) {
      const h = await get(`/en/tenders/winning-bids/?${q}&page=${page}`);
      const r = parse(h).filter(x => !seen.has(x.sr + '|' + x.tender_no + '|' + x.winner));
      r.forEach(x => seen.add(x.sr + '|' + x.tender_no + '|' + x.winner));
      rows.push(...r);
      if (!r.length || !h.includes(`page=${page + 1}`)) break;
      page++; await sleep(1200);
    }
    all[key] = rows; fs.writeFileSync(OUT, JSON.stringify(all));
    console.log(key, 'rows', rows.length, 'health', rows.filter(x => HEALTH.test(x.org + ' ' + x.subject)).length, 'pages', page);
    await sleep(1500);
  }
  // item popups for health awards
  const pops = new Set(Object.values(all).flat().filter(x => x.popup && HEALTH.test(x.org + ' ' + x.subject)).map(x => x.popup));
  let n = 0;
  for (const id of pops) {
    const f = path.join(POP, id.replace(/[^\w-]/g, '_') + '.html');
    if (fs.existsSync(f)) continue;
    fs.writeFileSync(f, await get(`/en/tenders/winning-bids-popup/${id}`)); n++;
    await sleep(1200);
  }
  console.log('done; health popups fetched', n, 'of', pops.size);
  process.exit(0);
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
