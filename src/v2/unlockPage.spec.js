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
  results: [{ id: 'gemini', status: 200, state: 'unlocked', region: 'US', latency_ms: 500 },
            { id: 'netflix', status: 403, state: 'blocked', region: '', latency_ms: 600 }],
  ip: { ip: '192.220.75.184', country: 'US', org: 'NTT', city: 'LA' },
}

function stubFetch(responses) {
  vi.stubGlobal('fetch', async path => {
    const body = responses[path] ?? {}
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

test('页面挂载后渲染分类卡片与工具栏（非空白）', async () => {
  stubFetch({
    '/api/v1/unlock/catalog': CATALOG,
    '/api/v1/unlock/last?exit=panel': EMPTY_LAST,
  })
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('网络体检')
  expect(wrapper.text()).toContain('海外 AI')
  expect(wrapper.text()).toContain('Google Gemini')
  expect(wrapper.text()).toContain('Netflix')
  expect(wrapper.text()).toContain('全部检测')
  // 未测状态可见
  expect(wrapper.text()).toContain('未测')
})

test('点击全部检测后显示结果与出口信息', async () => {
  const postPaths = []
  stubFetch({
    '/api/v1/unlock/catalog': CATALOG,
    '/api/v1/unlock/last?exit=panel': EMPTY_LAST,
    '/api/v1/nodes?limit=200': { items: [], total: 0 },
    '/api/v1/unlock/run': RUN_RESULT,
  })
  const realFetch = globalThis.fetch
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  // 拦截 POST
  globalThis.fetch = async (path, opts) => {
    if (opts?.method === 'POST') {
      postPaths.push(path)
      return new Response(JSON.stringify(RUN_RESULT), { status: 200 })
    }
    return realFetch(path, opts)
  }
  const runBtn = wrapper.findAll('button').find(b => b.text() === '全部检测')
  expect(runBtn).toBeDefined()
  await runBtn.trigger('click')
  await flushPromises()
  expect(postPaths).toEqual(['/api/v1/unlock/run'])
  expect(wrapper.text()).toContain('解锁')
  expect(wrapper.text()).toContain('192.220.*.*')
  expect(wrapper.text()).toContain('区域拒绝')
})
