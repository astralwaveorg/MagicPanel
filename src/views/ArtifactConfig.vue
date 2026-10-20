<template>
  <div class="mp-artifact">
    <h2 class="mp-page-title">产物配置</h2>
    <p class="mp-page-desc">
      配置按层级生效：<strong>内置默认</strong>（只读）→ <strong>通用配置</strong>（按引擎 + 平台）→
      <strong>设备专属</strong>（按设备）。
      合并规则是<b>键级并集</b>：同一个键以下层为准，字典逐层递归合并、列表整体替换；
      每一层只保存"与上层不同"的差异，没改过的键会跟随上层。
    </p>

    <div class="mp-artifact-grid">
      <!-- 左：作用域 -->
      <aside class="mp-artifact-aside">
        <div v-for="group in scopeGroups" :key="group.kind" class="mp-scope-group">
          <div class="mp-scope-group-title">
            {{ group.title }}
            <span class="mp-scope-group-hint">{{ group.hint }}</span>
          </div>
          <button
            v-for="s in group.items" :key="scopeKey(s)"
            class="mp-scope-item" :class="{ active: isActive(s) }"
            type="button" @click="select(s)"
          >
            <span class="mp-scope-dot" :class="{ on: s.customized }" />
            <span class="mp-scope-name">{{ s.label }}</span>
            <span class="mp-scope-tag">{{ scopeTag(s) }}</span>
          </button>
        </div>
      </aside>

      <!-- 右：编辑区 -->
      <section class="mp-artifact-main">
        <div class="mp-card">
          <div class="mp-toolbar">
            <div class="left">
              <div class="mp-scope-current">
                <strong>{{ current ? current.label : '产物配置' }}</strong>
                <span class="mp-toolbar-hint">{{ currentHint }}</span>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <el-select v-model="channel" size="small" style="width:104px">
                <el-option value="stable" label="稳定通道" />
                <el-option value="candidate" label="候选通道" />
              </el-select>
              <el-button v-if="!readonly" @click="reset">恢复本层</el-button>
              <el-button @click="preview">预览产物</el-button>
              <el-button v-if="!readonly" type="primary" :loading="saving" @click="save">
                保存
              </el-button>
              <el-button v-if="!readonly" type="primary" plain :loading="applying" @click="apply">
                保存并构建发布
              </el-button>
            </div>
          </div>

          <el-alert v-if="readonly" type="info" :closable="false" show-icon
                    style="margin-bottom:12px">
            内置默认是程序的出厂配置，只读不可改。要调整它，请切到「{{ current?.engine }} 通用配置」
            或更细的层级修改——上层没改过的键会自动跟随。
          </el-alert>
          <el-alert v-else-if="state && !state.overlay" type="info" :closable="false" show-icon
                    style="margin-bottom:12px">
            本层尚未做任何覆盖，当前完全继承上层。改动后会只保存差异部分。
          </el-alert>
          <el-alert v-else type="success" :closable="false" show-icon
                    style="margin-bottom:12px">
            本层已覆盖 {{ Object.keys(state.overlay || {}).length }} 个键，其余继承上层。
          </el-alert>

          <!-- 生效配置：值 + 来源 -->
          <h3 class="mp-section-title">生效配置</h3>
          <el-table :data="effectiveRows" size="small" class="mp-effective-table">
            <el-table-column label="键" min-width="150">
              <template #default="{ row }"><span class="mono">{{ row.key }}</span></template>
            </el-table-column>
            <el-table-column label="值" min-width="260">
              <template #default="{ row }">
                <span class="mono">{{ row.value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="110" align="right">
              <template #default="{ row }">
                <el-tag size="small" :type="row.source === layerLabel ? 'primary' : 'info'"
                        effect="plain">{{ row.source }}</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <!-- 本层编辑 -->
          <template v-if="!readonly">
            <h3 class="mp-section-title">本层修改</h3>
            <el-form :model="doc" label-position="top">
              <template v-for="group in groupOrder" :key="group">
                <div v-if="fieldsOf(group).length" style="margin-bottom:16px">
                  <div class="mp-subsection">{{ groupLabels[group] || group }}</div>
                  <el-row :gutter="12">
                    <el-col v-for="f in fieldsOf(group)" :key="f.key" :xs="24" :sm="12" :md="8">
                      <el-form-item :label="f.label">
                        <el-select v-if="f.type === 'select'" :model-value="getValue(f.key)"
                                   style="width:100%" @change="(v) => setValue(f.key, v)">
                          <el-option v-for="opt in f.options" :key="opt.value"
                                     :value="opt.value" :label="opt.label" />
                        </el-select>
                        <el-switch v-else-if="f.type === 'switch'" :model-value="getValue(f.key)"
                                   @update:model-value="(v) => setValue(f.key, v)" />
                        <el-input-number v-else-if="f.type === 'number'" :model-value="getValue(f.key)"
                                         :min="f.min ?? 0" :max="f.max ?? 65535"
                                         style="width:100%"
                                         @update:model-value="(v) => setValue(f.key, v)" />
                        <el-input v-else-if="f.type === 'list'" :model-value="listText(f.key)"
                                  type="textarea" :rows="3" class="mono"
                                  :placeholder="f.placeholder || '每行一个'"
                                  @input="(v) => setListText(f.key, v)" />
                        <el-input v-else :model-value="getValue(f.key) || ''"
                                  :placeholder="f.placeholder || ''"
                                  @input="(v) => setValue(f.key, v)" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </div>
              </template>

              <el-form-item label="高级 YAML（其余任意顶层键）">
                <el-input v-model="raw" type="textarea" :rows="10" class="mono" />
                <div class="mp-form-hint">
                  编辑的是"生效值"，保存时服务端只把与上层不同的部分记到本层。
                  合并为键级并集：同键以下层为准，字典递归合并、列表整体替换。
                  不能包含 proxies / proxy-providers / proxy-groups / rule-providers / rules。
                </div>
              </el-form-item>

              <el-form-item label="预设">
                <div class="mp-template-bar">
                  <el-select v-model="presetKey" size="small" style="width:200px"
                             @change="applyPreset">
                    <el-option v-for="p in presets" :key="p.key" :value="p.key" :label="p.label" />
                  </el-select>
                  <span class="mp-form-hint">预设是官方推荐的整份配置，套用后本层会覆盖对应键。</span>
                </div>
              </el-form-item>
            </el-form>
          </template>

          <template v-else>
            <h3 class="mp-section-title">内置内容（只读）</h3>
            <el-input :model-value="raw" type="textarea" :rows="12" readonly class="mono" />
          </template>
        </div>
      </section>
    </div>

    <el-dialog v-model="previewVisible" title="产物预览" width="min(920px, 94vw)">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <el-select v-model="previewPlatform" size="small" style="width:200px" @change="doPreview">
          <el-option v-for="p in platforms" :key="p.value" :value="p.value" :label="p.label" />
        </el-select>
        <span class="mp-toolbar-hint">{{ previewNote }}</span>
      </div>
      <div v-if="previewWarnings.length" class="mp-form-hint" style="margin-bottom:8px">
        <div v-for="(w, i) in previewWarnings" :key="i">⚠ {{ w }}</div>
      </div>
      <el-input :model-value="previewText" type="textarea" :rows="24" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { dump, load as yamlLoad } from 'js-yaml'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { PLATFORM_LABELS } from '../format'

const scopes = ref([])
const platforms = ref([])
const current = ref(null)
const state = ref(null)
const fields = ref([])
const groups = ref({})
const presets = ref([])
const doc = reactive({})
const raw = ref('')
const channel = ref('stable')
const saving = ref(false)
const applying = ref(false)
const previewVisible = ref(false)
const previewText = ref('')
const previewPlatform = ref('')
const previewNote = ref('')
const previewWarnings = ref([])
const presetKey = ref('')
const syncing = ref(false)

const groupOrder = computed(() => Object.keys(groups.value))

const scopeGroups = computed(() => {
  const byKind = { builtin: [], general: [], device: [] }
  for (const s of scopes.value) {
    if (!byKind[s.kind]) byKind[s.kind] = []
    byKind[s.kind].push(s)
  }
  return [
    { kind: 'builtin', title: '内置默认', hint: '只读', items: byKind.builtin },
    { kind: 'general', title: '通用配置', hint: '按引擎 + 平台', items: byKind.general },
    { kind: 'device', title: '设备专属', hint: '按设备', items: byKind.device },
  ].filter((g) => g.items.length)
})

const readonly = computed(() => current.value?.kind === 'builtin')
const layerLabel = computed(() => {
  if (!current.value) return ''
  if (current.value.kind === 'builtin') return '内置默认'
  if (current.value.kind === 'general') return '通用配置'
  return '设备专属'
})

const currentHint = computed(() => {
  if (!current.value) return ''
  const s = current.value
  if (s.kind === 'builtin') return '程序出厂配置，作为该引擎全部配置的起点'
  if (s.kind === 'general') return '覆盖内置默认，作用于该引擎与平台的全部设备'
  return `覆盖通用配置，只影响这台设备（${s.detail}）`
})

const effectiveRows = computed(() => {
  const eff = state.value?.effective || {}
  const sources = state.value?.sources || {}
  return Object.keys(eff).map((key) => ({
    key,
    value: formatValue(eff[key]),
    source: sources[key] || '内置默认',
  }))
})

function formatValue(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    const text = JSON.stringify(value)
    return text.length > 120 ? `${text.slice(0, 120)}…` : text
  }
  return String(value)
}

function scopeKey(s) {
  return `${s.kind}:${s.engine}:${s.target}:${s.device_id}`
}

function scopeTag(s) {
  if (s.kind === 'builtin') return '只读'
  if (s.kind === 'general') return '通用'
  return '设备'
}

function isActive(s) {
  return current.value && scopeKey(current.value) === scopeKey(s)
}

function fieldsOf(group) {
  return fields.value.filter((f) => f.group === group)
}

function getPath(obj, path) {
  return path.split('.').reduce((acc, key) => (acc == null ? acc : acc[key]), obj)
}

function setPath(obj, path, value) {
  const keys = path.split('.')
  let cur = obj
  keys.slice(0, -1).forEach((key) => {
    if (typeof cur[key] !== 'object' || cur[key] === null) cur[key] = {}
    cur = cur[key]
  })
  cur[keys[keys.length - 1]] = value
}

function getValue(key) {
  const value = getPath(doc, key)
  return value === undefined ? null : value
}

function setValue(key, value) {
  setPath(doc, key, value)
  syncRaw()
}

function listText(key) {
  const value = getPath(doc, key)
  if (Array.isArray(value)) return value.join('\n')
  return value ? String(value) : ''
}

function setListText(key, text) {
  const lines = String(text).split('\n').map((s) => s.trim()).filter(Boolean)
  setPath(doc, key, lines)
  syncRaw()
}

function syncRaw() {
  syncing.value = true
  raw.value = toYaml(doc)
  nextTick(() => { syncing.value = false })
}

function toYaml(obj) {
  return dump(obj, { lineWidth: 120, noRefs: true, sortKeys: false })
}

function parseYaml(text) {
  const data = yamlLoad(text)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('基础配置必须是键值映射')
  }
  return data
}

