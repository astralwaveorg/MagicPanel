import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
await page.goto('http://127.0.0.1:7101/admin/unlock', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(600);
const rows = await page.evaluate(async () => {
  const CHECKS = [
    ['gemini','https://gemini.google.com/favicon.ico'],
    ['chatgpt','https://chatgpt.com/favicon.ico'],
    ['claude','https://claude.ai/favicon.ico'],
    ['netflix','https://www.netflix.com/favicon.ico'],
    ['disney','https://www.disneyplus.com/favicon.ico'],
    ['youtube','https://www.youtube.com/favicon.ico'],
    ['spotify','https://www.spotify.com/favicon.ico'],
    ['tiktok','https://www.tiktok.com/favicon.ico'],
    ['reddit','https://www.reddit.com/favicon.ico'],
    ['wikipedia','https://zh.wikipedia.org/favicon.ico'],
  ];
  const out = [];
  for (const [id, url] of CHECKS) {
    const t0 = performance.now();
    let state = 'unreachable', reason = '';
    try {
      await Promise.race([
        fetch(url, { mode: 'no-cors', redirect: 'follow', cache: 'no-store' }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 8000)),
      ]);
      state = 'reachable';
    } catch (e) {
      reason = String(e.message || e).slice(0, 90);
      state = /NotSameOrigin|ERR_BLOCKED_BY_RESPONSE/i.test(reason) ? 'reachable(redirect)' : 'unreachable';
    }
    out.push({ id, state, ms: Math.round(performance.now() - t0), reason: reason.slice(0, 70) });
  }
  return out;
});
for (const r of rows) console.log(`${r.id.padEnd(12)} ${r.state.padEnd(20)} ${String(r.ms).padStart(6)}ms  ${r.reason}`);
await browser.close();
