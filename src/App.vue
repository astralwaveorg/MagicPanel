<template>
  <router-view v-if="isAuthPage" />
  <div v-else class="mp-layout">
    <aside class="mp-aside">
      <div class="mp-brand">
        <img src="/logo.svg" class="mp-brand-logo" alt="MagicPanel" title="返回门户首页" @click="router.push('/')">
        <span class="mp-brand-text" title="返回概览" @click="router.push('/admin')">
          MagicPanel
          <small>代理订阅配置管理</small>
        </span>
      </div>
      <el-menu :default-active="route.path" router>
        <el-menu-item v-for="item in menu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
      <div class="mp-aside-footer">
        <span class="mp-aside-user">
          <UserAvatar :user="store.user" :size="26" />
          <span class="mp-aside-name">{{ store.user?.display_name || store.user?.username }}</span>
        </span>
        <el-tooltip :content="theme === 'dark' ? '切换为亮色' : '切换为暗色'" placement="top">
          <el-button text @click="onToggleTheme" :aria-label="theme === 'dark' ? '切换为亮色' : '切换为暗色'">
            <el-icon :size="17"><Sunny v-if="theme === 'dark'" /><Moon v-else /></el-icon>
          </el-button>
        </el-tooltip>
        <el-button text size="small" @click="onLogout">退出</el-button>
      </div>
    </aside>

    <el-drawer v-model="drawer" direction="ltr" size="240px" :with-header="false">
      <div class="mp-brand">
        <img src="/logo.svg" class="mp-brand-logo" alt="MagicPanel" title="返回门户首页" @click="drawer = false; router.push('/')">
        <span class="mp-brand-text" title="返回概览" @click="drawer = false; router.push('/admin')">
          MagicPanel
          <small>代理订阅配置管理</small>
        </span>
      </div>
      <el-menu :default-active="route.path" @select="drawer = false" router>
        <el-menu-item v-for="item in menu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-drawer>

    <div class="mp-main">
      <div class="mp-topbar">
        <el-button text @click="drawer = true" aria-label="打开菜单">
          <el-icon :size="20"><Menu /></el-icon>
        </el-button>
        <strong>{{ route.meta.title }}</strong>
        <span style="flex:1"></span>
        <el-button text @click="onToggleTheme" :aria-label="theme === 'dark' ? '切换为亮色' : '切换为暗色'">
          <el-icon :size="17"><Sunny v-if="theme === 'dark'" /><Moon v-else /></el-icon>
        </el-button>
        <UserAvatar :user="store.user" :size="24" />
        <span style="font-size:13px;color:var(--mp-text-secondary)">{{ store.user?.display_name || store.user?.username }}</span>
        <el-button text size="small" @click="onLogout">退出</el-button>
      </div>
      <main class="mp-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Menu, Moon, Odometer, Connection, Collection, SetUp, Filter, Monitor,
  Iphone, Promotion, Document, Sunny, Tools, MagicStick, Timer, Operation,
} from '@element-plus/icons-vue'
import { confirmBox } from './confirm'
import { api } from './api'
import { store } from './store'
import { currentTheme, toggleTheme } from './theme'
import UserAvatar from './components/UserAvatar.vue'

const route = useRoute()
const router = useRouter()
const drawer = ref(false)
const theme = ref(currentTheme())

function onToggleTheme() {
  theme.value = toggleTheme()
}

const isAuthPage = computed(() =>
  route.meta.standalone || ['/admin/login', '/admin/setup'].includes(route.path))

// 侧边栏按依赖顺序排列：上游内容 → 引用它们 → 产物形态 → 配置 → 设备 → 构建发布 → 运维。
// 高频页面同时尽量靠上，日常改策略的路径最短。
const menu = [
  { path: '/admin', title: '概览', icon: Odometer },
  { path: '/admin/sources', title: '节点来源', icon: Connection },
  { path: '/admin/rule-providers', title: '规则来源', icon: Collection },
  { path: '/admin/groups', title: '策略组', icon: SetUp },
  { path: '/admin/rules', title: '分流规则', icon: Filter },
  { path: '/admin/targets', title: '引擎平台', icon: Monitor },
  { path: '/admin/artifact', title: '产物配置', icon: Operation },
  { path: '/admin/snippets', title: '功能模块', icon: MagicStick },
  { path: '/admin/devices', title: '设备管理', icon: Iphone },
  { path: '/admin/builds', title: '构建发布', icon: Promotion },
  { path: '/admin/automation', title: '自动发布', icon: Timer },
  { path: '/admin/audit', title: '审计日志', icon: Document },
  { path: '/admin/settings', title: '设置', icon: Tools },
]

async function onLogout() {
  if (!await confirmBox('确定退出当前账号？', '退出登录')) return
  try { await api('/api/v1/auth/logout', { method: 'POST' }) } catch { /* 忽略 */ }
  store.user = null
  store.csrf = ''
  router.push('/admin/login')
}
</script>
