<template>
  <div>
    <h2 class="mp-page-title">网络体检</h2>
    <p class="mp-page-desc">查看当前网络和服务器网络能访问哪些服务。</p>

    <div class="mp-card">
      <div class="unlock-toolbar">
        <el-button size="small" type="success" :loading="running"
                   @click="runServerChecks">检测服务器网络</el-button>
        <el-button size="small" type="success" :loading="browserRunning" :disabled="!catalog.length"
                   @click="runBrowserChecks">检测当前网络</el-button>
        <el-button size="small" :disabled="!hasResults" @click="copyResults">复制结果</el-button>
      </div>
    </div>

    <div class="mp-card">
      <div class="unlock-cols">
        <div class="unlock-col" v-for="group in summaries" :key="group.title">
          <div class="unlock-col-head">{{ group.title }}</div>
          <div class="unlock-col-body">
            <span class="cnt" v-for="item in group.items" :key="item.label">
              <b>{{ item.count }}</b>{{ item.label }}
            </span>
          </div>
          <p v-if="group.checkedAt || group.ip.ip" class="unlock-meta">
            <span v-if="group.ip.ip">参考出口 {{ maskIp(group.ip.ip) }} {{ group.ip.country }}</span>
            <span v-if="group.checkedAt">检测于 {{ fmtTime(group.checkedAt) }}</span>
          </p>
        </div>
      </div>
      <p v-if="exitHint" class="mp-form-hint">{{ exitHint }}</p>
      <p v-if="challengeCount" class="mp-form-hint">
        {{ challengeCount }} 项触发人机校验，可打开网页核实。
      </p>
      <p v-if="browserReview.length" class="mp-form-hint">
        {{ browserReview.length }} 项未确认响应，可点服务名打开网页核实。
      </p>
    </div>

    <div v-for="cat in visibleCategories" :key="cat.id" class="mp-card">
      <h3>{{ cat.name }} <span class="unlock-cat-count">{{ catItems(cat.id).length }}</span></h3>
      <div class="mp-table-wrap">
        <el-table :data="catItems(cat.id)" size="small" class="unlock-table">
          <el-table-column label="服务" min-width="180">
            <template #default="{ row }">
              <a v-if="siteById[row.id]" class="unlock-svc unlock-link" :href="siteById[row.id]"
                 target="_blank" rel="noopener noreferrer" :aria-label="`打开 ${row.name}`">
                <span class="unlock-icon-sm">{{ row.icon }}</span>{{ row.name }}
              </a>
              <span v-else class="unlock-svc"><span class="unlock-icon-sm">{{ row.icon }}</span>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="当前网络" min-width="190">
            <template #default="{ row }">
              <StatusDot :kind="browserKind(row.id)" :text="browserLabel(row.id)" />
              <span class="unlock-cell-sub">{{ browserLatency(row.id) }}</span>
              <div v-if="browserMap[row.id]" class="unlock-route" :title="browserMap[row.id]?.route?.domain">
                {{ browserRouteLabel(row.id) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="服务器网络" min-width="190">
            <template #default="{ row }">
              <StatusDot :kind="serverKind(row.id)" :text="serverLabel(row.id)" />
              <span class="unlock-cell-sub">{{ serverSub(row.id) }}</span>
              <div v-if="serverMap[row.id]" class="unlock-route" :title="routeTitle(row.id)">
                {{ routeLabel(row.id) }}
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <p class="mp-form-hint unlock-help">点服务名，打开网页验证登录或播放。</p>

    <NodeQualityCard />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'
import { fmtTime, latencyText } from '../format'
import { copyText } from '../utils/clipboard'
import { BROWSER_CHECKS, probeAll, probeExitIp } from '../utils/browserChecks'
import StatusDot from '../components/StatusDot.vue'
import NodeQualityCard from '../components/NodeQualityCard.vue'

const catalog = ref([])
const serverMap = ref({})
const browserMap = ref({})
const serverIp = ref({})
const browserIp = ref({})
const browserCheckedAt = ref(null)
const serverCheckedAt = ref(null)
const running = ref(false)
const browserRunning = ref(false)

const categories = [
  { id: 'ai', name: '海外 AI' },
  { id: 'stream', name: '流媒体' },
  { id: 'region', name: '服务地区检测' },
  { id: 'web', name: '网站服务' },
]

const browserById = Object.fromEntries(BROWSER_CHECKS.map(check => [check.id, check]))
const siteById = Object.fromEntries(BROWSER_CHECKS.map(check => [check.id, check.site]))

function catItems(cid) { return catalog.value.filter(c => c.category === cid) }
const visibleCategories = computed(() => categories.filter(c => catItems(c.id).length > 0))
const browserLabels = {
  reachable: '有响应', unknown: '无法确认', timeout: '超时', idle: '未测', unsupported: '不适用',
}
const serverLabels = {
  reachable: '网页可达', unlocked: '已确认', blocked: '访问受限',
  challenge: '人机校验', unknown: '无法确认', unsupported: '不支持', error: '检测失败', idle: '未测',
}

function browserStateOf(id) {
  return browserById[id] ? browserMap.value[id]?.state || 'idle' : 'unsupported'
}
function browserLabel(id) { return browserLabels[browserStateOf(id)] }
function browserKind(id) {
  return { reachable: 'ok', unknown: 'warn', timeout: 'warn' }[browserStateOf(id)] || 'muted'
}
function browserLatency(id) {
  const r = browserMap.value[id]
  return r?.state === 'reachable' ? latencyText(r.latency_ms) : ''
}
function serverStateOf(id) {
  const result = serverMap.value[id]
  return result?.extra?.reason === 'challenge' ? 'challenge' : result?.state || 'idle'
}
function serverLabel(id) { return serverLabels[serverStateOf(id)] || serverLabels.error }
function serverKind(id) {
  return { reachable: 'ok', unlocked: 'ok', blocked: 'danger', challenge: 'warn', unknown: 'warn', error: 'warn' }[serverStateOf(id)] || 'muted'
}
function serverSub(id) {
  const r = serverMap.value[id]
  if (!r) return ''
  return [r.region && `地区 ${r.region}`, r.latency_ms != null && latencyText(r.latency_ms),
    serverStateOf(id) === 'challenge' ? '' : r.detail].filter(Boolean).join(' · ')
}

function browserRouteLabel(id) {
  const route = browserMap.value[id]?.route
  return route?.ip ? `域名出口：${route.ip}${route.country ? ' · ' + route.country : ''}` : '未取得服务出口'
}

function routeLabel(id) {
  const route = serverMap.value[id]?.extra?.route
  if (route?.source === 'router_connection' && route.node) return `实际节点：${route.node}`
  if (route?.source === 'domain_trace' && route.ip) return `域名出口：${route.ip}${route.country ? ' · ' + route.country : ''}`
  return '未取得服务出口'
}
function routeTitle(id) {
  const route = serverMap.value[id]?.extra?.route
  return [route?.domain, route?.chain?.slice().reverse().join(' → ')].filter(Boolean).join(' · ')
}

function counts(labels, getState, states) {
  return states.map(state => ({ label: labels[state],
    count: catalog.value.filter(c => getState(c.id) === state).length }))
    .filter(item => item.count > 0)
}
const summaries = computed(() => [
  { title: '当前网络', ip: browserIp.value, checkedAt: browserCheckedAt.value,
    items: counts(browserLabels, browserStateOf, ['reachable', 'unknown', 'timeout', 'idle', 'unsupported']) },
  { title: '服务器网络', ip: serverIp.value, checkedAt: serverCheckedAt.value,
    items: counts(serverLabels, serverStateOf, ['reachable', 'unlocked', 'blocked', 'challenge', 'unknown', 'unsupported', 'error', 'idle']) },
])
const challengeCount = computed(() => catalog.value.filter(c => serverStateOf(c.id) === "challenge").length)
const browserReview = computed(() => catalog.value.filter(c =>
  ['unknown', 'timeout'].includes(browserStateOf(c.id))))
const exitHint = computed(() => {
  if (!browserIp.value.ip || !serverIp.value.ip) return ''
  if (browserIp.value.ip === serverIp.value.ip) {
    return '两边查询到的出口相同。各服务可能走不同线路。'
  }
  return '两边查询到的出口不同。结果仅代表各自检测时的线路。'
})

const hasResults = computed(() =>
  Object.keys(serverMap.value).length > 0 || Object.keys(browserMap.value).length > 0)

function maskIp(ip) {
  if (!ip) return ''
  const parts = ip.split('.')
  return parts.length === 4 ? `${parts[0]}.${parts[1]}.*.*` : ip.slice(0, 10) + '…'
}

async function loadCatalog() {
  const data = await api('/api/v1/unlock/catalog')
  catalog.value = data.checks || []
}

async function loadServerLast() {
  const entry = await api('/api/v1/unlock/last?exit=panel')
  if (entry && entry.results) {
    const map = {}
    for (const r of entry.results) map[r.id] = r
    serverMap.value = map
    serverIp.value = entry.ip || {}
    serverCheckedAt.value = entry.checked_at || null
  }
}

async function runServerChecks() {
  if (running.value) return
  running.value = true
  try {
    const entry = await api('/api/v1/unlock/run', {
      method: 'POST', body: { exit: 'panel', ids: [] },
    })
    const map = {}
    for (const r of entry.results || []) map[r.id] = r
    serverMap.value = map
    serverIp.value = entry.ip || {}
    serverCheckedAt.value = entry.checked_at || null
    ElMessage.success('服务器网络检测完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    running.value = false
  }
}

async function runBrowserChecks() {
  if (browserRunning.value) return
  browserRunning.value = true
  try {
    browserMap.value = {}
    browserIp.value = {}
    browserCheckedAt.value = null
    const ipRequest = probeExitIp()
    const checks = catalog.value.map(c => browserById[c.id]).filter(Boolean)
    await probeAll(checks, (r) => {
      browserMap.value = { ...browserMap.value, [r.id]: r }
    })
    browserIp.value = await ipRequest
    browserCheckedAt.value = Date.now()
    ElMessage.success('当前网络检测完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    browserRunning.value = false
  }
}

async function copyResults() {
  const lines = [`当前网络出口：${browserIp.value.ip || '未知'}`,
    `服务器网络出口：${serverIp.value.ip || '未知'}`]
  for (const c of catalog.value) {
    lines.push(`${c.name}：当前网络 ${browserLabel(c.id)}｜服务器网络 ${serverLabel(c.id)}`
      + `${serverSub(c.id) ? '（' + serverSub(c.id) + '）' : ''}`
      + (browserMap.value[c.id] ? '｜当前网络 ' + browserRouteLabel(c.id) : '')
      + (serverMap.value[c.id] ? '｜' + routeLabel(c.id) : ''))
  }
  try {
    await copyText(lines.join('\n'))
    ElMessage.success('已复制')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  try {
    await loadCatalog()
  } catch (e) {
    ElMessage.error(`检测目录加载失败：${e.message}`)
  }
  try {
    await loadServerLast()
  } catch (e) {
    ElMessage.error(`最近检测结果加载失败：${e.message}`)
  }
})

</script>

<style scoped>
.unlock-route { margin-top: 2px; font-size: 12px; color: var(--el-text-color-secondary); overflow-wrap: anywhere; }
.unlock-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.unlock-meta { font-size: 12.5px; color: var(--mp-text-secondary); }
.unlock-cols { display: flex; gap: 16px; flex-wrap: wrap; }
.unlock-col { flex: 1 1 260px; min-width: 240px; }
.unlock-col-head { font-size: 12.5px; color: var(--mp-text-secondary); margin-bottom: 8px; }
.unlock-col-body { display: flex; gap: 20px; flex-wrap: wrap; }
.unlock-col-body .cnt { font-size: 12.5px; color: var(--mp-text-secondary); }
.unlock-col-body .cnt b { font-size: 18px; color: var(--mp-text-primary); margin-right: 4px; }
.unlock-cat-count { color: var(--mp-muted); font-size: 12px; margin-left: 6px; }
.unlock-svc { display: inline-flex; align-items: center; gap: 6px; }
.unlock-icon-sm { font-size: 13px; }
.unlock-cell-sub { margin-left: 8px; font-size: 11.5px; color: var(--mp-muted); }
.unlock-link { color: inherit; text-decoration: none; }
.unlock-link:hover, .unlock-link:focus-visible { text-decoration: underline; }
.unlock-help { margin: 0 0 16px; }
.unlock-meta span + span { margin-left: 12px; }
</style>
