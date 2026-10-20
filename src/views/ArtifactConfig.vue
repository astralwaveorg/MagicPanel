<template>
  <div>
    <h2 class="mp-page-title">产物配置</h2>
    <p class="mp-page-desc">
      产物的基础层：端口、模式、日志、IPv6、DNS 等顶层键按引擎分别配置。
      节点、策略组、分流规则由各自页面维护；功能模块与发布目标扩展在其上叠加，优先级更高。
    </p>

    <div class="mp-card">
      <div class="mp-toolbar">
        <div class="left">
          <el-radio-group v-model="engine" size="small" @change="load">
            <el-radio-button value="stash">Stash</el-radio-button>
            <el-radio-button value="mihomo">Mihomo</el-radio-button>
          </el-radio-group>
          <el-select v-model="presetKey" size="small" style="width:200px" @change="applyPreset">
            <el-option v-for="p in presets" :key="p.key" :value="p.key" :label="p.label" />
          </el-select>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <el-select v-model="channel" size="small" style="width:104px">
            <el-option value="stable" label="稳定通道" />
            <el-option value="candidate" label="候选通道" />
          </el-select>
          <el-button @click="reset">恢复默认</el-button>
          <el-button @click="preview">预览</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button type="primary" plain :loading="applying" @click="apply">
            保存并构建发布
          </el-button>
        </div>
      </div>

      <el-alert v-if="!isDefault" type="info" :closable="false" show-icon
                style="margin-bottom:12px">
        已自定义。修改后需重新构建并发布，客户端才会拿到新内容。
      </el-alert>

      <el-form :model="doc" label-position="top">
        <template v-for="group in groupOrder" :key="group">
          <div v-if="fieldsOf(group).length" style="margin-bottom:18px">
            <h3 style="margin:0 0 10px;font-size:14px;font-weight:600">
              {{ groupLabels[group] || group }}
            </h3>
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
            不能包含 proxies / proxy-providers / proxy-groups / rule-providers / rules
            （这些由各自的页面维护）；列表键与目标扩展是「追加」而不是替换。
          </div>
        </el-form-item>
      </el-form>
    </div>

    <el-dialog v-model="previewVisible" title="产物预览" width="min(920px, 94vw)">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <el-select v-model="previewTarget" size="small" style="width:200px" @change="doPreview">
          <el-option v-for="t in targets" :key="t.name" :value="t.name" :label="t.name" />
        </el-select>
        <span class="mp-toolbar-hint">{{ previewNote }}</span>
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

const engine = ref('stash')
const channel = ref('stable')
const doc = reactive({})
const raw = ref('')
const fields = ref([])
const groups = ref({})
const presets = ref([])
const presetKey = ref('')
const isDefault = ref(true)
const updatedAt = ref('')
const targets = ref([])
const saving = ref(false)
const applying = ref(false)
const previewVisible = ref(false)
const previewText = ref('')
const previewTarget = ref('')
const previewNote = ref('')

const groupOrder = computed(() => Object.keys(groups.value))

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

const syncing = ref(false)

// 高级 YAML 是同一份文档的另一个视图：改动文本后回填表单
watch(raw, (text) => {
  if (syncing.value) return
  try {
    const parsed = parseYaml(text)
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, parsed)
  } catch { /* 非法 YAML 保留原文，保存时由服务端提示 */ }
})

function toYaml(obj) {
  return dump(obj, { lineWidth: 120, noRefs: true, sortKeys: false })
}

async function load() {
  try {
    const [cfg, schema, targetList] = await Promise.all([
      api(`/api/v1/base-config?engine=${engine.value}`),
      api(`/api/v1/base-config/schema?engine=${engine.value}`),
      api('/api/v1/targets'),
    ])
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, cfg.doc || {})
    raw.value = cfg.content || ''
    isDefault.value = cfg.is_default
    updatedAt.value = cfg.updated_at
    fields.value = schema.fields
    groups.value = schema.groups
    presets.value = schema.presets
    presetKey.value = ''
    targets.value = targetList
    if (!previewTarget.value) {
      const first = targetList.find((t) => t.engine === engine.value) || targetList[0]
      previewTarget.value = first ? first.name : ''
    }
  } catch (e) {
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
  isDefault.value = false
}

function parseYaml(text) {
  const data = yamlLoad(text)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('基础配置必须是键值映射')
  }
  return data
}

async function save() {
  saving.value = true
  try {
    const r = await api(`/api/v1/base-config?engine=${engine.value}`, {
      method: 'PUT',
      body: { content: raw.value, updated_at: updatedAt.value },
    })
    raw.value = r.content
    isDefault.value = r.is_default
    updatedAt.value = r.updated_at
    ElMessage.success('已保存，重新构建并发布后生效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function reset() {
  if (!await confirmBox('恢复该引擎的默认基础配置？', '恢复默认',
                        { type: 'warning' })) return
  try {
    const r = await api(`/api/v1/base-config/reset?engine=${engine.value}`, { method: 'POST' })
    raw.value = r.content
    isDefault.value = true
    updatedAt.value = r.updated_at
    await load()
    ElMessage.success('已恢复默认')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function apply() {
  applying.value = true
  try {
    const r = await api('/api/v1/base-config/apply', {
      method: 'POST',
      body: { engine: engine.value, content: raw.value, channel: channel.value,
              note: '更新基础配置' },
    })
    ElMessage.success(`已构建 #${r.build_id} 并发布到${channel.value === 'stable' ? '稳定' : '候选'}通道`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    applying.value = false
  }
}

async function preview() {
  previewVisible.value = true
  await doPreview()
}

async function doPreview() {
  if (!previewTarget.value) return
  try {
    const r = await api('/api/v1/base-config/preview', {
      method: 'POST',
      body: { engine: engine.value, target: previewTarget.value },
    })
    previewText.value = r.content
    previewNote.value = r.note
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>
