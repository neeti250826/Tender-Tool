// Download NUPCO item lists listed in itemlist_targets.json into ksa/items/
const { chromium } = require('playwright-core');
const fs = require('fs'); const path = require('path');
(async () => {
  const t = JSON.parse(fs.readFileSync(path.join(__dirname,'itemlist_targets.json'),'utf8'));
  const b = await chromium.launch({channel:'chrome', headless:true}); const ctx = await b.newContext();
  for (const [id,u] of t) {
    const out = path.join(__dirname,'items', id.replace('/','_')+'.'+u.split('.').pop().toLowerCase());
    if (fs.existsSync(out)) continue;
    try { const r = await ctx.request.get(encodeURI(decodeURI(u)),{timeout:120000}); fs.writeFileSync(out, await r.body()); console.log(id, r.status()); }
    catch(e){ console.log(id,'ERR',e.message.slice(0,80)); }
  }
  await b.close();
})();
