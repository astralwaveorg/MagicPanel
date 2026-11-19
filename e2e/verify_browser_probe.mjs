// 验证浏览器端「当前网络」探测：CSP 放宽后是否真的发出请求并拿到可达/不可达
import { chromium } from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e).slice(0, 100)));
await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
await page.goto('http://127.0.0.1:7101/admin/unlock', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(800);

// 在页面上下文里跑一次真实探测（与页面同源、同样 CSP）
const result = await page.evaluate(async () => {
  const urls = [
    ['gemini', 'https://gemini.google.com/'],
    ['chatgpt', 'https://chatgpt.com/'],
    ['netflix', 'https://www.netflix.com/'],
    ['wikipedia', 'https://zh.wikipedia.org/'],
  ];
  const out = [];
  for (const [id, url] of urls) {
    const t0 = performance.now();
    let state = 'unreachable';
    try {
      await Promise.race([
        fetch(url, { mode: 'no-cors', redirect: 'follow', cache: 'no-store' }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 8000)),
      ]);
      state = 'reachable';
    } catch (e) { state = 'err:' + String(e).slice(0, 40); }
    out.push({ id, state, ms: Math.round(performance.now() - t0) });
  }
  return out;
});
console.log(JSON.stringify(result, null, 1));
console.log('pageerror:', errors.length);
await browser.close();
