// 验证分流方案在收起态与展开态显示一致
import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:7101/admin/login', { waitUntil: 'domcontentloaded' });
await page.getByRole('textbox', { name: '用户名' }).fill('admin');
await page.getByRole('textbox', { name: '密码' }).fill('Screenshot-2026');
await page.getByRole('button', { name: '登录' }).click();
await page.waitForURL('**/admin', { timeout: 8000 }).catch(() => {});
await page.goto('http://127.0.0.1:7101/admin/groups', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(900);
const collapsed = await page.locator('.vb-select').first().innerText();
await page.locator('.vb-select').first().click();
await page.waitForTimeout(500);
const options = await page.locator('.el-select-dropdown__item').allInnerTexts();
console.log('收起态:', collapsed.replace(/\n+/g, ' | '));
console.log('展开项:', options.map(o => o.replace(/\n+/g, ' | ')).join('  ||  '));
await page.screenshot({ path: '/tmp/mp-shots/variant-dropdown.png' });
await browser.close();
