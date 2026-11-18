<template>
  <div>
    <h2 class="mp-page-title">网络体检</h2>
    <p class="mp-page-desc">
      两个视角分开看：<b>面板出口</b>（路由器代理链真实出口，含指定节点模式）检测
      「能不能解锁」；<b>你的网络</b>（打开本页的这台设备）检测「能不能连上」。
      两者不一致时，多半是该域名的分流没把你的设备送进代理链。点卡片可单项重测。
    </p>

    <div class="mp-card">
      <div class="unlock-toolbar">
        <el-select v-model="exit" style="width:280px" size="small" filterable
                   :disabled="running || browserRunning">
          <el-option label="面板出口（路由器代理链）" value="panel" />
          <el-option v-for="n in nodeOptions" :key="n" :label="'节点：' + n" :value="n" />
        </el-select>
        <el-button size="small" type="success" :loading="running" @click="runAll">全部检测</el-button>
        <el-button size="small" :disabled="!hasResults" @click="copyResults">复制结果</el-button>
        <span v-if="lastRun" class="unlock-meta">
          {{ exitLabel }} · {{ fmtTime(lastRun.checked_at) }}
          <span v-if="lastRun.ip && lastRun.ip.ip" class="mono">
            · 出口 {{ maskIp(lastRun.ip.ip) }} {{ lastRun.ip.country }} {{ lastRun.ip.org }}
          </span>
        </span>
      </div>
    </div>

    <div class="mp-card">
      <div class="unlock-summary">
        <svg viewBox="0 0 100 100" class="unlock-ring">
          <circle cx="50" cy="50" r="42" class="ring-bg" />
          <circle cx="50" cy="50" r="42" class="ring-fg"
                  :stroke-dasharray="ringDash" transform="rotate(-90 50 50)" />
          <text x="50" y="58" text-anchor="middle" class="ring-text">{{ unlockRate }}%</text>
        </svg>
        <div class="unlock-counts">
          <div class="cnt ok"><b>{{ countBy('unlocked') }}</b>解锁</div>
          <div class="cnt bad"><b>{{ countBy('blocked') + countBy('unsupported') }}</b>不支持</div>
          <div class="cnt warn"><b>{{ countBy('error') }}</b>异常</div>
          <div class="cnt idle"><b>{{ countBy('idle') }}</b>未测</div>
        </div>
        <div class="unlock-local">
          <h3>你的网络（浏览器端）</h3>
          <p v-if="browserIp.ip" class="mono">
            出口 {{ browserIp.ip }} {{ browserIp.country }}
          </p>
          <p v-if="browserDone" class="mp-form-hint">
            可达 {{ browserCount('reachable') }} / {{ browserChecks.length }}
            · 超时 {{ browserCount('timeout') }} · 不可达 {{ browserCount('unreachable') }}
          </p>
          <p class="mp-form-hint">
            在你打开面板的这台设备上逐项探测（no-cors，不读内容，只判可达）；
            面板出口测的是路由器代理链。两者对照才说明分流是否把你送对了路。
          </p>
          <el-button size="small" type="success" :loading="browserRunning"
                     @click="runBrowserChecks">在你的网络里逐项检测</el-button>
        </div>
        <div class="unlock-local">
          <h3>节点解锁批量检测</h3>
          <p class="mp-form-hint">
            对全部节点逐个检测 AI 六项（Gemini/ChatGPT/Claude/Grok/Perplexity/Copilot），
            AI 全部解锁的节点会在重命名时带 🔓 徽章（需在设置里开启
            「解锁徽章」）。每节点约 15-20 秒，按批后台进行。
          </p>
          <p v-if="batch && batch.total" class="mp-form-hint">
            {{ batch.running ? `进行中 ${batch.done}/${batch.total}：${batch.current}` :
               `上次完成 ${batch.done}/${batch.total}，AI 全解锁 ${batch.unlocked} 个` }}
          </p>
          <el-button size="small" type="success" :loading="batchStarting"
                     :disabled="batch && batch.running"
                     @click="startBatch">检测下一批（3 个）</el-button>
        </div>
      </div>
    </div>

    <div v-for="cat in categories" :key="cat.id" class="mp-card">
      <h3>{{ cat.name }} <span class="unlock-cat-count">{{ catItems(cat.id).length }}</span></h3>
      <div class="unlock-grid">
        <div v-for="c in catItems(cat.id)" :key="c.id" class="unlock-card"
             :class="['st-' + stateOf(c.id), { 'is-testing': stateOf(c.id) === 'testing' }]" :title="detailOf(c.id)"
             @click="runOne(c.id)">
          <div class="unlock-icon">{{ c.icon }}</div>
          <div class="unlock-info">
            <b>{{ c.name }}</b>
            <span class="unlock-state">{{ stateLabel(c.id) }}</span>
            <span class="unlock-sub" v-if="regionOf(c.id)">片源地区：{{ regionOf(c.id) }}</span>
            <span class="unlock-sub" v-else-if="latencyOf(c.id)">{{ latencyOf(c.id) }}ms</span>
            <span class="unlock-sub" :class="{ 'browser-mismatch': browserMismatch(c.id) }"
                  v-if="browserStateOf(c.id) !== 'idle'">
              你的网络：{{ browserLabel(c.id) }}{{ browserLatency(c.id) }}
            </span>
          </div>
        </div>
      </div>
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

