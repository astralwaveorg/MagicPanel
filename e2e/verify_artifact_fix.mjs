import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', (err) => errors.push(String(err).slice(0, 120)));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 120)); });
await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
// 整页加载 /admin/artifact（复现原 bug 的路径）
await page.goto('http://127.0.0.1:7101/admin/artifact', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1500);
const banner = await page.getByText("页面异常").count();
console.log('错误横幅出现:', banner > 0, '| pageerror/console 数:', errors.length);
for (const e of errors.slice(0, 3)) console.log('  ', e);
await page.screenshot({ path: '/tmp/mp-shots/artifact-after-fix.png' });
await browser.close();
