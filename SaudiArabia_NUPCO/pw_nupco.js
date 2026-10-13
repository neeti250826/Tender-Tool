const { chromium } = require('playwright-core');
const fs = require('fs'); const SP = process.argv[2];
(async () => {
  const list = JSON.parse(fs.readFileSync(SP+'/nupco_list.json','utf8'));
  const hrefs = [...new Set(list.map(x=>x.href))];
  const b = await chromium.launch({channel:'chrome', headless:false}); const ctx = await b.newContext();
  const pages = await Promise.all([0,1,2,3].map(()=>ctx.newPage())); const out=[]; let i=0;
  await Promise.all(pages.map(async p=>{ while(i<hrefs.length){ const h=hrefs[i++];
    try{ await p.goto(h,{timeout:60000,waitUntil:'domcontentloaded'}); await p.waitForTimeout(1500);
      const r = await p.evaluate(()=>({title:document.querySelector('h1')?.innerText||document.title, text:(document.querySelector('main')||document.body).innerText.slice(0,4000),
        pdfs:[...document.querySelectorAll('a[href$=".pdf"],a[href*=".xls"]')].map(a=>({t:a.innerText.trim(),h:a.href}))}));
      out.push({href:h,...r}); } catch(e){ out.push({href:h,err:e.message.slice(0,100)}); } } }));
  fs.writeFileSync(SP+'/nupco_pages.json', JSON.stringify(out,null,1)); console.log(out.length, out.filter(x=>x.err).length);
  await b.close();
})();
