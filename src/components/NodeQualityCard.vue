<template>
  <section class="mp-card">
    <h3>节点质量</h3>
    <p class="mp-form-hint">
      从服务器测速。延迟低于 {{ thresholds.delay_ms }} ms、下载达到 {{ speedText(thresholds.speed_bps) }} 的节点才检测 AI 和流媒体。
    </p>
    <el-collapse v-if="quality.routing_candidates">
      <el-collapse-item title="分流候选" name="routing-candidates">
        <p class="mp-form-hint">只列有近期通过记录的节点。这里的结果不会自动改变分流。</p>
        <dl class="quality-details">
          <template v-for="(pool, id) in quality.routing_candidates" :key="id">
            <dt>{{ id === 'netflix' ? 'Netflix 日本 · 非自制剧样本' : (quality.platforms?.[id] || id) }}</dt>
            <dd v-if="pool.count">{{ pool.nodes.join('、') }}<span v-if="pool.count > pool.nodes.length"> 等 {{ pool.count }} 条</span></dd>
            <dd v-else>暂无确认通过的节点</dd>
          </template>
        </dl>
      </el-collapse-item>
    </el-collapse>
    <div class="quality-actions">
      <el-button size="small" type="success" :loading="busy" :disabled="loading || quality.task?.running" @click="run">
        测下一批
      </el-button>
      <el-button size="small" :disabled="loading" @click="load">刷新结果</el-button>
      <el-button size="small" :disabled="!quality.counts?.probed" :loading="exporting" @click="download">
        导出达标节点
      </el-button>
      <el-button size="small" :disabled="loading || !!loadError" @click="editSettings">检测设置</el-button>
      <el-switch aria-label="自动检测" :model-value="quality.auto" :disabled="loading || saving || !!loadError"
                 @change="toggleAuto" />
      <span>{{ autoState }}</span>
    </div>
    <p v-if="loadError" role="alert" class="mp-form-hint">{{ loadError }}</p>
    <p v-else-if="quality.task?.running" class="mp-form-hint">正在检测，完成后会更新列表。</p>
    <p v-else-if="quality.task?.last?.error" class="mp-form-hint">{{ quality.task.last.error }}</p>
    <p v-else-if="quality.task?.last?.skipped" class="mp-form-hint">{{ quality.task.last.skipped }}</p>
    <div v-if="items.length" class="quality-filters">
      <el-select v-model="filter" size="small" aria-label="筛选节点">
        <el-option v-for="option in filters" :key="option.id" :label="option.label" :value="option.id" />
      </el-select>
      <span class="mp-form-hint">{{ filtered.length }} 个节点</span>
    </div>
    <div v-if="items.length" class="mp-table-wrap">
      <el-table :data="visible" size="small" empty-text="没有符合条件的节点">
        <el-table-column type="expand">
          <template #default="{ row }">
            <p v-if="!Object.keys(row.probes || {}).length" class="mp-form-hint">{{ row.reason || '还没有平台检测结果。' }}</p>
            <dl v-else class="quality-details">
              <div v-for="(probe, id) in row.probes" :key="id">
                <dt>{{ quality.platforms?.[id] || id }}</dt>
                <dd>{{ platformLabels[probe.state] || '未确认' }}<span v-if="probe.region"> · {{ probe.region }}</span>
                  <span v-if="probe.detail"> · {{ probe.detail }}</span>
                </dd>
              </div>
            </dl>
          </template>
        </el-table-column>
        <el-table-column label="节点" prop="name" min-width="190" />
        <el-table-column label="结果" min-width="115">
          <template #default="{ row }">{{ labels[row.stage] || '未测' }} {{ row.badges }}</template>
        </el-table-column>
        <el-table-column label="延迟" min-width="85">
          <template #default="{ row }">{{ row.delay_ms >= 0 ? latencyText(row.delay_ms) : '—' }}</template>
        </el-table-column>
        <el-table-column label="下载" min-width="100">
          <template #default="{ row }">{{ row.speed_bps ? speedText(row.speed_bps) : '—' }}</template>
        </el-table-column>
        <el-table-column label="检测时间" min-width="145">
          <template #default="{ row }">{{ row.checked_at ? fmtTime(row.checked_at) : '—' }}</template>
        </el-table-column>
      </el-table>
    </div>
    <el-pagination v-if="filtered.length > 10" v-model:current-page="page" :page-size="10"
                   :total="filtered.length" small layout="prev, pager, next" />
    <p v-else-if="!items.length && !loadError && !loading" class="mp-form-hint">没有可测节点。请先在「节点来源」添加或抓取节点。</p>
    <p class="mp-form-hint">“网页可达”不代表可以登录或播放。</p>
    <el-dialog v-model="settingsOpen" title="节点检测设置" width="min(560px, 95vw)">
      <el-form label-position="top">
        <div class="quality-settings">
          <el-form-item v-for="[key, label, min, max] in settingFields" :key="key" :label="label">
            <el-input-number v-model="draft[key]" :min="min" :max="max" :precision="0" controls-position="right" />
          </el-form-item>
        </div>
        <el-form-item label="检测平台">
          <el-select v-model="draft.probe_platform_ids" multiple filterable clearable collapse-tags placeholder="留空检测全部平台">
            <el-option v-for="(name, id) in quality.platforms" :key="id" :label="name" :value="id" />
          </el-select>
        </el-form-item>
        <el-form-item label="在 Mihomo 构建中加入质量分组">
          <el-switch v-model="draft.probe_build_groups" active-value="1" inactive-value="0" />
          <p class="mp-form-hint">下次构建时生效。现有分流规则不变。</p>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settingsOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveSettings">保存设置</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'
