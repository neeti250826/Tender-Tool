// EKAP MedTech extraction, run inside the user's verified EKAP tab (Edge, CDP 9222).
//   Stage 1: for every in-scope OKAS code x tender year 2024-2026, page through the tender list
//            -> lists/<code>_<year>.json (skipped when already present = resumable)
//   Stage 2: one detail per unique tender id -> details/<id>.json. Details cached by the earlier
//            IVD pull (<TURKEY_IVD_PROJECT>/outputs/**/raw*details) are copied, not re-fetched.
// Usage: node ekap_extract_medtech.js [lists|details|all]
const fs = require('fs'); const path = require('path');
const { attach, post } = require('./ekap_lib');

const HERE = __dirname;
const LISTS = path.join(HERE, 'lists'), DETAILS = path.join(HERE, 'details');
const OLD_ROOT = '<TURKEY_IVD_PROJECT>/outputs';
const YEARS = [2024, 2025, 2026];
const counts = JSON.parse(fs.readFileSync(path.join(HERE, 'code_counts.json'), 'utf8')); // "code|year" -> n
const REL = JSON.parse(fs.readFileSync(path.join(HERE, 'code_relevance.json'), 'utf8')); // code -> Core|Partial|Catch-all
const TIERS = ['Core', 'Partial', 'Catch-all'];
fs.mkdirSync(LISTS, { recursive: true }); fs.mkdirSync(DETAILS, { recursive: true });

function oldDetailIndex() {
  const idx = {};
  const walk = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p); else if (/details/.test(d) && e.name.endsWith('.json')) idx[e.name.slice(0, -5)] = p; } };
  walk(OLD_ROOT); return idx;
}

async function stageLists(page, tier) {
  const jobs = Object.entries(counts).filter(([k, n]) => n > 0 && REL[k.split('|')[0]] === tier).map(([k]) => k.split('|'));
  for (const [code, year] of jobs) {
    const out = path.join(LISTS, `${code}_${year}.json`);
    if (fs.existsSync(out)) continue;
    const all = []; let skip = 0, total = null;
    while (total === null || skip < total) {
      const r = await post(page, '/Ihale/GetListByParameters', { paginationSkip: skip, paginationTake: 100, orderBy: 'ihaleTarihi', siralamaTipi: 'desc',
        yasaKapsami4734List: [1], ihaleTuruIdList: [1], okasBransKodList: [code],
        ihaleTarihSaatBaslangic: `${year}-01-01T00:00:00.000Z`, ihaleTarihSaatBitis: `${year}-12-31T23:59:59.999Z` });
      if (r.status !== 200 || !r.json) throw new Error(`list ${code} ${year} skip=${skip}: ${r.status} ${r.text || ''}`);
      const items = r.json.list || []; total = r.json.totalCount || 0;
      all.push(...items); skip += items.length;
      if (!items.length) break;
    }
    fs.writeFileSync(out, JSON.stringify({ code, year: +year, total, list: all }));
    console.log(`list ${code} ${year}: ${all.length}/${total}`);
  }
}

async function stageDetails(page, tier) {
  const ids = new Map();
  for (const f of fs.readdirSync(LISTS)) {
    if (REL[f.split('_')[0]] !== tier) continue;
    const d = JSON.parse(fs.readFileSync(path.join(LISTS, f), 'utf8'));
    for (const x of d.list) if (x.id && !ids.has(x.id)) ids.set(x.id, x);
  }
  const old = oldDetailIndex(); let copied = 0, fetched = 0, have = 0, n = 0;
  for (const id of ids.keys()) {
    n++;
    const out = path.join(DETAILS, `${id}.json`);
    if (fs.existsSync(out)) { have++; continue; }
    if (old[id]) { fs.copyFileSync(old[id], out); copied++; continue; }
    const r = await post(page, '/IhaleDetay/GetByIhaleIdIhaleDetay', { ihaleId: id });
    if (r.status !== 200 || !r.json) { console.error(`detail ${id}: ${r.status} ${r.text || ''}`); continue; }
    fs.writeFileSync(out, JSON.stringify(r.json.item || r.json)); fetched++;
    if (fetched % 10 === 0) console.log(`details ${n}/${ids.size}: fetched ${fetched}, copied ${copied}, had ${have}`);
  }
  console.log(`details done: unique ${ids.size}, fetched ${fetched}, copied ${copied}, had ${have}`);
}

(async () => {
  // Tier by tier so the most useful tenders land first: Core lists+details, then Partial, then Catch-all.
  const { page } = await attach();
  for (const tier of TIERS) {
    console.log('== tier', tier);
    await stageLists(page, tier);
    await stageDetails(page, tier);
  }
  process.exit(0);
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
