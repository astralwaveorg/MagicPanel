<template>
  <div>
    <h2 class="mp-page-title">网络体检</h2>
    <p class="mp-page-desc">从服务器按分流规则检测各服务的可达与解锁状态。</p>

    <div class="mp-card">
      <div class="unlock-toolbar">
        <el-button size="small" type="success" :loading="running"
                   @click="runServerChecks()">检测服务器网络</el-button>
        <el-button size="small" @click="openNodeCheck">检测指定节点</el-button>
        <el-button size="small" :disabled="!hasResults" @click="copyResults">复制结果</el-button>
      </div>
    </div>

    <div class="mp-card">
      <div class="unlock-cols">
        <div class="unlock-col">
          <div class="unlock-col-head">服务器网络</div>
          <div class="unlock-col-body">
            <span class="cnt" v-for="item in serverSummary" :key="item.label">
              <b>{{ item.count }}</b>{{ item.label }}
            </span>
          </div>
          <p v-if="serverCheckedAt || serverIp.ip" class="unlock-meta">
            <span v-if="serverIp.ip">参考出口 {{ maskIp(serverIp.ip) }} {{ serverIp.country }}</span>
            <span v-if="serverCheckedAt">最近检测 {{ fmtTime(serverCheckedAt) }}</span>
          </p>
        </div>
      </div>
      <p v-if="challengeCount" class="mp-form-hint">
        {{ challengeCount }} 项触发人机校验，可打开网页核实。
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
          <el-table-column label="服务器网络" min-width="240">
            <template #default="{ row }">
              <StatusDot :kind="serverKind(row.id)" :text="serverLabel(row.id)" />
              <span class="unlock-cell-sub"
                    :title="serverMap[row.id]?.checked_at ? fmtTime(serverMap[row.id].checked_at) : ''">{{ serverSub(row.id) }}</span>
              <div v-if="serverMap[row.id]" class="unlock-route" :title="routeTitle(row.id)">
                {{ routeLabel(row.id) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="86">
            <template #default="{ row }">
              <el-button link type="primary" size="small" :disabled="running"
                         :aria-label="`从服务器检测 ${row.name}`"
                         @click="runServerChecks([row.id])">检测</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <p class="mp-form-hint unlock-help">点服务名，打开网页验证登录或播放。</p>

    <el-dialog v-model="nodeDialog" title="检测指定节点" width="min(680px, 94vw)">
      <el-select v-model="nodeKey" @change="nodeResults = []" filterable placeholder="选择节点" aria-label="选择节点"
                 :loading="nodeLoading" :disabled="nodeRunning" style="width: 100%; margin-bottom: 8px">
        <el-option v-for="node in nodeOptions" :key="node.probe_key" :value="node.probe_key" :label="node.name" />
      </el-select>
      <el-select v-model="nodeServices" @change="nodeResults = []" multiple filterable placeholder="选择服务" aria-label="选择服务"
                 :disabled="nodeRunning" style="width: 100%">
        <el-option v-for="service in catalog" :key="service.id" :value="service.id" :label="service.name" />
      </el-select>
      <p class="mp-form-hint">这次检测只走所选节点。网页可达不代表可登录或播放。</p>
      <el-table v-if="nodeResults.length" :data="nodeResults" size="small">
        <el-table-column label="服务" prop="name" min-width="125" />
        <el-table-column label="结果" min-width="200">
          <template #default="{ row }">
            {{ row.state === 'unknown' && row.extra?.reason === 'challenge' ? '人机校验' : serverLabels[row.state] }}
            <span v-if="row.detail"> · {{ row.detail }}</span>
            <div class="unlock-route">{{ resultRouteLabel(row) }}</div>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" :loading="nodeRunning" :disabled="!nodeKey || !nodeServices.length"
                   @click="runNodeCheck">开始检测</el-button>
      </template>
    </el-dialog>

    <NodeQualityCard />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'
import { fmtTime, latencyText } from '../format'
import { copyText } from '../utils/clipboard'
import StatusDot from '../components/StatusDot.vue'
import NodeQualityCard from '../components/NodeQualityCard.vue'

const catalog = ref([])
const serverMap = ref({})
const serverIp = ref({})
const serverCheckedAt = ref(null)
const running = ref(false)
const nodeDialog = ref(false)
const nodeOptions = ref([])
const nodeKey = ref('')
const nodeServices = ref([])
const nodeResults = ref([])
const nodeLoading = ref(false)
const nodeRunning = ref(false)

const categories = [
  { id: 'ai', name: '海外 AI' },
  { id: 'stream', name: '流媒体' },
  { id: 'region', name: '服务地区检测' },
  { id: 'web', name: '网站服务' },
]

const siteById = computed(() =>
  Object.fromEntries(catalog.value.map(c => [c.id, c.url])))

function catItems(cid) { return catalog.value.filter(c => c.category === cid) }
const visibleCategories = computed(() => categories.filter(c => catItems(c.id).length > 0))
const serverLabels = {
  reachable: '网页可达', unlocked: '已确认', blocked: '访问受限',
  challenge: '人机校验', unknown: '无法确认', unsupported: '不支持', error: '检测失败', idle: '未测',
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

function routeLabel(id) {
  return resultRouteLabel(serverMap.value[id])
}
function resultRouteLabel(result) {
  const route = result?.extra?.route
  if (['router_connection', 'probe_connection'].includes(route?.source) && route.node) return `实际节点：${route.node}`
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
const serverSummary = computed(() =>
  counts(serverLabels, serverStateOf, ['reachable', 'unlocked', 'blocked', 'challenge', 'unknown', 'unsupported', 'error', 'idle']))
const challengeCount = computed(() => catalog.value.filter(c => serverStateOf(c.id) === "challenge").length)

const hasResults = computed(() => Object.keys(serverMap.value).length > 0)

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

async function runServerChecks(ids = []) {
  if (running.value) return
  running.value = true
  try {
    const entry = await api('/api/v1/unlock/run', {
      method: 'POST', body: { exit: 'panel', ids },
    })
    const map = ids.length ? { ...serverMap.value } : {}
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

async function openNodeCheck() {
  nodeDialog.value = true
  if (nodeOptions.value.length || nodeLoading.value) return
  nodeLoading.value = true
  try {
    const data = await api('/api/v1/unlock/quality')
    nodeOptions.value = (data.items || []).filter(node => node.probe_key)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    nodeLoading.value = false
  }
}

async function runNodeCheck() {
  if (nodeRunning.value) return
  nodeRunning.value = true
  nodeResults.value = []
  try {
    const entry = await api('/api/v1/unlock/run', {
      method: 'POST', body: { exit: nodeKey.value, ids: nodeServices.value },
    })
    const names = Object.fromEntries(catalog.value.map(service => [service.id, service.name]))
    nodeResults.value = (entry.results || []).map(row => ({ ...row, name: names[row.id] || row.id }))
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    nodeRunning.value = false
  }
}

async function copyResults() {
  const lines = [`服务器网络出口：${serverIp.value.ip || '未知'}`]
  for (const c of catalog.value) {
    lines.push(`${c.name}：${serverLabel(c.id)}`
      + `${serverSub(c.id) ? '（' + serverSub(c.id) + '）' : ''}`
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
