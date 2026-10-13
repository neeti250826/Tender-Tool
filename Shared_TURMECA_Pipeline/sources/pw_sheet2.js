const { chromium } = require('playwright-core');
const fs = require('fs');
(async () => {
  const ctx = await chromium.launchPersistentContext('<LOCAL_APPDATA>/ms-playwright/pw-google', {channel:'chrome', headless:false});
  const r = await ctx.request.get('https://docs.google.com/spreadsheets/d/<TAXONOMY_SHEET_ID>/export?format=xlsx');
  console.log(r.status(), r.headers()['content-type']);
  fs.writeFileSync(process.argv[2], await r.body());
  await ctx.close();
})();
