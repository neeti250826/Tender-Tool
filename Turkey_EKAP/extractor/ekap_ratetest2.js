// Rate test for the DETAIL endpoint: N calls at pace P ms over ids from lists/*.json.
const fs = require('fs'); const path = require('path'); const crypto = require('crypto');
const { attach } = require('./ekap_lib');
(async () => {
  const [N, P] = process.argv.slice(2).map(Number);
  const ids = [];
  for (const f of fs.readdirSync('lists')) for (const x of JSON.parse(fs.readFileSync(path.join('lists', f))).list) if (ids.length < N) ids.push(x.id);
  const { page } = await attach(); const R8 = 'Qm2LtXR0aByP69vZNKef4wMJ';
  const mk = () => { const guid = crypto.randomUUID(), iv = crypto.randomBytes(16);
    const enc = v => { const c = crypto.createCipheriv('aes-192-cbc', Buffer.from(R8), iv); return Buffer.concat([c.update(v), c.final()]).toString('base64'); };
    return { 'Accept': 'application/json', 'Content-Type': 'application/json', 'api-version': 'v1', 'X-Custom-Request-Ts': enc(String(Date.now())),
      'X-Custom-Request-Siv': iv.toString('base64'), 'X-Custom-Request-R8id': enc(guid), 'X-Custom-Request-Guid': guid }; };
  const out = [];
  for (const id of ids) {
    const s = await page.evaluate(async ({ h, id }) => (await fetch('/b_ihalearama/api/IhaleDetay/GetByIhaleIdIhaleDetay', { method: 'POST', headers: h, credentials: 'include', body: JSON.stringify({ ihaleId: id }) })).status, { h: mk(), id });
    out.push(s); await new Promise(r => setTimeout(r, P));
  }
  console.log(out.join(' '));
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
