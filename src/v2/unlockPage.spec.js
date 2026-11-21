import { afterEach, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import Unlock from '../views/Unlock.vue'

let wrapper
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.unstubAllGlobals() })

const CATALOG = {
  checks: [
    { id: 'gemini', name: 'Google Gemini', icon: '✦', category: 'ai' },
    { id: 'netflix', name: 'Netflix', icon: 'N', category: 'stream' },
  ],
  categories: { ai: '海外 AI', stream: '流媒体' },
}
const EMPTY_LAST = {}
const RUN_RESULT = {
  checked_at: Math.floor(Date.now() / 1000), exit: 'panel',
  results: [{ id: 'gemini', status: 200, state: 'unlocked', region: 'US', latency_ms: 500,
              extra: { route: { ip: '192.0.2.2', domain: 'gemini.google.com', source: 'domain_trace' } } },
            { id: 'netflix', status: 403, state: 'blocked', region: '', latency_ms: 600 }],
  ip: { ip: '192.220.75.184', country: 'US', org: 'NTT', city: 'LA' },
}
const QUALITY = {
  items: [{ name: '测试线路', stage: 'probed', delay_ms: 200, speed_bps: 3000000 }],
  counts: { probed: 1 },
  task: { running: false },
  auto: false,
}

function stubFetch(responses) {
  vi.stubGlobal('fetch', async path => {
    const body = responses[path] ?? {}
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

test('页面挂载后渲染两网络环境对照表与分类（非空白）', async () => {
  stubFetch({
    '/api/v1/unlock/catalog': CATALOG,
    '/api/v1/unlock/last?exit=panel': EMPTY_LAST,
    '/api/v1/unlock/quality': QUALITY,
  })
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('网络体检')
  // 服务器网络是页面主体
  expect(wrapper.text()).toContain('服务器网络')
  expect(wrapper.text()).not.toContain('当前网络')
  // 服务分类与服务名
  expect(wrapper.text()).toContain('海外 AI')
  expect(wrapper.text()).toContain('Google Gemini')
  expect(wrapper.text()).toContain('Netflix')
  // 检测入口
  expect(wrapper.text()).toContain('检测服务器网络')
  expect(wrapper.text()).not.toContain('检测当前网络')
  // 未测状态可见
  expect(wrapper.text()).toContain('未测')
  expect(wrapper.text()).toContain('节点测速与解锁')
  expect(wrapper.text()).toContain('测试线路')
  expect(wrapper.text()).toContain('导出达标节点')
})

test('检测服务器网络后展示解锁结论与出口信息', async () => {
  stubFetch({
    '/api/v1/unlock/catalog': CATALOG,
    '/api/v1/unlock/last?exit=panel': EMPTY_LAST,
    '/api/v1/unlock/quality': QUALITY,
  })
  const realFetch = globalThis.fetch
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const postPaths = []
  globalThis.fetch = async (path, opts) => {
    if (opts?.method === 'POST') {
      postPaths.push(path)
      return new Response(JSON.stringify(RUN_RESULT), { status: 200 })
    }
    return realFetch(path, opts)
  }
  const runBtn = wrapper.findAll('button').find(b => b.text() === '检测服务器网络')
  expect(runBtn).toBeDefined()
  await runBtn.trigger('click')
  await flushPromises()
  expect(postPaths).toEqual(['/api/v1/unlock/run'])
  expect(wrapper.text()).toContain('已确认')
  expect(wrapper.text()).toContain('192.220.*.*')
  expect(wrapper.text()).toContain('域名出口：192.0.2.2')
  expect(wrapper.text()).toContain('访问受限')
  expect(wrapper.text()).not.toContain('一致')
})

test('单项复测只请求所选服务并保留其他服务的结果', async () => {
  const request = vi.fn(async (path, options) => {
    if (path === '/api/v1/unlock/run') {
      return new Response(JSON.stringify({ ...RUN_RESULT,
        results: [{ id: 'netflix', state: 'reachable', status: 200 }] }))
    }
    const responses = {
      '/api/v1/unlock/catalog': CATALOG,
      '/api/v1/unlock/last?exit=panel': RUN_RESULT,
      '/api/v1/unlock/quality': QUALITY,
    }
    return new Response(JSON.stringify(responses[path] ?? {}))
  })
  vi.stubGlobal('fetch', request)
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  await wrapper.get('button[aria-label="从服务器检测 Netflix"]').trigger('click')
  await flushPromises()
  const [, options] = request.mock.calls.find(([path]) => path === '/api/v1/unlock/run')
  expect(JSON.parse(options.body)).toEqual({ exit: 'panel', ids: ['netflix'] })
  expect(wrapper.text()).toContain('域名出口：192.0.2.2')
  expect(wrapper.text()).not.toContain('访问受限')
})

