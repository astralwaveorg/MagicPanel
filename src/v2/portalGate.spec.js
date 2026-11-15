import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import Portal from '../views/Portal.vue'
import { createPortalGate, portalDeviceResource, validPortalPin } from './portalGate'

test.each([
  ['1234', true], ['123456', true], ['12345', false], ['12ab', false],
  ['', false], ['1234567', false], [1234, false],
])('门户仅接受4/6位数字字符串：%s', (pin, valid) => {
  expect(validPortalPin(pin)).toBe(valid)
})

test('门禁reset后忽略旧响应，旧请求结束不会解除新请求的单飞保护', async () => {
  const first = deferred(), second = deferred()
  const gate = createPortalGate(pin => pin === '1234' ? first.promise : second.promise)
  const old = gate.submit('1234')
  gate.reset()
  const current = gate.submit('654321')
  first.resolve({ marker: 'old' })
  await old
  expect(gate.state.data).toBe(null)
  expect(gate.state.loading).toBe(true)
  expect(gate.submit('654321')).toBe(current)
  second.resolve({ marker: 'current' })
  await current
  expect(gate.state.data).toEqual({ marker: 'current' })
  expect(gate.state.loading).toBe(false)
})

test('门禁未获免PIN许可时拒绝空PIN，错误保留在响应代次内', async () => {
  const gate = createPortalGate(() => Promise.resolve({ marker: 'revealed' }))
  await expect(gate.submit('')).rejects.toThrow('4 或 6 位')
  expect(gate.state.loading).toBe(false)
  await gate.submit('', { canSkipPin: true })
  expect(gate.state.data).toEqual({ marker: 'revealed' })
})

test('门禁reset后的旧失败不能覆盖新一轮结果', async () => {
  let reject
  const oldResponse = new Promise((resolve, fail) => { reject = fail })
  const gate = createPortalGate(pin => pin === '1234' ? oldResponse : Promise.resolve({ marker: 'current' }))
  const old = gate.submit('1234')
  gate.reset()
  await gate.submit('123456')
  reject(new Error('旧轮次失败'))
  await old
  expect(gate.state.data).toEqual({ marker: 'current' })
  expect(gate.state.error).toBe(null)
  expect(gate.state.loading).toBe(false)
})

test('资源URL拒绝设备未授权方案和非HTTP地址，不推断来源路径', () => {
  const dto = fixtureData()
  expect(portalDeviceResource(dto.devices[0], '未授权方案', dto.variants)).toBe(null)
  expect(portalDeviceResource({ ...dto.devices[0], subscription_url: 'javascript:alert(1)' },
    '默认', dto.variants)).toBe(null)
})

const fixtureData = () => ({
  devices: [{
    name: 'fixture-phone', display_name: '示例手机', platform: 'ios', env: 'production',
    engine: 'stash', target_name: 'fixture-ios', note: '', last_pull_at: null,
    subscription_url: 'http://127.0.0.1:7100/feed/fixture-only/config.yaml?client=fixture',
    preview_url: '/feed/fixture-only/config.yaml?preview=1&client=fixture',
    variants: ['默认', '办公 & 测试'],
  }],
  variants: [{ id: 0, name: '默认', note: '' }, { id: 1, name: '办公 & 测试', note: '' },
    { id: 2, name: '未授权方案', note: '' }],
  clients: [], guides: [], rules: [], rule_providers: [], snippets: [],
  release_state: { production: null, testing: null },
})
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', ...headers },
})
const deferred = () => {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}
let wrapper, requests, send, me

beforeEach(() => {
  sessionStorage.clear()
  requests = []
  me = () => json({ detail: '未登录' }, 401)
  send = () => json(fixtureData())
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (url === '/api/v1/auth/me') return me()
    if (url === '/api/v1/portal/data') {
      requests.push(JSON.parse(options.body))
      return send()
    }
    throw new Error('unexpected fixture endpoint')
  }))
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
async function openPortal() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: Portal }, { path: '/admin/login', component: { template: '<div>登录</div>' } },
  ] })
  await router.push('/')
  wrapper = mount(Portal, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}
async function enter(pin = '123456') {
  await wrapper.get('.pt-pin').setValue(pin)
  await wrapper.get('.pt-pin-form').trigger('submit')
  await flushPromises()
}

