// 线上验证：生产域名下浏览器端探测（无需登录，门户页同源 CSP）
import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('https://magichub.top:8443/', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(400);
const out = await page.evaluate(async () => {
  const res = [];
  for (const [id, url] of [['gemini','https://gemini.google.com/'],
                           ['chatgpt','https://chatgpt.com/'],
                           ['netflix','https://www.netflix.com/'],
                           ['wiki','https://zh.wikipedia.org/']]) {
    const t0 = performance.now();
    let s = 'ok';
    try {
      await Promise.race([fetch(url, { mode: 'no-cors', redirect: 'follow', cache: 'no-store' }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 12000))]);
    } catch (e) { s = String(e.message).slice(0, 40); }
    res.push({ id, s, ms: Math.round(performance.now() - t0) });
  }
  return res;
});
for (const r of out) console.log(`  ${r.id.padEnd(10)} ${r.s.padEnd(22)} ${r.ms}ms`);
await browser.close();
