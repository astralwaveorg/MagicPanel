// 全页面截图验证：登录后遍历全部 16 个路由，每页截图存 /tmp/mp-shots/。
// 同时收集每页的 console 错误与未渲染空白（body 文本过短）作为"页面健康"证据。
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = 'http://127.0.0.1:7101';
const OUT = '/tmp/mp-shots';
mkdirSync(OUT, { recursive: true });

const PAGES = [
  ['login', '/admin/login'],
  ['overview', '/admin'],
  ['unlock', '/admin/unlock'],
  ['groups', '/admin/groups'],
  ['rules', '/admin/rules'],
  ['sources', '/admin/sources'],
  ['rule-providers', '/admin/rule-providers'],
  ['base-config', '/admin/artifact'],
  ['base-config-targets', '/admin/artifact?tab=targets'],
  ['base-config-artifact', '/admin/artifact?tab=artifact'],
  ['devices', '/admin/devices'],
  ['builds', '/admin/builds'],
  ['builds-auto', '/admin/builds?tab=auto'],
  ['snippets', '/admin/snippets'],
  ['deps', '/admin/dependencies'],
  ['audit', '/admin/audit'],
  ['settings', '/admin/settings'],
  ['portal', '/'],
];

const results = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(`${page.url()} :: ${msg.text().slice(0, 160)}`);
});
page.on('pageerror', (err) => consoleErrors.push(`${page.url()} :: PAGEERROR ${String(err).slice(0, 160)}`));

// 未登录先截登录页，再登录
await page.goto(`${BASE}/admin/login`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/login.png` });

await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});

for (const [name, path] of PAGES) {
  if (name === 'login') continue;
  try {
    await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1100);            // 等接口渲染（Element Plus 过渡）
    const text = (await page.locator('body').innerText()).trim();
    const blank = text.length < 40;
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
    results.push({ name, path, textLen: text.length, blank,
                   title: await page.title() });
  } catch (err) {
    results.push({ name, path, error: String(err).slice(0, 160) });
    await page.screenshot({ path: `${OUT}/${name}-ERROR.png` }).catch(() => {});
  }
}

writeFileSync(`${OUT}/results.json`, JSON.stringify({ results, consoleErrors }, null, 1));
await browser.close();
console.log(JSON.stringify({ results, consoleErrors: consoleErrors.slice(0, 12) }, null, 1));