// 高级 YAML 是同一份文档的另一个视图：改动文本后回填表单
watch(raw, (text) => {
  if (syncing.value) return
  try {
    const parsed = parseYaml(text)
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, parsed)
  } catch { /* 非法 YAML 保留原文，保存时由服务端提示 */ }
})

async function loadScopes() {
  const data = await api('/api/v1/base-config/scopes')
  scopes.value = data.scopes
}

async function loadSchema(engine) {
  const schema = await api(`/api/v1/base-config/schema?engine=${engine}`)
  fields.value = schema.fields
  groups.value = schema.groups
  presets.value = schema.presets
  presetKey.value = ''
}

async function select(scope) {
  const previous = current.value
  current.value = scope
  try {
    await loadSchema(scope.engine)
    const params = new URLSearchParams({ engine: scope.engine })
    if (scope.platform) params.set('platform', scope.platform)
    if (scope.device_id) params.set('device_id', String(scope.device_id))
    const data = await api(`/api/v1/base-config?${params.toString()}`)
    state.value = data
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, data.effective || {})
    raw.value = data.content || ''
    syncing.value = true
    nextTick(() => { syncing.value = false })
  } catch (e) {
    // 切换失败时回滚到上一个作用域，避免标题与内容对不上
    current.value = previous
    ElMessage.error(e.message)
  }
}

