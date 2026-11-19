// 验证双路径探测：重定向站点（gemini）能被 iframe 路径判为可达
import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
await page.goto('http://127.0.0.1:7101/admin/unlock', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(800);
const t0 = Date.now();
await page.getByRole('button', { name: '检测当前网络' }).click();
await page.waitForTimeout(40000);
const left = await page.locator('.unlock-col').first().innerText();
console.log('当前网络列:', left.replace(/\n+/g, ' | '));
// 逐项看 Gemini 的状态
const gemini = await page.evaluate(() => {
  const rows = [...document.querySelectorAll('table tbody tr')];
  const r = rows.find(x => x.innerText.includes('Gemini'));
  return r ? r.innerText.replace(/\n+/g, ' | ') : '未找到';
});
console.log('Gemini 行:', gemini);
console.log('耗时', Date.now() - t0, 'ms');
await page.screenshot({ path: '/tmp/mp-shots/unlock-dual-path.png' });
await browser.close();
