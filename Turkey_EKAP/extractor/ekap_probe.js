const { attach, post } = require('./ekap_lib');
(async () => {
  const { page } = await attach();
  const r = await post(page, '/Ihale/GetListByParameters', {
    paginationSkip: 0, paginationTake: 3, orderBy: 'ihaleTarihi', siralamaTipi: 'desc', yasaKapsami4734List: [1], ihaleTuruIdList: [1],
    okasBransKodList: ['33184500'], ihaleTarihSaatBaslangic: '2025-01-01T00:00:00.000Z', ihaleTarihSaatBitis: '2025-12-31T23:59:59.999Z' });
  console.log('status', r.status, r.text || '');
  if (r.json) { console.log('totalCount', r.json.totalCount); (r.json.list || []).forEach(x => console.log(' ', x.ikn, '|', (x.ihaleAdi||'').slice(0,80), '|', x.id)); }
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
