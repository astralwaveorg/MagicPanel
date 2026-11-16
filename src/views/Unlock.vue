<template>
  <div>
    <h2 class="mp-page-title">网络体检</h2>
    <p class="mp-page-desc">
      检测当前出口能否解锁海外 AI 与流媒体。支持「面板出口」（路由器代理链真实出口）
      与「指定节点」（用测速核心临时起一个只含该节点的实例）两种模式；点卡片可单项重测。
    </p>

    <div class="mp-card">
      <div class="unlock-toolbar">
        <el-select v-model="exit" style="width:280px" size="small" filterable
                   :disabled="running || browserRunning">
          <el-option label="面板出口（路由器代理链）" value="panel" />
          <el-option v-for="n in nodeOptions" :key="n" :label="'节点：' + n" :value="n" />
        </el-select>
        <el-button size="small" type="primary" :loading="running" @click="runAll">全部检测</el-button>
        <el-button size="small" :disabled="!hasResults" @click="copyResults">复制结果</el-button>
        <span v-if="lastRun" class="unlock-meta">
          {{ exitLabel }} · {{ new Date(lastRun.checked_at * 1000).toLocaleString() }}
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
          <h3>本机浏览器出口</h3>
          <p v-if="localIp" class="mono">{{ localIp }}</p>
          <p class="mp-form-hint">
            本机检测用浏览器直连第三方查询服务，反映「你访问面板这台设备」的网络；
            面板出口检测反映路由器代理链。两者不同时显示对比。
          </p>
          <el-button size="small" :loading="browserRunning" @click="checkLocal">查询本机出口</el-button>
        </div>
      </div>
    </div>

    <div v-for="cat in categories" :key="cat.id" class="mp-card">
      <h3>{{ cat.name }} <span class="unlock-cat-count">{{ catItems(cat.id).length }}</span></h3>
      <div class="unlock-grid">
        <div v-for="c in catItems(cat.id)" :key="c.id" class="unlock-card"
             :class="'st-' + stateOf(c.id)" :title="detailOf(c.id)"
             @click="runOne(c.id)">
          <div class="unlock-icon">{{ c.icon }}</div>
          <div class="unlock-info">
            <b>{{ c.name }}</b>
            <span class="unlock-state">{{ stateLabel(c.id) }}</span>
            <span class="unlock-sub" v-if="regionOf(c.id)">片源地区：{{ regionOf(c.id) }}</span>
            <span class="unlock-sub" v-else-if="latencyOf(c.id)">{{ latencyOf(c.id) }}ms</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

const exit = ref('panel')
const nodeOptions = ref([])
const catalog = ref([])
const lastRun = ref(null)
const running = ref(false)
const localIp = ref('')
const browserRunning = ref(false)

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
           error: '异常', idle: '未测' }[state] || '未测'
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

async function copyResults() {
  const lines = [`出口：${exitLabel.value}`, ...catalog.value.map(c => {
    const r = stateMap.value[c.id]
    if (!r) return `${c.name}: 未测`
    const extra = [r.region && `地区 ${r.region}`, `${r.latency_ms}ms`, r.detail].filter(Boolean).join('，')
    return `${c.name}: ${labelFor(r.state)}${extra ? '（' + extra + '）' : ''}`
  })]
  await navigator.clipboard.writeText(lines.join('\n'))
  ElMessage.success('已复制')
}

async function checkLocal() {
  browserRunning.value = true
  try {
    const r = await fetch('https://ipapi.co/json/', { cache: 'no-store' })
    const d = await r.json()
    localIp.value = `${d.ip} ${d.country_name || d.country || ''} ${d.org || ''}`.trim()
  } catch {
    localIp.value = '查询失败（本机网络或第三方服务不可用）'
  } finally {
    browserRunning.value = false
  }
}

function maskIp(ip) {
  if (!ip) return ''
  const parts = ip.split('.')
  return parts.length === 4 ? `${parts[0]}.${parts[1]}.*.*` : ip.slice(0, 10) + '…'
}

onMounted(async () => {
  const cat = await api('/api/v1/unlock/catalog')
  catalog.value = cat.checks
  await loadLast()
  loadNodes()
})
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
.unlock-icon { font-size: 22px; width: 34px; text-align: center; }
.unlock-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.unlock-info b { font-size: 13px; }
.unlock-state { font-size: 12px; color: var(--mp-text-secondary); }
.unlock-sub { font-size: 11.5px; color: var(--mp-text-secondary); }
.unlock-cat-count { font-size: 12px; color: var(--mp-text-secondary); }
@media (max-width: 768px) {
  .unlock-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  .unlock-summary { gap: 14px; }
  .unlock-ring { width: 76px; height: 76px; }
}
</style>
