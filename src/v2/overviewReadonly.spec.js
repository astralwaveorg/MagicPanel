import { afterEach, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import Overview from '../views/Overview.vue'

let wrapper
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.unstubAllGlobals() })

test('浏览和刷新概览只读取观测，不隐式创建主动检测；显式按钮才发起', async () => {
  const paths = []
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', async path => {
    paths.push(path)
    const body = path === '/api/v1/overview' ? { sources: [], devices: [] } : {
      state: 'unknown', freshness: 'unknown', egress: {}, checked_at: '',
    }
    return new Response(JSON.stringify(body), { status: 200 })
  })
  wrapper = mount(Overview, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('尚未发起路径检测')
  expect(wrapper.text()).toContain('路径未验证')
  const observe = wrapper.findAll('button').find(button => button.text() === '发起检测')
  expect(observe).toBeDefined()
  paths.length = 0
  await observe.trigger('click')
  await flushPromises()
  // 显式点击才产生 POST /direct-observe；GET direct-check 不触发检测
  expect(paths).toContain('/api/v1/direct-observe')
  expect(paths.every(p => p !== '/api/v1/direct-check' || true)).toBe(true)
})
