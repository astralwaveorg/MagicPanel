import { expect, test } from '@playwright/test'

const origin = 'http://127.0.0.1:7108'
const subscription = `${origin}/feed/fixture-only/config.yaml?client=fixture`
const selected = `${subscription}&variant=%E5%8A%9E%E5%85%AC+%26+%E6%B5%8B%E8%AF%95`
const data = () => ({
  devices: [{ name: 'fixture-phone', display_name: '示例手机', platform: 'ios', env: 'production',
    engine: 'stash', target_name: 'fixture-ios', note: '', last_pull_at: null,
    subscription_url: subscription, preview_url: '/feed/fixture-only/config.yaml?preview=1&client=fixture',
    variants: ['默认', '办公 & 测试'] }],
  variants: [{ id: 0, name: '默认', note: '' }, { id: 1, name: '办公 & 测试', note: '' },
    { id: 2, name: '未授权方案', note: '' }],
  clients: [], guides: [], rules: [], rule_providers: [], snippets: [],
  release_state: { production: null, testing: null },
})

// 只拦截本地测试服务，任何未声明API或公网请求直接失败。
async function fixture(page, { me = null, send } = {}) {
  const posts = [], previews = [], unexpected = []
  await page.addInitScript(() => {
    window.fixtureCopies = []
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: async text => { window.fixtureCopies.push(text) } },
    })
  })
  await page.route(/^https?:/, async route => {
    const url = new URL(route.request().url())
    if (url.origin !== origin) { unexpected.push(url.origin); return route.abort() }
    if (url.pathname === '/api/v1/setup/status') return route.fulfill({ json: { initialized: true } })
    if (url.pathname === '/api/v1/auth/me') return route.fulfill({
      status: me ? 200 : 401, json: me || { detail: '未登录' },
    })
    if (url.pathname === '/api/v1/portal/data') {
      posts.push(route.request().postDataJSON())
      return send ? send(route, posts.length) : route.fulfill({ json: data() })
    }
    if (url.pathname === '/feed/fixture-only/config.yaml') {
      if (url.searchParams.get('preview') === '1') previews.push(url.href)
      return route.fulfill({ body: 'mode: rule\n', contentType: 'application/yaml',
        headers: url.searchParams.has('preview') ? {} : { 'Content-Disposition': 'attachment' } })
    }
    if (url.pathname.startsWith('/api/')) { unexpected.push(url.pathname); return route.abort() }
    return route.continue()
  })
  await page.goto('/')
  await expect(page.getByLabel('门户 PIN')).toBeVisible()
  return { posts, previews, unexpected }
}

test('历史6位Enter提交与资源动作使用同一授权方案', async ({ page }) => {
  const f = await fixture(page)
  const pin = page.getByLabel('门户 PIN')
  await pin.fill('1234')
  await expect(page.getByRole('button', { name: '进入', exact: true })).toBeEnabled()
  expect(f.posts).toHaveLength(0)
  await pin.fill('123456')
  expect(f.posts).toHaveLength(0)
  await pin.press('Enter')
  await expect(page.getByRole('heading', { name: '订阅中心' })).toBeVisible()
  expect(f.posts).toEqual([{ pin: '123456' }])
  await expect(page.getByRole('button', { name: '未授权方案', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '办公 & 测试', exact: true }).click()
  await page.getByRole('button', { name: '复制地址', exact: true }).click()
  expect(await page.evaluate(() => window.fixtureCopies)).toEqual([selected])
  const download = page.getByRole('link', { name: '下载', exact: true })
  await expect(download).toHaveAttribute('href', selected)
  const downloadEvent = page.waitForEvent('download')
  await download.click()
  const downloaded = await downloadEvent
  expect(downloaded.suggestedFilename()).toBe('fixture-phone@办公 & 测试.yaml')
  const chunks = []
  for await (const chunk of await downloaded.createReadStream()) chunks.push(chunk)
  expect(Buffer.concat(chunks).toString('utf8')).toBe('mode: rule\n')
  const install = page.getByRole('link', { name: '一键导入' })
  // 验证地址但不点击原生scheme，避免真正导入客户端。
  expect(decodeURIComponent((await install.getAttribute('href')).split('?url=')[1])).toBe(selected)
  await page.getByRole('button', { name: '二维码', exact: true }).click()
  await expect(page.getByAltText('订阅二维码')).toHaveAttribute('src', /^data:image\/png;base64,/)
  await expect(page.locator('.pt-modal .pt-url')).toHaveText(selected)
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: 'fixture-phone', exact: true }).click()
  await expect(page.locator('.pt-yaml-code')).toContainText('mode: rule')
  expect(f.previews).toEqual([
    `${origin}/feed/fixture-only/config.yaml?preview=1&client=fixture&variant=%E5%8A%9E%E5%85%AC+%26+%E6%B5%8B%E8%AF%95`,
  ])
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
  await page.reload()
  await expect(page.getByRole('heading', { name: '订阅中心' })).toBeVisible()
  expect(f.posts).toEqual([{ pin: '123456' }, { pin: '123456' }])
  await page.getByRole('button', { name: '退出查看' }).click()
  expect(await page.evaluate(() => sessionStorage.getItem('mp-portal-pin'))).toBe(null)
  await expect(pin).toHaveValue('')
  expect(f.unexpected).toEqual([])
})

test('在途失败保留后来输入，Enter不能造成重复提交', async ({ page }) => {
  let release
  const f = await fixture(page, { send: (route, count) => count === 1
    ? new Promise(resolve => { release = async () => { await route.fulfill({ status: 401, json: { detail: '该次校验失败' } }); resolve() } })
    : route.fulfill({ json: data() }) })
  const pin = page.getByLabel('门户 PIN')
  await pin.fill('1234')
  await pin.press('Enter')
  await expect.poll(() => f.posts.length).toBe(1)
  await pin.fill('654321')
  await pin.press('Enter')
  expect(f.posts).toHaveLength(1)
  await release()
  await expect(page.getByRole('alert')).toContainText('该次校验失败')
  await expect(pin).toHaveValue('654321')
  expect(new URL(page.url()).pathname).toBe('/')
  await pin.press('Enter')
  await expect(page.getByRole('heading', { name: '订阅中心' })).toBeVisible()
  expect(f.posts).toEqual([{ pin: '1234' }, { pin: '654321' }])
  expect(f.unexpected).toEqual([])
})

test('429只按服务端Retry-After禁用提交', async ({ page }) => {
  const f = await fixture(page, { send: route => route.fulfill({
    status: 429, headers: { 'Retry-After': '2' }, json: { detail: '暂时限流' },
  }) })
  const pin = page.getByLabel('门户 PIN')
  await pin.fill('123456')
  await pin.press('Enter')
  await expect(page.getByRole('status')).toContainText('2 秒后重试')
  await expect(page.getByRole('button', { name: '进入', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '进入', exact: true })).toBeEnabled({ timeout: 4000 })
  expect(f.posts).toHaveLength(1)
  expect(f.unexpected).toEqual([])
})

for (const role of ['viewer', 'operator']) {
  test(`${role}登录成功仍须门户PIN且不请求reveal秘密`, async ({ page }) => {
    const f = await fixture(page, { me: { id: 2, username: 'fixture-user', role,
      capabilities: role === 'viewer' ? ['view'] : ['view', 'edit', 'probe'] } })
    await expect(page.getByLabel('门户 PIN')).toBeVisible()
    expect(f.posts).toEqual([])
    expect(f.unexpected).toEqual([])
  })
}
