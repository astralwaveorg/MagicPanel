import { afterEach, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import Overview from '../views/Overview.vue'

let wrapper
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.unstubAllGlobals() })

test('浏览和刷新概览只读取观测，不隐式创建主动检测', async () => {
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
  expect(wrapper.text()).toContain('暂无出口观测，未发起主动检测。')
  expect(wrapper.text()).toContain('路径未验证')
  const refresh = wrapper.findAll('button').find(button => button.text() === '刷新记录')
  expect(refresh).toBeDefined()
  await refresh.trigger('click')
  await flushPromises()
  expect(paths).toEqual(['/api/v1/overview', '/api/v1/direct-check', '/api/v1/direct-check'])
  expect(wrapper.text()).not.toContain('正在检测出口')
})
