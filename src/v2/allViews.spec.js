// 全视图挂载冒烟：每个管理页在最小数据下必须能渲染出可见内容，
// 不允许出现"引用未定义变量导致整页空白"一类的事故（Unlock 页曾发生过）。
import { afterEach, describe, expect, test, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'

// 各页面主接口的最小合法响应；未列出的路径一律返回 {}
// 用生产的真实条目形状做桩（含全部字段），比手造最小对象更能暴露真实缺陷
import groupsFixture from './fixtures/groups.json'
import rulesFixture from './fixtures/rules.json'
import sourcesFixture from './fixtures/sources.json'
import ruleProvidersFixture from './fixtures/rule-providers.json'
import devicesFixture from './fixtures/devices.json'
import targetsFixture from './fixtures/targets.json'
import snippetsFixture from './fixtures/snippets.json'
import variantsFixture from './fixtures/variants.json'

const DATA = {
  '/api/v1/variants': variantsFixture,
  '/api/v1/devices': devicesFixture,
  '/api/v1/groups?': groupsFixture,
  '/api/v1/rules?': rulesFixture,
  '/api/v1/sources': sourcesFixture,
  '/api/v1/rule-providers': ruleProvidersFixture,
  '/api/v1/snippets': snippetsFixture,
  '/api/v1/builds': [],
  '/api/v1/targets': targetsFixture,
  '/api/v1/overview': {
    counts: { groups: 1, rules: 1, rules_enabled: 1, devices_stale: 0 },
    sources: [], rule_providers: [], devices: [], recent_audit: [],
    release_state: { release_revisions: { production: 1, testing: 1 } },
    direct: {},
  },
  '/api/v1/direct-check': { state: 'unknown', freshness: 'unknown', egress: {}, checked_at: '' },
                  '/api/v1/base-config': { scopes: [], targets: [], doc: {} },
    '/api/v1/audit?': { items: [], total: 0 },
  '/api/v1/settings': {},
  '/api/v1/users': [],
  '/api/v1/portal/status': { enabled: false },
  '/api/v1/core/status': { available: false },
  '/api/v1/deps/status': {},
  '/api/v1/unlock/catalog': { checks: [
    { id: 'gemini', name: 'Gemini', icon: '✦', category: 'ai' },
    { id: 'netflix', name: 'Netflix', icon: 'N', category: 'stream' },
  ], categories: { ai: '海外 AI', stream: '流媒体' } },
  '/api/v1/nodes?limit=200': { items: [], total: 0 },
  '/api/v1/automation': {},
}

const VIEWS = [
  ['/admin', () => import('../views/Overview.vue'), '系统概览'],
  ['/admin/unlock', () => import('../views/Unlock.vue'), '网络体检'],
  ['/admin/groups', () => import('../views/Groups.vue'), '策略组'],
  ['/admin/rules', () => import('../views/Rules.vue'), '分流策略'],
  ['/admin/sources', () => import('../views/Sources.vue'), '节点来源'],
  ['/admin/rule-providers', () => import('../views/RuleProviders.vue'), '规则来源'],
  ['/admin/artifact', () => import('../views/BaseConfig.vue'), '基础配置'],
  ['/admin/devices', () => import('../views/Devices.vue'), '设备管理'],
  ['/admin/builds', () => import('../views/Builds.vue'), '构建发布'],
  ['/admin/snippets', () => import('../views/Snippets.vue'), '拓展模块'],
  ['/admin/dependencies', () => import('../views/Dependencies.vue'), '自主维护'],
  ['/admin/audit', () => import('../views/Audit.vue'), '审计日志'],
  ['/admin/settings', () => import('../views/Settings.vue'), '系统设置'],
  ['/admin/login', () => import('../views/Login.vue'), '登录'],
  ['/admin/setup', () => import('../views/Setup.vue'), '初始化'],
  ['/', () => import('../views/Portal.vue'), '订阅门户'],
]

let router
afterEach(async () => {
  vi.unstubAllGlobals()
  if (router) await router.replace('/')
})

function makeRouter() {
  // 每个用例独立 memory 路由，避免 WebHistory 在 jsdom 里的跨用例污染
  return createRouter({
    history: createMemoryHistory(),
    routes: VIEWS.map(([path, component]) => ({ path, component })),
  })
}

function stubFetch() {
  vi.stubGlobal('fetch', async (input) => {
    const path = typeof input === 'string' ? input : input.url
    const base = path.split('?')[0]
    const key = Object.keys(DATA).find(k => path.startsWith(k)) ?? base
    if (!(key in DATA)) {
      // 未登记的路径返回 503：漏 mock 从"静默空对象"变成显式信号——
      // 视图必须自己兜底（?? []），否则冒烟会红（2026-11-18）
      return new Response(JSON.stringify({ detail: 'stub 未登记该接口' }), { status: 503 })
    }
    return new Response(JSON.stringify(DATA[key]), { status: 200 })
  })
}

describe('全视图挂载冒烟', () => {
  for (const [path, load, title] of VIEWS) {
    test(`${title}（${path}）挂载渲染非空白`, async () => {
      stubFetch()
      router = makeRouter()
      router.push(path)
      await router.isReady()
      const { default: view } = await load()
      wrapper = mount(view, { global: { plugins: [ElementPlus, router] } })
      await flushPromises()
      expect(wrapper.text().trim().length, `${title} 渲染为空白`).toBeGreaterThan(0)
      wrapper?.unmount()
      wrapper = null
    })
  }
})

let wrapper = null
