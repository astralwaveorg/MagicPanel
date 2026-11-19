<template>
  <div>
    <h2 class="mp-page-title">网络体检</h2>
    <p class="mp-page-desc">
      右列：服务器网络。面板所在机器经路由器代理链的出口，判断服务是否解锁，
      以此为准。
      <br />左列：当前网络。打开本页的这台设备直连服务，只反映能否连上。
      <br />浏览器无法自动判定跨域重定向与带 <code>X-Frame-Options</code> 的站点，
      这类结果可能与实际不符，可用终端 curl 复核。
    </p>

    <div class="mp-card">
      <div class="unlock-toolbar">
        <el-button size="small" type="success" :loading="running"
                   @click="runServerChecks">检测服务器网络</el-button>
        <el-button size="small" type="success" :loading="browserRunning"
                   @click="runBrowserChecks">检测当前网络</el-button>
        <el-button size="small" :disabled="!hasResults" @click="copyResults">复制结果</el-button>
        <span class="unlock-meta">
          服务器网络<span v-if="serverIp.ip" class="mono">
            · 出口 {{ maskIp(serverIp.ip) }} {{ serverIp.country }}</span>
          <span v-if="browserIp.ip" class="mono">
            · 当前网络 {{ maskIp(browserIp.ip) }} {{ browserIp.country }}</span>
        </span>
      </div>
    </div>

    <div class="mp-card">
      <div class="unlock-summary">
        <div class="unlock-cols">
          <div class="unlock-col">
            <div class="unlock-col-head">当前网络（这台设备）</div>
            <div class="unlock-col-body">
              <div class="cnt ok"><b>{{ browserCount('reachable') }}</b>可达</div>
              <div class="cnt bad"><b>{{ browserCount('unreachable') }}</b>不可达</div>
              <div class="cnt warn"><b>{{ browserCount('timeout') }}</b>超时</div>
              <div class="cnt idle"><b>{{ browserCount('idle') }}</b>未测</div>
            </div>
          </div>
          <div class="unlock-col">
            <div class="unlock-col-head">服务器网络（面板出口）</div>
            <div class="unlock-col-body">
              <div class="cnt ok"><b>{{ serverCount('unlocked') }}</b>解锁</div>
              <div class="cnt bad"><b>{{ serverCount('blocked') }}</b>区域拒绝</div>
              <div class="cnt bad"><b>{{ serverCount('unsupported') }}</b>不支持</div>
              <div class="cnt warn"><b>{{ serverCount('error') }}</b>异常</div>
              <div class="cnt idle"><b>{{ serverCount('idle') }}</b>未测</div>
            </div>
          </div>
        </div>
      </div>
      <el-alert v-if="mismatches.length" type="warning" :closable="false" show-icon
                style="margin-top:12px"
                :title="`${mismatches.length} 项服务两边结论不一致`">
        <div class="mp-form-hint">
          {{ mismatchHint }}
        </div>
      </el-alert>
      <p v-if="unknownServer.length" class="mp-form-hint" style="margin-top:8px">
        另有 {{ unknownServer.length }} 项（{{ unknownServer.map(c => c.name).join('、') }}）
        在服务器侧无法判定，可能是 Cloudflare 人机校验，也可能该服务不支持当前出口地区。
        这类结果不计入上面的不一致。
      </p>
    </div>

    <div v-for="cat in categories" :key="cat.id" class="mp-card">
      <h3>{{ cat.name }} <span class="unlock-cat-count">{{ catItems(cat.id).length }}</span></h3>
      <div class="mp-table-wrap">
        <el-table :data="catItems(cat.id)" size="small" class="unlock-table">
          <el-table-column label="服务" min-width="180">
            <template #default="{ row }">
              <span class="unlock-svc"><span class="unlock-icon-sm">{{ row.icon }}</span>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="当前网络（这台设备）" min-width="190">
            <template #default="{ row }">
              <StatusDot :kind="browserKind(row.id)" :text="browserLabel(row.id)" />
              <span class="unlock-cell-sub">{{ browserLatency(row.id) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="服务器网络（面板出口）" min-width="190">
            <template #default="{ row }">
              <StatusDot :kind="serverKind(row.id)" :text="serverLabel(row.id)" />
              <span class="unlock-cell-sub">{{ serverSub(row.id) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="对照" width="120">
            <template #default="{ row }">
              <span v-if="mismatchOf(row.id)" class="unlock-mismatch">不一致</span>
              <span v-else-if="browserStateOf(row.id) !== 'idle' && serverStateOf(row.id) !== 'idle'"
                    class="unlock-match">一致</span>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>节点能力（构建期产物里的节点名徽章）</h3>
      <p class="mp-form-hint">
        节点的解锁能力在<b>构建流程</b>里测：构建时按已有检测结果给节点分类并重命名
        （🔓 AI 全解锁 / 🎬 流媒体解锁 / 📺 Netflix 高级版），构建完成后自动补测缺失的节点，
        补测完成再构建一次，产物里的节点名就带上能力标记。
      </p>
      <p v-if="coverage" class="mp-form-hint">
        能力数据覆盖：{{ coverage.covered }} / {{ coverage.total }} 个节点
        <span v-if="coverage.missing">（还缺 {{ coverage.missing }} 个，构建后会自动补测）</span>
      </p>
      <p v-if="batch && batch.total" class="mp-form-hint">
        {{ batch.running ? `补测进行中 ${batch.done}/${batch.total}：${batch.current}`
           : `上次补测完成 ${batch.done}/${batch.total}，其中 ${batch.unlocked} 个有能力标记` }}
      </p>
      <el-button size="small" type="success" :loading="batchStarting"
                 :disabled="batch && batch.running"
                 @click="startBatch">补测下一批节点</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'
import { fmtTime } from '../format'
import { copyText } from '../utils/clipboard'
import { BROWSER_CHECKS, probeAll, probeExitIp } from '../utils/browserChecks'
import StatusDot from '../components/StatusDot.vue'

const catalog = ref([])
const serverMap = ref({})
const browserMap = ref({})
const serverIp = ref({})
const browserIp = ref({})
const running = ref(false)
const browserRunning = ref(false)
const batchStarting = ref(false)
const batch = ref(null)
const coverage = ref(null)
let batchTimer = null

const categories = [
  { id: 'ai', name: '海外 AI' },
  { id: 'stream', name: '流媒体' },
  { id: 'region', name: '服务地区检测' },
  { id: 'web', name: '网站服务' },
]

const browserChecks = BROWSER_CHECKS

function catItems(cid) { return catalog.value.filter(c => c.category === cid) }

// ---- 当前网络（浏览器端）----
function browserStateOf(id) {
  return (browserMap.value[id] || {}).state || 'idle'
}
function browserLabel(id) {
  const s = browserStateOf(id)
  return { reachable: '可达', unreachable: '不可达', timeout: '超时' }[s] || '未测'
}
function browserKind(id) {
  const s = browserStateOf(id)
  return { reachable: 'ok', unreachable: 'bad', timeout: 'warn' }[s] || 'muted'
}
function browserLatency(id) {
  const r = browserMap.value[id]
  return r && r.latency_ms ? `${r.latency_ms}ms` : ''
}
function browserCount(state) {
  return Object.values(browserMap.value).filter(r => r.state === state).length
}

// ---- 服务器网络（面板出口）----
function serverStateOf(id) {
  return (serverMap.value[id] || {}).state || 'idle'
}
function serverLabel(id) {
  const s = serverStateOf(id)
  return { unlocked: '解锁', blocked: '区域拒绝', unsupported: '不支持',
           error: '异常' }[s] || '未测'
}
function serverKind(id) {
  const s = serverStateOf(id)
  return { unlocked: 'ok', blocked: 'bad', unsupported: 'muted',
           error: 'warn' }[s] || 'muted'
}
function serverSub(id) {
  const r = serverMap.value[id]
  if (!r) return ''
  const bits = []
  if (r.region) bits.push(`地区 ${r.region}`)
  if (r.latency_ms) bits.push(`${r.latency_ms}ms`)
  if (r.detail) bits.push(r.detail)
  return bits.join(' · ')
}
function serverCount(state) {
  return Object.values(serverMap.value).filter(r => r.state === state).length
}

// ---- 对照 ----
// 当前网络「不可达」而服务器网络「解锁」：服务器能走通但你这台设备走不通，
// 说明该服务的分流没把你的设备送进代理链（客户端规则缺失或被直连规则抢先）。
function mismatchOf(id) {
  const b = browserStateOf(id)
  const s = serverStateOf(id)
  if (b === 'idle' || s === 'idle') return false
  // 右列是「解锁判定」，左列是「网络可达」——语义不同。
  // 右列若无法判定（Cloudflare 人机校验等），不是两边结论不一致，
  // 只是服务器侧没测出结果，不该报成"分流问题"。
  if (s !== 'unlocked' && s !== 'blocked' && s !== 'unsupported') return false
  const bOk = b === 'reachable'
  const sOk = s === 'unlocked'
  return bOk !== sOk
}
const mismatches = computed(() => catalog.value.filter(c => mismatchOf(c.id)))
const mismatchHint = computed(() => {
  const onlyServer = mismatches.value.filter(c =>
    browserStateOf(c.id) !== 'reachable' && serverStateOf(c.id) === 'unlocked')
  const onlyBrowser = mismatches.value.filter(c =>
    browserStateOf(c.id) === 'reachable' && serverStateOf(c.id) !== 'unlocked')
  const parts = []
  if (onlyServer.length) {
    parts.push(`${onlyServer.length} 项服务在服务器网络可解锁，当前网络连不上。`
      + '先在这台设备的终端复核，能返回状态码即说明网络可达，'
      + '只是浏览器的跨域策略测不出来：'
      + `curl -sI -m 8 ${onlyServer[0].url || ''} | head -1`)
  }
  if (onlyBrowser.length) {
    parts.push(`${onlyBrowser.length} 项服务当前网络可连，服务器出口不可用，`
      + '通常是出口 IP 被该服务限制')
  }
  return parts.join('；')
})

// 右列无法判定的服务（Cloudflare 人机校验等）：不算不一致，但要单独提示
const unknownServer = computed(() => catalog.value.filter(c => {
  const s = serverStateOf(c.id)
  return s === 'error' || s === 'unsupported'
}))

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
  }
}

async function loadCoverage() {
  try {
    coverage.value = await api('/api/v1/unlock/capability-coverage')
  } catch { /* 覆盖率只是提示信息 */ }
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
    probeExitIp().then((r) => { browserIp.value = r })
    await probeAll(browserChecks, (r) => {
      browserMap.value = { ...browserMap.value, [r.id]: r }
    })
    ElMessage.success('当前网络检测完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    browserRunning.value = false
  }
}

async function refreshBatch() {
  try {
    batch.value = await api('/api/v1/unlock/batch-status')
    if (batch.value?.running) {
      if (!batchTimer) batchTimer = setInterval(refreshBatch, 2000)
    } else if (batchTimer) {
      clearInterval(batchTimer)
      batchTimer = null
      loadCoverage()
    }
  } catch { /* 进度非关键 */ }
}

async function startBatch() {
  if (batchStarting.value) return
  batchStarting.value = true
  try {
    await api('/api/v1/unlock/batch-detect', { method: 'POST', body: { qty: 3 } })
    ElMessage.success('补测已启动，后台进行中')
    refreshBatch()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchStarting.value = false
  }
}

async function copyResults() {
  const lines = [`当前网络出口：${browserIp.value.ip || '未知'}`,
    `服务器网络出口：${serverIp.value.ip || '未知'}`]
  for (const c of catalog.value) {
    lines.push(`${c.name}：当前网络 ${browserLabel(c.id)}｜服务器网络 ${serverLabel(c.id)}`
      + `${serverSub(c.id) ? '（' + serverSub(c.id) + '）' : ''}`
      + `${mismatchOf(c.id) ? ' ⚠不一致' : ''}`)
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
  loadCoverage()
  refreshBatch()
})

onUnmounted(() => { if (batchTimer) clearInterval(batchTimer) })
</script>

<style scoped>
.unlock-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.unlock-meta { font-size: 12.5px; color: var(--mp-text-secondary); }
.unlock-summary { display: flex; flex-direction: column; gap: 12px; }
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
.unlock-mismatch { color: var(--el-color-danger); font-weight: 600; font-size: 12px; }
.unlock-match { color: var(--el-color-success); font-size: 12px; }
</style>
