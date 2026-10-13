// Rate test: N list calls (take=T) at pace P ms, report statuses with timestamps.
const { attach } = require('./ekap_lib');
const lib = require('./ekap_lib');
(async () => {
  const [N, T, P] = process.argv.slice(2).map(Number);
  const { page } = await attach();
  const crypto = require('crypto'); const R8 = 'Qm2LtXR0aByP69vZNKef4wMJ';
  const mk = () => { const guid = crypto.randomUUID(), iv = crypto.randomBytes(16);
    const enc = v => { const c = crypto.createCipheriv('aes-192-cbc', Buffer.from(R8), iv); return Buffer.concat([c.update(v), c.final()]).toString('base64'); };
    return { 'Accept': 'application/json', 'Content-Type': 'application/json', 'api-version': 'v1', 'X-Custom-Request-Ts': enc(String(Date.now())),
      'X-Custom-Request-Siv': iv.toString('base64'), 'X-Custom-Request-R8id': enc(guid), 'X-Custom-Request-Guid': guid }; };
  const out = [];
  for (let i = 0; i < N; i++) {
    const t0 = Date.now();
    const s = await page.evaluate(async ({ h, T, i }) => (await fetch('/b_ihalearama/api/Ihale/GetListByParameters', { method: 'POST', headers: h, credentials: 'include',
      body: JSON.stringify({ paginationSkip: i * T, paginationTake: T, orderBy: 'ihaleTarihi', siralamaTipi: 'desc', yasaKapsami4734List: [1], ihaleTuruIdList: [1], okasBransKodList: ['33141000'],
        ihaleTarihSaatBaslangic: '2024-01-01T00:00:00.000Z', ihaleTarihSaatBitis: '2024-12-31T23:59:59.999Z' }) })).status, { h: mk(), T, i });
    out.push(`${s}:${Date.now() - t0}ms`);
    await new Promise(r => setTimeout(r, P));
  }
  console.log(out.join(' '));
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