describe('真实门户的 PIN 提交', () => {
  test('输入第四位和第六位都不发请求，显式提交才发送完整历史 PIN', async () => {
    await openPortal()
    await wrapper.get('.pt-pin').setValue('1234')
    expect(requests).toEqual([])
    await wrapper.get('.pt-pin').setValue('123456')
    expect(requests).toEqual([])
    expect(wrapper.get('.pt-pin').element.checkValidity()).toBe(true)
    await wrapper.get('.pt-pin-form').trigger('submit')
    await flushPromises()
    expect(requests).toEqual([{ pin: '123456' }])
    expect(wrapper.find('.pt-hero').exists()).toBe(true)
    expect(sessionStorage.getItem('mp-portal-pin')).toBe('123456')
  })

  test('5位无法提交，等待中的重复提交只发一次', async () => {
    const pending = deferred()
    send = () => pending.promise
    await openPortal()
    await enter('12345')
    expect(requests).toEqual([])
    await enter('1234')
    await wrapper.get('.pt-pin-form').trigger('submit')
    expect(requests).toEqual([{ pin: '1234' }])
    expect(wrapper.get('.pt-pin-submit').element.disabled).toBe(true)
    pending.resolve(json(fixtureData()))
    await flushPromises()
  })

  test.each([401, 403])('旧的%s失败不清空后来输入，也不跳管理登录', async status => {
    const pending = deferred()
    send = () => pending.promise
    await openPortal()
    await enter('1234')
    await wrapper.get('.pt-pin').setValue('654321')
    pending.resolve(json({ detail: '该次 PIN 未通过' }, status))
    await flushPromises()
    expect(wrapper.get('.pt-pin').element.value).toBe('654321')
    expect(wrapper.find('.pt-gate').exists()).toBe(true)
    expect(wrapper.text()).toContain('该次 PIN 未通过')
  })

  test('429使用Retry-After倒数，倒数结束才允许重新提交', async () => {
    send = () => json({ detail: '稍后重试' }, 429, { 'Retry-After': '3' })
    await openPortal()
    vi.useFakeTimers()
    await enter('1234')
    expect(wrapper.text()).toContain('3 秒后重试')
    expect(wrapper.get('.pt-pin-submit').element.disabled).toBe(true)
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.get('.pt-pin-submit').element.disabled).toBe(false)
  })

  test('Retry-After的HTTP日期可倒数，缺少头时不猜固定锁定时间', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-15T00:00:00Z'))
    await openPortal()
    send = () => json({ detail: '暂时限流' }, 429, { 'Retry-After': 'Sun, 15 Nov 2026 00:00:05 GMT' })
    await enter('123456')
    expect(requests).toEqual([{ pin: '123456' }])
    expect(wrapper.text()).toContain('5 秒后重试')
    await vi.advanceTimersByTimeAsync(5000)
    send = () => json({ detail: '暂时限流' }, 429)
    await enter('123456')
    expect(wrapper.text()).toContain('暂时限流')
    expect(wrapper.text()).not.toContain('秒后重试')
  })

  test('历史6位sessionStorage可恢复，退出清除PIN并返回门禁', async () => {
    sessionStorage.setItem('mp-portal-pin', '123456')
    await openPortal()
    expect(wrapper.find('.pt-hero').exists()).toBe(true)
    expect(requests).toEqual([{ pin: '123456' }])
    await wrapper.get('.pt-exit').trigger('click')
    expect(sessionStorage.getItem('mp-portal-pin')).toBe(null)
    expect(wrapper.find('.pt-gate').exists()).toBe(true)
  })

  test.each([
    { capabilities: [] }, { capabilities: ['view'] }, { capabilities: ['view', 'edit', 'probe'] },
  ])('无reveal能力$capabilities的会话仍等待PIN', async ({ capabilities }) => {
    me = () => json({ id: 2, username: 'fixture-user', role: 'operator', capabilities })
    await openPortal()
    expect(requests).toEqual([])
    expect(wrapper.find('.pt-gate').exists()).toBe(true)
  })

  test('具有服务端reveal能力的会话可免PIN', async () => {
    me = () => json({ id: 1, username: 'fixture-admin', capabilities: ['view', 'reveal'] })
    await openPortal()
    expect(requests).toEqual([{ pin: '' }])
    expect(wrapper.find('.pt-hero').exists()).toBe(true)
  })

  test('auth/me没有capabilities不能由旧role推断免PIN', async () => {
    me = () => json({ id: 1, username: 'fixture-admin', role: 'admin' })
    await openPortal()
    expect(requests).toEqual([])
  })
})

test('只有自定义产物时选择首个授权方案，无可用产物时不展示订阅动作', async () => {
  const dto = fixtureData()
  dto.devices[0].variants = ['办公 & 测试']
  dto.devices.push({ ...dto.devices[0], name: 'fixture-disabled', variants: [] })
  send = () => json(dto)
  await openPortal()
  await enter()
  const cards = wrapper.findAll('.pt-card')
  expect(cards[0].get('a[download]').attributes('href')).toContain('&variant=%E5%8A%9E%E5%85%AC+%26+%E6%B5%8B%E8%AF%95')
  expect(cards[1].find('a[download]').exists()).toBe(false)
  expect(cards[1].get('button.pt-btn.primary').element.disabled).toBe(true)
})

test('方案选择只展示设备授权项，保留query并统一复制/下载/导入/预览', async () => {
  const copied = []
  vi.stubGlobal('navigator', { clipboard: { writeText: async text => copied.push(text) } })
  await openPortal()
  await enter()
  expect(wrapper.text()).not.toContain('未授权方案')
  const chip = wrapper.findAll('.pt-variant-chip').find(w => w.text() === '办公 & 测试')
  await chip.trigger('click')
  const want = 'http://127.0.0.1:7100/feed/fixture-only/config.yaml?client=fixture&variant=%E5%8A%9E%E5%85%AC+%26+%E6%B5%8B%E8%AF%95'
  const card = wrapper.get('.pt-card')
  await card.get('button.pt-btn.primary').trigger('click')
  expect(copied).toEqual([want])
  expect(card.get('a[download]').attributes('href')).toBe(want)
  expect(decodeURIComponent(card.findAll('a.pt-btn')[1].attributes('href').split('?url=')[1])).toBe(want)
  const originalFetch = fetch
  let previewUrl
  vi.stubGlobal('fetch', async (url, options) => {
    if (String(url).includes('/feed/')) { previewUrl = url; return new Response('mode: rule') }
    return originalFetch(url, options)
  })
  await card.get('.pt-card-name-btn').trigger('click')
  await flushPromises()
  expect(previewUrl).toBe('/feed/fixture-only/config.yaml?preview=1&client=fixture&variant=%E5%8A%9E%E5%85%AC+%26+%E6%B5%8B%E8%AF%95')
  expect(wrapper.get('.pt-yaml-code').text()).toBe('mode: rule')
})
