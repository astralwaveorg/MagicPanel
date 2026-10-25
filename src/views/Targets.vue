<template>
  <div>
    <p class="mp-page-desc">
      每个目标对应一类客户端（引擎 + 平台）。同一策略按目标编译为对应方言；平台扩展用于处理平台差异，按整键覆盖。按住左侧手柄拖动排序；分页时仅重排当前页。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button @click="openEdit()" type="primary">添加引擎平台</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有引擎平台。"
      next="点击“添加引擎平台”，例如 Stash · macOS 与 Mihomo · Windows 各建一个。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id" size="small">
          <el-table-column label="顺序" :width="isMobile ? 56 : 104" align="center">
            <template #default="{ row, $index }">
              <div class="order-cell">
                <span class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
                <el-button text size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
                <el-button text size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="130">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="引擎" width="100">
            <template #default="{ row }">{{ ENGINE_LABELS[row.engine] || row.engine }}</template>
          </el-table-column>
          <el-table-column label="平台" width="90">
            <template #default="{ row }">{{ PLATFORM_LABELS[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="160">
            <template #default="{ row }">{{ row.description || '—' }}</template>
          </el-table-column>
          <el-table-column label="平台扩展" min-width="120">
            <template #default="{ row }">{{ row.extra_yaml ? '有（字典递归 / 列表追加）' : '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" @click="remove(row)" type="danger" plain>删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <RefConfirmDialog
      v-model:visible="refDialog.visible"
      :title="refDialog.title"
      :message="refDialog.message"
      :references="refDialog.references"
      :warnings="refDialog.warnings"
      :hint="refDialog.hint"
      :confirm-text="refDialog.confirmText"
      :busy="refDialog.busy"
      :choices="refDialog.choices"
      :choice-label="refDialog.choiceLabel"
      :choice-placeholder="refDialog.choicePlaceholder"
      :choice-value="refDialog.choiceValue"
      @update:choice-value="refDialog.choiceValue = $event"
      @confirm="onRefConfirm"
    />

    <el-dialog v-model="dialog" :title="editing ? '编辑引擎平台' : '添加引擎平台'"
               width="min(620px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称（字母、数字、_ -）">
              <el-input v-model="form.name" class="mono" placeholder="例如：stash-ios" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="引擎">
              <el-select v-model="form.engine" style="width:100%">
                <el-option value="stash" label="Stash" />
                <el-option value="mihomo" label="Mihomo" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="平台">
              <el-select v-model="form.platform" style="width:100%">
                <el-option v-for="(label, key) in PLATFORM_LABELS" :key="key" :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="例如：iPhone 主力配置" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <span>平台扩展（YAML 映射；字典递归合并、列表追加、标量覆盖）</span>
            <span class="mp-field-hint">{{ engineHint }}</span>
          </template>
          <div class="mp-template-bar">
            <el-button v-for="t in templates" :key="t.label" size="small" text type="primary" @click="insertTemplate(t.content)">插入{{ t.label }}</el-button>
          </div>
          <el-input v-model="form.extra_yaml" type="textarea" :rows="8" class="mono"
                    :placeholder="enginePlaceholder" />
        </el-form-item>
        <el-form-item label="客户端更新间隔">
          <span class="mp-toolbar-hint">统一取“设置 → 客户端更新间隔”，对所有目标生效。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import RefConfirmDialog from '../components/RefConfirmDialog.vue'
import { PLATFORM_LABELS, ENGINE_LABELS } from '../format'

// 引擎差异以官方文档为准：
// Stash 特有顶层键 http / cron / script-providers（stash.wiki/configuration/example-config）
// Mihomo 特有顶层键 tun / sniffer / listeners（wiki.metacubex.one）
const ENGINE_HINTS = {
  stash: 'Stash 特有：http（mitm、url-rewrite）、cron、script-providers',
  mihomo: 'Mihomo 特有：tun、sniffer、listeners',
}
const ENGINE_PLACEHOLDERS = {
  stash: '# Stash 示例：\n# http:\n#   mitm:\n#     - "*.google.cn"',
  mihomo: '# Mihomo 示例：\n# tun:\n#   enable: true\n#   stack: gvisor',
}
const TEMPLATES = {
  stash: [
    {
      label: 'MitM 模板',
      content: 'http:\n  # CA 证书需在设备上信任后再启用\n  mitm:\n    - "*.example.com"\n',
    },
    {
      label: '定时脚本模板',
      content: 'cron:\n  script:\n    - name: my-script\n      cron: "0 * * * *"\n      timeout: 10\n',
    },
  ],
  mihomo: [
    {
      label: 'TUN 模板',
      content: 'tun:\n  enable: true\n  stack: gvisor\n  dns-hijack:\n    - any:53\n  auto-route: true\n  auto-detect-interface: true\n',
    },
    {
      label: '嗅探模板',
      content: 'sniffer:\n  enable: true\n  sniff:\n    TLS:\n      ports: [443]\n    HTTP:\n      ports: [80]\n',
    },
  ],
}

