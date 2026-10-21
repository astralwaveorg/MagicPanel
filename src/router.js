import { createRouter, createWebHistory } from 'vue-router'
import { api } from './api'
import { store } from './store'

// “/” 为 Magic Panel 首页（PIN 门禁，无需登录）；管理端统一挂在 /admin 下。
const routes = [
  { path: '/', component: () => import('./views/Portal.vue'), meta: { title: 'MagicPanel - 订阅配置服务中心', standalone: true } },
  { path: '/admin/setup', component: () => import('./views/Setup.vue'), meta: { title: '初始化' } },
  { path: '/admin/login', component: () => import('./views/Login.vue'), meta: { title: '登录' } },
  { path: '/admin', component: () => import('./views/Overview.vue'), meta: { title: '系统状态' } },
  { path: '/admin/sources', component: () => import('./views/Sources.vue'), meta: { title: '节点来源' } },
  { path: '/admin/rule-providers', component: () => import('./views/RuleProviders.vue'), meta: { title: '规则来源' } },
  { path: '/admin/groups', component: () => import('./views/Groups.vue'), meta: { title: '策略组' } },
  { path: '/admin/rules', component: () => import('./views/Rules.vue'), meta: { title: '分流规则' } },
  { path: '/admin/snippets', component: () => import('./views/Snippets.vue'), meta: { title: '功能模块' } },
  { path: '/admin/artifact', component: () => import('./views/ArtifactConfig.vue'), meta: { title: '产物配置' } },
  { path: '/admin/targets', component: () => import('./views/Targets.vue'), meta: { title: '引擎平台' } },
  { path: '/admin/devices', component: () => import('./views/Devices.vue'), meta: { title: '设备管理' } },
  { path: '/admin/builds', component: () => import('./views/Builds.vue'), meta: { title: '构建发布' } },
  { path: '/admin/automation', component: () => import('./views/Automation.vue'), meta: { title: '自动发布' } },
  { path: '/admin/audit', component: () => import('./views/Audit.vue'), meta: { title: '审计日志' } },
  { path: '/admin/settings', component: () => import('./views/Settings.vue'), meta: { title: '设置' } },
  // 旧路径兼容
  { path: '/portal', redirect: '/' },
  { path: '/login', redirect: '/admin/login' },
  { path: '/setup', redirect: '/admin/setup' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (!store.ready) {
    try {
      const s = await api('/api/v1/setup/status')
      store.initialized = s.initialized
    } catch {
      store.initialized = true
    }
    if (store.initialized) {
      try {
        const me = await api('/api/v1/auth/me')
        store.user = me
        store.csrf = me.csrf_token
      } catch { /* 未登录 */ }
    }
    store.ready = true
  }
  if (!store.initialized) {
    return to.path === '/admin/setup' ? true : '/admin/setup'
  }
  if (to.meta.standalone) {
    // 独立页标题自带完整品牌，不拼后缀
    document.title = to.meta.title
    return true
  }
  if (to.path === '/admin/setup') {
    document.title = '初始化 · MagicPanel'
    return '/admin/login'
  }
  if (to.path === '/admin/login') {
    document.title = '登录 · MagicPanel'
    return store.user ? '/admin' : true
  }
  if (!store.user) {
    document.title = '登录 · MagicPanel'
    return '/admin/login'
  }
  document.title = `${to.meta.title} · MagicPanel`
  return true
})
