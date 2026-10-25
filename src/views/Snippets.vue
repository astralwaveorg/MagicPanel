<template>
  <div>
    <h2 class="mp-page-title">拓展模块</h2>
    <p class="mp-page-desc">
      用于补充脚本、复写、面板等 YAML 片段，构建时按引擎合并至目标配置。
      合并规则：字典递归合并、列表追加、标量覆盖；平台扩展最后生效，优先级最高。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <el-radio-group v-model="categoryFilter" size="small">
          <el-radio-button value="">全部分类</el-radio-button>
          <el-radio-button v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key">
            {{ label }}
          </el-radio-button>
        </el-radio-group>
      </div>
      <el-button @click="openEdit()" type="primary">添加模块</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="暂未添加任何拓展模块。"
      next="点击“添加模块”即可配置，例如为 Stash 增加面板，或为 Mihomo 追加 DNS 配置。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="filtered" v-loading="loading" size="small">
          <el-table-column prop="name" label="名称" min-width="130" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="分类" width="90">
            <template #default="{ row }">{{ CATEGORY_LABELS[row.category] || row.category }}</template>
          </el-table-column>
          <el-table-column label="来源" width="90">
            <template #default="{ row }">
              <el-tooltip v-if="row.source === 'remote'"
                          :content="row.url || '远程来源'" placement="top">
                <el-tag size="small" type="info" effect="plain">远程</el-tag>
              </el-tooltip>
              <el-tag v-else size="small" effect="plain">内联</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="适用引擎" width="100">
            <template #default="{ row }">{{ ENGINE_LABELS[row.engine] || row.engine }}</template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="{ row }">
              <span class="mp-status">
                <i class="mp-dot" :class="row.enabled ? 'ok' : 'muted'" />
                {{ row.enabled ? '启用' : '停用' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="sort" label="顺序" width="80" align="right" />
          <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
          <el-table-column label="更新时间" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="250" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="preview(row)" type="info" plain>内容</el-button>
                <el-button v-if="row.source === 'remote'" size="small"
                           :loading="refreshing === row.id" @click="refresh(row)" plain>抓取</el-button>
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" @click="remove(row)" type="danger" plain>删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑模块' : '添加模块'"
               width="min(640px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item v-if="form.source === 'inline'" label="常用预设（选好后点“填入”，内容可继续修改）">
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="presetKey" placeholder="选择一个预设" style="flex:1" filterable>
              <el-option-group v-for="(items, cat) in PRESETS_BY_CATEGORY" :key="cat"
                               :label="CATEGORY_LABELS[cat] || cat">
                <el-option v-for="p in items" :key="p.key" :label="p.name" :value="p.key" />
              </el-option-group>
            </el-select>
            <el-button :disabled="!presetKey" @click="applyPreset" type="primary">填入</el-button>
          </div>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称">
              <el-input v-model="form.name" placeholder="例如：首页面板" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="分类">
              <el-select v-model="form.category" style="width:100%">
                <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key"
                           :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="适用引擎">
              <el-select v-model="form.engine" style="width:100%">
                <el-option v-for="(label, key) in ENGINE_LABELS" :key="key"
                           :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="合并顺序（小的先合并）">
              <el-input-number v-model="form.sort" :min="0" :max="999" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="来源类型">
          <el-radio-group v-model="form.source">
            <el-radio-button value="inline">内联内容</el-radio-button>
            <el-radio-button value="remote">远程 URL</el-radio-button>
          </el-radio-group>
          <div class="mp-form-hint">
            {{ form.source === 'remote'
              ? '服务端按间隔抓取远端文件，内容进缓存；抓取失败保留上一次可用内容。'
              : '内容直接写在下面，构建时按引擎合并进目标配置。' }}
          </div>
        </el-form-item>
        <template v-if="form.source === 'remote'">
          <el-form-item label="远程地址">
            <el-input v-model="form.url" placeholder="https://example.com/fragment.yaml" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="格式">
                <el-select v-model="form.format" style="width:100%">
                  <el-option value="yaml" label="YAML" />
                  <el-option value="text" label="纯文本" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="抓取间隔（秒）">
                <el-input-number v-model="form.interval" :min="600" :max="604800"
                                 :step="3600" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="客户端更新间隔（秒）">
                <el-input-number v-model="form.client_interval" :min="0" :max="604800"
                                 :step="3600" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="抓取走代理">
            <el-switch v-model="form.useProxy" />
            <span class="mp-form-hint" style="margin-left:12px">
              服务端直连抓不到时经指定代理中转（例如 http://10.0.1.8:7890）
            </span>
          </el-form-item>
          <el-form-item label="抓取代理地址">
            <el-input v-model="form.proxyUrl" placeholder="留空表示直连抓取" />
          </el-form-item>
          <el-form-item v-if="form.content" label="当前缓存内容（抓取后由服务端维护）">
            <el-input :model-value="form.content" type="textarea" :rows="6" readonly class="mono" />
          </el-form-item>
        </template>
        <el-form-item v-else label="内容（YAML 键值片段）">
          <el-input v-model="form.content" type="textarea" :rows="10" class="mono"
                    placeholder="panel:&#10;  首页:&#10;    title: 家庭网络" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" placeholder="用途说明，会展示在 Magic Panel 首页" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用（停用后不参与构建）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialog" :title="`内容 · ${previewName}`"
               width="min(680px, 94vw)">
      <el-input :model-value="previewContent" type="textarea" :rows="14" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import { fmtTime } from '../format'
import { PRESETS_BY_CATEGORY, SNIPPET_PRESETS } from '../snippetPresets'

const CATEGORY_LABELS = {
  script: '脚本', rewrite: '复写', panel: '面板', dns: 'DNS', general: '通用',
}
const ENGINE_LABELS = { stash: '仅 Stash', mihomo: '仅 Mihomo', all: '全部引擎' }

const rows = ref([])
const isMobile = useMobile()
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const categoryFilter = ref('')
const presetKey = ref('')
const previewDialog = ref(false)
const previewContent = ref('')
const previewName = ref('')
const refreshing = ref(0)

const emptyForm = () => ({
  name: '', category: 'general', engine: 'all', content: '',
  enabled: true, sort: 0, note: '',
  source: 'inline', url: '', format: 'yaml',
  interval: 86400, client_interval: 0,
  useProxy: false, proxyUrl: '',
})
const form = reactive(emptyForm())

function applyPreset() {
  const preset = SNIPPET_PRESETS.find((p) => p.key === presetKey.value)
  if (!preset) return
  form.name = preset.name
  form.category = preset.category
  form.engine = preset.engine
  form.content = preset.content
  form.note = preset.note || ''
  form.enabled = preset.enabled !== false
  form.source = 'inline'
  ElMessage.success('已填入预设，可继续修改后保存')
}

const filtered = computed(() =>
  categoryFilter.value
    ? rows.value.filter((r) => r.category === categoryFilter.value)
    : rows.value)

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const paged = await api(`/api/v1/snippets/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`)
    rows.value = paged.items
    total.value = paged.total
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openEdit(row) {
  presetKey.value = ''
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, category: row.category, engine: row.engine,
    content: row.content, enabled: !!row.enabled, sort: row.sort, note: row.note,
    source: row.source || 'inline', url: row.url || '',
    format: row.format || 'yaml',
    interval: row.interval ?? 86400, client_interval: row.client_interval ?? 0,
    useProxy: !!row.use_proxy, proxyUrl: '',
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写名称')
  if (form.source === 'inline' && !form.content.trim()) {
    return ElMessage.warning('请填写内容')
  }
  if (form.source === 'remote' && !form.url.trim()) {
    return ElMessage.warning('请填写远程地址')
  }
  saving.value = true
  const body = {
    name: form.name, category: form.category, engine: form.engine,
    content: form.source === 'inline' ? form.content : (form.content || ''),
    enabled: form.enabled, sort: form.sort, note: form.note,
    source: form.source, url: form.url, format: form.format,
    interval: form.interval, client_interval: form.client_interval,
    // 抓取代理：留空表示不改；给了空串表示改成直连
    proxy_url: form.source === 'remote'
      ? (form.useProxy ? (form.proxyUrl || '') : '')
      : null,
  }
  try {
    if (editing.value) {
      await api(`/api/v1/snippets/${editing.value.id}`, { method: 'PUT', body })
    } else {
      await api('/api/v1/snippets', { method: 'POST', body })
    }
    dialog.value = false
    ElMessage.success('已保存，下次构建时生效')
    await load()
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function refresh(row) {
  refreshing.value = row.id
  try {
    await api(`/api/v1/snippets/${row.id}/refresh`, { method: 'POST' })
    ElMessage.success(`已抓取 “${row.name}”`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refreshing.value = 0
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除模块 “${row.name}”？下次构建不再包含该片段。`, '删除拓展模块')) return
  try {
    await api(`/api/v1/snippets/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function preview(row) {
  previewContent.value = row.content
  previewName.value = row.name
  previewDialog.value = true
}
</script>
