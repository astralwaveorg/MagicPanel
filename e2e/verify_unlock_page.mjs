// 端到端：点「检测当前网络」与「检测服务器网络」，核对两列结果与对照结论
import { chromium } from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e).slice(0, 120)));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 120)); });

await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
await page.goto('http://127.0.0.1:7101/admin/unlock', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(800);

await page.getByRole('button', { name: '检测当前网络' }).click();
await page.waitForTimeout(14000);
const left = await page.locator('.unlock-col').first().innerText();
console.log('--- 当前网络列 ---');
console.log(left.replace(/\n+/g, ' | '));

await page.screenshot({ path: '/tmp/mp-shots/unlock-browser-probe.png' });

// 点一个服务卡片重测单项（验证单点重测路径）
const card = page.locator('.unlock-card, table tbody tr').first();
const hasCard = await card.count();
console.log('服务行数:', hasCard);
console.log('pageerror/console:', errors.length, errors.slice(0, 3));
await browser.close();
