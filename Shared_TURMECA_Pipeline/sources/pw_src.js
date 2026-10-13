const { chromium } = require('playwright-core');
const fs = require('fs');
const SP = process.argv[2];
(async () => {
  const b = await chromium.launch({channel:'chrome', headless:false});
  const ctx = await b.newContext();
  // CPV via EU Publications Office SPARQL
  const q = `PREFIX skos:<http://www.w3.org/2004/02/skos/core#>
SELECT ?code ?en ?tr WHERE { ?c skos:inScheme <http://data.europa.eu/cpv/cpv> ; skos:notation ?code .
 FILTER(STRSTARTS(STR(?code),"331"))
 OPTIONAL{?c skos:prefLabel ?en FILTER(lang(?en)="en")} OPTIONAL{?c skos:prefLabel ?tr FILTER(lang(?tr)="tr")} }`;
  try {
    const r = await ctx.request.get('https://publications.europa.eu/webapi/rdf/sparql?format=text%2Fcsv&query='+encodeURIComponent(q),{timeout:90000});
    const t = await r.text(); console.log('CPV', r.status(), t.length); fs.writeFileSync(SP+'/cpv331.csv', t);
  } catch(e){ console.log('CPV ERR', e.message.slice(0,200)); }
  // NUPCO list
  const p = await ctx.newPage(); const out=[];
  for (const u of ['https://www.nupco.com/tenders/tenders-list/', ...[2,3,4,5,6].map(i=>`https://www.nupco.com/tenders/tenders-list/${i}/`)]) {
    try { await p.goto(u,{timeout:60000, waitUntil:'domcontentloaded'}); await p.waitForTimeout(2500);
      const items = await p.evaluate(()=>[...document.querySelectorAll('a[href*="/tender/"]')].map(a=>({href:a.href, text:(a.closest('article,li,tr,.tender,div')||a).innerText.replace(/\s+/g,' ').slice(0,400)})));
      console.log('NUPCO', u, items.length); out.push(...items);
    } catch(e){ console.log('NUPCO ERR',u,e.message.slice(0,120)); }
  }
  fs.writeFileSync(SP+'/nupco_list.json', JSON.stringify(out,null,1));
  await b.close();
})();