const rows = ref([])
const refDialog = reactive({
  visible: false, title: '', message: '', references: [], warnings: [],
  hint: '', confirmText: '删除并解除关联', busy: false, action: null,
  choices: [], choiceLabel: '', choicePlaceholder: '请选择', choiceValue: null,
})
const isMobile = useMobile()
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const tableRef = ref(null)
const sorter = useRowSortable(tableRef, rows, async (ids) => {
  try {
    await api('/api/v1/targets/reorder', { method: 'POST', body: ids })
    ElMessage.success('顺序已更新')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  }
  await load()
})

const emptyForm = () => ({
  name: '', engine: 'stash', platform: 'ios', description: '', extra_yaml: '',
})
const form = reactive(emptyForm())

const engineHint = computed(() => ENGINE_HINTS[form.engine] || '')
const enginePlaceholder = computed(() => ENGINE_PLACEHOLDERS[form.engine] || '')
const templates = computed(() => TEMPLATES[form.engine] || [])

function insertTemplate(content) {
  form.extra_yaml = form.extra_yaml
    ? `${form.extra_yaml.replace(/\s+$/, '')}\n\n${content}`
    : content
}

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const paged = await api(`/api/v1/targets/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`)
    rows.value = paged.items
    total.value = paged.total
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
  await sorter.init()
}
onMounted(load)
onBeforeUnmount(sorter.destroy)

async function move(index, delta) {
  const ids = rows.value.map((r) => r.id)
  const [id] = ids.splice(index, 1)
  ids.splice(index + delta, 0, id)
  try {
    await api('/api/v1/targets/reorder', { method: 'POST', body: ids })
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, engine: row.engine, platform: row.platform,
    description: row.description, extra_yaml: row.extra_yaml,
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/targets/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      await api('/api/v1/targets', { method: 'POST', body: form })
    }
    dialog.value = false
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  if (!await confirmBox(`删除引擎平台 “${row.name}”？`, '删除引擎平台')) return
  try {
    await api(`/api/v1/targets/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e.status === 409 && e.detail?.code === 'target_in_use') {
      const choices = (e.detail.candidates || []).map((c) => ({
        id: c.id, label: `${c.name}（${c.platform}）`,
      }))
      openRefDialog({
        title: `删除引擎平台“${row.name}”`,
        message: e.message,
        references: e.detail.references,
        hint: '删除前需要把这些设备迁移到另一个引擎平台；迁移后它们的配置会按新平台生成。',
        choices,
        choiceLabel: '把这些设备迁移到：',
        choicePlaceholder: '请选择目标引擎平台',
        confirmText: '迁移并删除',
        action: () => forceDeleteTarget(row),
      })
      return
    }
    ElMessage.error(e.message)
  }
}

async function forceDeleteTarget(row) {
  if (!refDialog.choiceValue) {
    ElMessage.warning('请先选择要把设备迁移到哪个引擎平台')
    return
  }
  refDialog.busy = true
  try {
    const resp = await api(
      `/api/v1/targets/${row.id}?force=1&move_to=${refDialog.choiceValue}`,
      { method: 'DELETE' })
    refDialog.visible = false
    const n = resp.moved_devices?.length || 0
    ElMessage.success(n ? `已删除，${n} 台设备已迁移` : '已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
  }
}

function openRefDialog({ title, message, references, warnings = [], hint, action,
  confirmText, choices = [], choiceLabel = '', choicePlaceholder = '请选择' }) {
  Object.assign(refDialog, {
    visible: true, title, message, references, warnings, hint,
    confirmText: confirmText || '删除并解除关联', busy: false, action,
    choices, choiceLabel, choicePlaceholder, choiceValue: null,
  })
}

async function onRefConfirm() {
  if (refDialog.action) await refDialog.action()
}
</script>

