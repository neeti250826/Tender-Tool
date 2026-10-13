// One list call; print status + all response headers (looking for rate-limit / retry-after info).
const { attach } = require('./ekap_lib');
const crypto = require('crypto');
(async () => {
  const { page } = await attach();
  const R8 = 'Qm2LtXR0aByP69vZNKef4wMJ', guid = crypto.randomUUID(), iv = crypto.randomBytes(16);
  const enc = v => { const c = crypto.createCipheriv('aes-192-cbc', Buffer.from(R8), iv); return Buffer.concat([c.update(v), c.final()]).toString('base64'); };
  const headers = { 'Accept': 'application/json', 'Content-Type': 'application/json', 'api-version': 'v1',
    'X-Custom-Request-Ts': enc(String(Date.now())), 'X-Custom-Request-Siv': iv.toString('base64'), 'X-Custom-Request-R8id': enc(guid), 'X-Custom-Request-Guid': guid };
  const r = await page.evaluate(async (headers) => {
    const x = await fetch('/b_ihalearama/api/Ihale/GetListByParameters', { method: 'POST', headers, credentials: 'include',
      body: JSON.stringify({ paginationSkip: 0, paginationTake: 1, yasaKapsami4734List: [1], ihaleTuruIdList: [1], okasBransKodList: ['33141121'] }) });
    const h = {}; x.headers.forEach((v, k) => h[k] = v);
    return { status: x.status, h, body: (await x.text()).slice(0, 300) };
  }, headers);
  console.log(JSON.stringify(r, null, 1));
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