import { fmtTime, latencyText } from '../format'

const quality = ref({})
const loading = ref(true)
const busy = ref(false)
const saving = ref(false)
const exporting = ref(false)
const loadError = ref('')
const filter = ref('')
const page = ref(1)
const settingsOpen = ref(false)
const draft = ref({})
const settingFields = [
  ['probe_max_delay_ms', '延迟上限（ms）', 1, 5000],
  ['probe_min_speed_bps', '下载速度下限（B/s）', 1, 100000000],
  ['probe_speed_bytes', '测速文件大小（B）', 65536, 5242880],
  ['probe_speed_timeout_sec', '下载时限（秒）', 3, 20],
  ['probe_timeout_ms', '平台请求超时（ms）', 1000, 15000],
  ['probe_concurrency', '同一节点的平台并发', 1, 6],
  ['probe_round_limit', '每批节点上限', 1, 10],
  ['probe_refresh_hours', '达标节点复测间隔（小时）', 12, 168],
  ['probe_retry', '失败重试次数', 0, 1],
]
let timer = null
const cancellation = new AbortController()

const labels = { probed: '达标', latency_failed: '延迟未通过', speed_failed: '下载过慢',
  inconclusive: '无法确认', unsupported: '核心不支持', unknown: '未测' }
const platformLabels = { reachable: '网页可达', unlocked: '已确认', blocked: '受限',
  unknown: '未确认', error: '检测失败', unsupported: '不支持' }
const items = computed(() => quality.value.items || [])
const thresholds = computed(() => quality.value.thresholds || { delay_ms: 600, speed_bps: 2000000 })
const filters = computed(() => [{ id: '', label: '全部结果' }, ...Object.entries(labels)
  .filter(([id]) => quality.value.counts?.[id]).map(([id, label]) => ({ id, label }))])
const filtered = computed(() => filter.value ? items.value.filter(row => row.stage === filter.value) : items.value)
const visible = computed(() => filtered.value.slice((page.value - 1) * 10, page.value * 10))
const autoState = computed(() => quality.value.auto
  ? quality.value.scheduler_on ? '自动检测已开启' : '系统定时任务未开启'
  : '自动检测已关闭')
watch(filter, () => { page.value = 1 })
watch(() => filtered.value.length, size => { page.value = Math.min(page.value, Math.max(1, Math.ceil(size / 10))) })

function speedText(value) { return `${(value / 1e6).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} MB/s` }

function schedule() {
  if (timer || cancellation.signal.aborted) return
  timer = setTimeout(async () => { timer = null; await load() }, 5000)
}

async function load() {
  try {
    quality.value = await api('/api/v1/unlock/quality', { signal: cancellation.signal }) || {}
    loadError.value = ''
    if (quality.value.task?.running) schedule()
  } catch (e) {
    if (!cancellation.signal.aborted) loadError.value = e.message
  } finally { loading.value = false }
}

async function run() {
  busy.value = true
  try {
    await api('/api/v1/unlock/quality/run', { method: 'POST' })
    quality.value = { ...quality.value, task: { running: true } }
    schedule()
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

function editSettings() {
  const settings = quality.value.settings || {}
  draft.value = { ...settings, probe_platform_ids: [...(settings.probe_platform_ids || [])] }
  settingsOpen.value = true
}

async function saveSettings() {
  if (settingFields.some(([key]) => !Number.isInteger(draft.value[key]))) {
    ElMessage.error('请填写完整的检测设置')
    return
  }
  saving.value = true
  try {
    const values = Object.fromEntries(Object.entries(draft.value).map(([key, val]) =>
      [key, Array.isArray(val) ? val.join(',') : String(val)]))
    await api('/api/v1/settings', { method: 'PUT', body: { values } })
    settingsOpen.value = false
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

async function toggleAuto(enabled) {
  saving.value = true
  try {
    await api('/api/v1/settings', { method: 'PUT', body: { values: { probe_funnel_enabled: enabled ? '1' : '0' } } })
    await load()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

async function download() {
  exporting.value = true
  try {
    const text = await api('/api/v1/unlock/quality/export', { method: 'POST', responseType: 'text' })
    const url = URL.createObjectURL(new Blob([text], { type: 'application/yaml' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'magicpanel-node-pools.yaml'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { ElMessage.error(e.message) } finally { exporting.value = false }
}

onMounted(load)
onUnmounted(() => { if (timer) clearTimeout(timer); cancellation.abort() })
</script>

<style scoped>
.quality-actions, .quality-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 12px 0; }
.quality-filters .el-select { width: 150px; }
.quality-settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0 12px; }
.quality-details { margin: 6px 16px; }
.quality-details div { display: flex; flex-wrap: wrap; gap: 0 12px; padding: 3px 0; }
.quality-details dt { min-width: 115px; font-weight: 600; }
.quality-details dd { margin: 0; }
</style>
