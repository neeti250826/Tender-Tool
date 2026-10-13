// Count EKAP tenders per OKAS code and year. Usage: node ekap_count.js 33141121 33184500 ...
const { attach, post } = require('./ekap_lib');
(async () => {
  const { page } = await attach();
  for (const code of process.argv.slice(2)) for (const y of [2024, 2025, 2026]) {
    const r = await post(page, '/Ihale/GetListByParameters', { paginationSkip: 0, paginationTake: 1, orderBy: 'ihaleTarihi', siralamaTipi: 'desc',
      yasaKapsami4734List: [1], ihaleTuruIdList: [1], okasBransKodList: [code],
      ihaleTarihSaatBaslangic: `${y}-01-01T00:00:00.000Z`, ihaleTarihSaatBitis: `${y}-12-31T23:59:59.999Z` });
    console.log(code, y, r.status, r.json ? r.json.totalCount : r.text);
  }
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