function applyPreset(key) {
  const preset = presets.value.find((p) => p.key === key)
  if (!preset) return
  raw.value = preset.content
  try {
    const parsed = parseYaml(preset.content)
    Object.keys(doc).forEach((k) => delete doc[k])
    Object.assign(doc, parsed)
  } catch { /* 预设由服务端保证合法 */ }
}

function scopeQuery() {
  const s = current.value
  if (!s) return ''
  const params = new URLSearchParams({ engine: s.engine })
  if (s.platform) params.set('platform', s.platform)
  if (s.device_id) params.set('device_id', String(s.device_id))
  return params.toString()
}

async function save() {
  if (!current.value) return
  saving.value = true
  try {
    const r = await api(`/api/v1/base-config?${scopeQuery()}`, {
      method: 'PUT',
      body: { content: raw.value, updated_at: state.value?.updated_at || '' },
    })
    state.value = r
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, r.effective || {})
    raw.value = r.content || ''
    await loadScopes()
    ElMessage.success('已保存，重新构建并发布后生效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function reset() {
  if (!current.value) return
  if (!await confirmBox('清空本层覆盖，回到继承上层？', '恢复本层',
                        { type: 'warning' })) return
  try {
    const r = await api(`/api/v1/base-config/reset?${scopeQuery()}`, { method: 'POST' })
    state.value = r
    const kept = Object.keys(r.overlay || {}).length
    ElMessage.success(kept
      ? `已恢复为继承上层（保留个人直连域名与 Fake-IP 过滤 ${kept} 项）`
      : '已恢复为继承上层')
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, r.effective || {})
    raw.value = r.content || ''
    await loadScopes()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function apply() {
  if (!current.value) return
  applying.value = true
  try {
    const s = current.value
    const r = await api('/api/v1/base-config/apply', {
      method: 'POST',
      body: {
        engine: s.engine, platform: s.platform, device_id: s.device_id,
        content: raw.value, channel: channel.value, note: '更新基础配置',
      },
    })
    ElMessage.success(`已构建 #${r.build_id} 并发布到${channel.value === 'stable' ? '稳定' : '候选'}通道`)
    await loadScopes()
    await select(current.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    applying.value = false
  }
}

async function preview() {
  previewVisible.value = true
  if (!previewPlatform.value && current.value?.platform) {
    previewPlatform.value = current.value.platform
  }
  await doPreview()
}

async function doPreview() {
  if (!previewPlatform.value) return
  try {
    const r = await api('/api/v1/base-config/preview', {
      method: 'POST',
      body: {
        engine: current.value?.engine || 'stash',
        platform: previewPlatform.value,
        device_id: current.value?.device_id || 0,
      },
    })
    previewText.value = r.content
    previewNote.value = r.note
    previewWarnings.value = r.warnings || []
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  try {
    await loadScopes()
    const first = scopes.value.find((s) => s.kind === 'general') || scopes.value[0]
    if (first) await select(first)
    const seen = new Set()
    for (const s of scopes.value) {
      if (s.kind === 'general' && !seen.has(s.platform)) {
        seen.add(s.platform)
        platforms.value.push({ value: s.platform, label: PLATFORM_LABELS[s.platform] || s.platform })
      }
    }
    previewPlatform.value = current.value?.platform || platforms.value[0]?.value || ''
  } catch (e) {
    ElMessage.error(e.message)
  }
})
</script>

<style scoped>
.mp-artifact-grid {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .mp-artifact-grid { grid-template-columns: 1fr; }
}
.mp-artifact-aside {
  background: var(--mp-card-bg, #1b1c20);
  border: 1px solid var(--mp-border, #2c2e33);
  border-radius: 10px;
  padding: 12px;
}
.mp-scope-group + .mp-scope-group { margin-top: 14px; }
.mp-scope-group-title {
  font-size: 12px;
  color: var(--mp-text-secondary);
  letter-spacing: .04em;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.mp-scope-group-hint { font-size: 11px; opacity: .7; }
.mp-scope-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 7px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--mp-text, #e6e7ea);
  font-size: 13px;
  cursor: pointer;
}
.mp-scope-item:hover { background: var(--mp-hover, rgba(255, 255, 255, .05)); }
.mp-scope-item.active {
  background: var(--mp-accent-soft, rgba(64, 158, 255, .16));
  color: var(--mp-accent, #409eff);
}
.mp-scope-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--mp-border, #3a3d44); flex: none;
}
.mp-scope-dot.on { background: var(--mp-accent, #409eff); }
.mp-scope-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mp-scope-tag { font-size: 11px; opacity: .55; }
.mp-scope-current { display: flex; flex-direction: column; gap: 2px; }
.mp-section-title { font-size: 13px; font-weight: 600; margin: 18px 0 8px; }
.mp-subsection { font-size: 12px; color: var(--mp-text-secondary); margin-bottom: 8px; }
.mp-effective-table { margin-bottom: 4px; }
</style>
