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
const COVERAGE = { total: 30, covered: 12, missing: 18, ratio: 0.4 }

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
    '/api/v1/unlock/capability-coverage': COVERAGE,
    '/api/v1/unlock/batch-status': { running: false, done: 0, total: 0 },
  })
  wrapper = mount(Unlock, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('网络体检')
  // 两个网络环境是页面主体
  expect(wrapper.text()).toContain('当前网络（这台设备）')
  expect(wrapper.text()).toContain('服务器网络（面板出口）')
  // 服务分类与服务名
  expect(wrapper.text()).toContain('海外 AI')
  expect(wrapper.text()).toContain('Google Gemini')
  expect(wrapper.text()).toContain('Netflix')
  // 两个检测入口
  expect(wrapper.text()).toContain('检测服务器网络')
  expect(wrapper.text()).toContain('检测当前网络')
  // 未测状态可见
  expect(wrapper.text()).toContain('未测')
  // 节点能力区块说明能力在构建期测
  expect(wrapper.text()).toContain('节点能力')
  expect(wrapper.text()).toContain('12 / 30')
})

test('检测服务器网络后展示解锁结论与出口信息', async () => {
  stubFetch({
    '/api/v1/unlock/catalog': CATALOG,
    '/api/v1/unlock/last?exit=panel': EMPTY_LAST,
    '/api/v1/unlock/capability-coverage': COVERAGE,
    '/api/v1/unlock/batch-status': { running: false, done: 0, total: 0 },
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
  expect(wrapper.text()).toContain('解锁')
  expect(wrapper.text()).toContain('192.220.*.*')
  expect(wrapper.text()).toContain('区域拒绝')
  // 对照列给出结论
  expect(wrapper.text()).toContain('对照')
})