// 节点解锁批量检测：进度轮询（发起后每 2 秒查一次直到完成）
const batch = ref(null)
const batchStarting = ref(false)
let batchTimer = null

async function refreshBatch() {
  try {
    batch.value = await api('/api/v1/unlock/batch-status')
    if (batch.value?.running) {
      if (!batchTimer) batchTimer = setInterval(refreshBatch, 2000)
    } else if (batchTimer) {
      clearInterval(batchTimer)
      batchTimer = null
    }
  } catch { /* 静默：进度非关键信息 */ }
}

async function startBatch() {
  if (batchStarting.value) return
  batchStarting.value = true
  try {
    await api('/api/v1/unlock/batch-detect', { method: 'POST', body: { qty: 3 } })
    ElMessage.success('批量检测已启动，后台进行中')
    refreshBatch()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchStarting.value = false
  }
}

const exit = ref('panel')
const nodeOptions = ref([])
const catalog = ref([])
const lastRun = ref(null)
const running = ref(false)
const browserRunning = ref(false)
// 「你的网络」视角：浏览器端逐项探测结果与出口 IP
const browserChecks = BROWSER_CHECKS
const browserMap = ref({})
const browserIp = ref({})
const browserDone = ref(false)
const browserChecksLoaded = ref(false)

async function runBrowserChecks() {
  if (browserRunning.value) return
  browserRunning.value = true
  browserChecksLoaded.value = true
  browserDone.value = false
  try {
    probeExitIp().then((r) => { browserIp.value = r })
    await probeAll(browserChecks, (r) => { browserMap.value = { ...browserMap.value, [r.id]: r } })
    browserDone.value = true
    ElMessage.success('你的网络检测完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    browserRunning.value = false
  }
}

function browserStateOf(id) {
  if (!browserChecksLoaded.value) return 'idle'
  return (browserMap.value[id] || {}).state || 'idle'
}
function browserLabel(id) {
  return { reachable: '可达', unreachable: '不可达', timeout: '超时' }[browserStateOf(id)] || '未测'
}
function browserLatency(id) {
  const r = browserMap.value[id]
  return r && r.latency_ms ? ` · ${r.latency_ms}ms` : ''
}
function browserCount(state) {
  return Object.values(browserMap.value).filter((r) => r.state === state).length
}
function browserMismatch(id) {
  // 面板出口解锁、你的设备却连不上 → 分流没把你送进代理链
  return stateOf(id) === 'unlocked'
    && ['unreachable', 'timeout'].includes(browserStateOf(id))
}

const categories = [
  { id: 'ai', name: '海外 AI' },
  { id: 'stream', name: '流媒体' },
  { id: 'region', name: '服务地区检测' },
  { id: 'web', name: '网站服务' },
]

const nodeOptionsLoaded = ref(false)
async function loadNodes() {
  if (nodeOptionsLoaded.value) return
  try {
    const data = await api('/api/v1/nodes?limit=200')
    nodeOptions.value = [...new Set(data.items.map(i => i.emit_name).filter(Boolean))]
    nodeOptionsLoaded.value = true
  } catch { /* 忽略：选择器留空也能用面板出口 */ }
}

const stateMap = ref({})
const hasResults = computed(() => Object.keys(stateMap.value).length > 0)
function stateOf(id) {
  const r = stateMap.value[id]
  return r ? r.state : 'idle'
}
function labelFor(state) {
  return { unlocked: '解锁', blocked: '区域拒绝', unsupported: '不支持',
           error: '异常', idle: '未测', testing: '检测中…' }[state] || '未测'
}
function stateLabel(id) { return labelFor(stateOf(id)) }
function resultOf(id) { return stateMap.value[id] || {} }
function regionOf(id) { return resultOf(id).region || '' }
function latencyOf(id) { const l = resultOf(id).latency_ms; return l ? l : '' }
function detailOf(id) {
  const r = stateMap.value[id]
  if (!r) return ''
  const bits = [`HTTP ${r.status ?? '-'}`]
  if (r.detail) bits.push(r.detail)
  return bits.join(' · ')
}
function countBy(state) {
  if (state === 'idle') {
    return catalog.value.length - Object.keys(stateMap.value).length
  }
  return Object.values(stateMap.value).filter(r => r.state === state).length
}
const unlockRate = computed(() => {
  const done = catalog.value.length - countBy('idle')
  if (!done) return 0
  return Math.round((countBy('unlocked') / done) * 100)
})
const ringDash = computed(() => `${(unlockRate.value / 100) * 264} 264`)
const exitLabel = computed(() =>
  exit.value === 'panel' ? '面板出口' : `节点 ${exit.value}`)

function catItems(cid) { return catalog.value.filter(c => c.category === cid) }

function applyEntry(entry) {
  lastRun.value = entry
  const map = {}
  for (const r of entry.results || []) map[r.id] = r
  stateMap.value = map
}

async function loadLast() {
  const entry = await api(`/api/v1/unlock/last?exit=${encodeURIComponent(exit.value)}`)
  if (entry && entry.results) applyEntry(entry)
}

async function run(ids) {
  running.value = true
  try {
    const entry = await api('/api/v1/unlock/run', {
      method: 'POST', body: { exit: exit.value, ids },
    })
    applyEntry(entry)
    ElMessage.success(ids?.length ? '检测完成' : `检测完成：解锁 ${countBy('unlocked')} / ${catalog.value.length}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    running.value = false
  }
}
function runAll() { run([]) }
function runOne(id) { run([id]) }

// 复制统一走 utils/clipboard（2026-11-18 收拢）

async function copyResults() {
  const lines = [`出口：${exitLabel.value}`, ...catalog.value.map(c => {
    const r = stateMap.value[c.id]
    const b = browserMap.value[c.id]
    const browser = browserChecksLoaded.value
      ? `｜你的网络：${{ reachable: '可达', unreachable: '不可达', timeout: '超时' }[b?.state] || '未测'}`
      : ''
    if (!r) return `${c.name}: 未测${browser}`
    const extra = [r.region && `地区 ${r.region}`, `${r.latency_ms}ms`, r.detail].filter(Boolean).join('，')
    return `${c.name}: ${labelFor(r.state)}${extra ? '（' + extra + '）' : ''}${browser}`
  })]
  try {
    await copyText(lines.join('\n'))
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败：浏览器拒绝了剪贴板权限，请手动选择文本复制')
  }
}


function maskIp(ip) {
  if (!ip) return ''
  const parts = ip.split('.')
  return parts.length === 4 ? `${parts[0]}.${parts[1]}.*.*` : ip.slice(0, 10) + '…'
}

onMounted(async () => {
  try {
    const cat = await api('/api/v1/unlock/catalog')
    catalog.value = cat.checks
  } catch (e) {
    ElMessage.error(`检测目录加载失败：${e.message}`)
  }
  try {
    await loadLast()
  } catch (e) {
    ElMessage.error(`最近检测结果加载失败：${e.message}`)
  }
  loadNodes()
  refreshBatch()
})

onUnmounted(() => { if (batchTimer) clearInterval(batchTimer) })
</script>

<style scoped>
.unlock-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.unlock-meta { font-size: 12.5px; color: var(--mp-text-secondary); }
.unlock-summary { display: flex; gap: 24px; align-items: center; flex-wrap: wrap; }
.unlock-ring { width: 96px; height: 96px; }
.ring-bg { fill: none; stroke: var(--mp-border, #444); stroke-width: 10; }
.ring-fg { fill: none; stroke: var(--el-color-success); stroke-width: 10;
          transition: stroke-dasharray .4s; }
.ring-text { font-size: 22px; fill: var(--mp-text, #eee); }
.unlock-counts { display: flex; gap: 16px; }
.cnt { text-align: center; font-size: 12px; color: var(--mp-text-secondary); }
.cnt b { display: block; font-size: 22px; }
.cnt.ok b { color: var(--el-color-success); }
.cnt.bad b { color: var(--el-color-danger); }
.cnt.warn b { color: var(--el-color-warning); }
.unlock-local { flex: 1; min-width: 240px; }
.unlock-local h3 { margin: 0 0 6px; font-size: 14px; }
.unlock-local p { margin: 4px 0 10px; font-size: 13px; }
.unlock-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; }
.unlock-card { display: flex; gap: 10px; padding: 10px; border: 1px solid var(--mp-border, #333);
               border-radius: 8px; cursor: pointer; align-items: center; transition: border-color .2s; }
.unlock-card:hover { border-color: var(--el-color-primary); }
.unlock-card.st-unlocked { border-left: 3px solid var(--el-color-success); }
.unlock-card.st-blocked, .unlock-card.st-unsupported { border-left: 3px solid var(--el-color-danger); }
.unlock-card.st-error { border-left: 3px solid var(--el-color-warning); }
.unlock-card.is-testing { opacity: .55; pointer-events: none; }
.unlock-icon { font-size: 22px; width: 34px; text-align: center; }
.unlock-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.unlock-info b { font-size: 13px; }
.unlock-state { font-size: 12px; color: var(--mp-text-secondary); }
.unlock-sub { font-size: 11.5px; color: var(--mp-text-secondary); }
.unlock-sub.browser-mismatch { color: var(--el-color-danger); font-weight: 600; }
.unlock-cat-count { font-size: 12px; color: var(--mp-text-secondary); }
@media (max-width: 768px) {
  .unlock-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  .unlock-summary { gap: 14px; }
  .unlock-ring { width: 76px; height: 76px; }
}
</style>
