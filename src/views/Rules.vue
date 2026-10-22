<template>
  <div>
    <h2 class="mp-page-title">分流规则</h2>
    <p class="mp-page-desc">
      规则按声明顺序自上而下首次匹配，最后一条须为 MATCH 兜底。按住左侧手柄拖动排序；分页时仅重排当前页，调整后于下一次构建生效。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button @click="openBatch">批量修改</el-button>
          <el-button @click="batchEnable(true)">批量启用</el-button>
          <el-button @click="batchEnable(false)">批量停用</el-button>
          <el-button @click="removeSelected" type="danger" plain>批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
      </div>
      <el-button @click="openEdit()" type="primary">添加规则</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有分流规则。"
      next="点击“添加规则”；构建前至少需要一条 MATCH 兜底规则。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="顺序" :width="isMobile ? 56 : 104" align="center">
            <template #default="{ row, $index }">
              <div class="order-cell">
                <span class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
                <el-button text size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
                <el-button text size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="130">
            <template #default="{ row }"><span class="mono">{{ row.type }}</span></template>
          </el-table-column>
          <el-table-column label="匹配值" min-width="200">
            <template #default="{ row }"><span class="mono">{{ row.value || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="target" label="目标" min-width="110" />
          <el-table-column label="适用平台" min-width="150">
            <template #default="{ row }">
              <span>{{ scopeText(row.targets) }}</span>
              <div v-if="row.devices && row.devices.length" class="mp-cell-sub">
                设备：{{ scopeText(row.devices) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="no-resolve" width="100" align="center">
            <template #default="{ row }">{{ row.no_resolve ? '是' : '—' }}</template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="140">
            <template #default="{ row }">{{ row.note || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" @click="remove(row)" type="danger" plain>删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑规则' : '添加规则'" width="min(560px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width:100%">
            <el-option v-for="t in ruleTypes" :key="t" :value="t" :label="t" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.type === 'RULE-SET'" label="规则来源">
          <el-select v-model="form.value" style="width:100%">
            <el-option v-for="p in ruleProviders" :key="p.name" :value="p.name" :label="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-else-if="!isFinal" label="匹配值">
          <el-input v-model="form.value" class="mono" maxlength="512"
                    :placeholder="form.type === 'IP-CIDR' ? '10.0.1.0/24' : 'example.com'" />
        </el-form-item>
        <el-form-item label="目标（策略组或内置动作）">
          <el-select v-model="form.target" filterable style="width:100%">
            <el-option v-for="g in groups" :key="g.name" :value="g.name" :label="g.name" />
            <el-option value="DIRECT" label="DIRECT（直连）" />
            <el-option value="REJECT" label="REJECT（拒绝）" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用引擎平台">
          <MultiSelectClear :has-value="form.targets.length" @clear="form.targets = []">
            <el-select v-model="form.targets" multiple style="width:100%"
                       placeholder="包含所有"
                       @change="form.targets = normalizeScope(form.targets, ALL_SCOPE)">
              <el-option :value="ALL_SCOPE" label="包含所有" />
              <el-option v-for="t in targets" :key="t.name" :value="t.name" :label="t.name" />
            </el-select>
          </MultiSelectClear>
          <div class="mp-form-hint">
            只在选中的引擎平台里生效；若该规则指向的策略组不适用于同一平台，规则会被自动剔除。
          </div>
        </el-form-item>
        <el-form-item label="适用设备">
          <MultiSelectClear :has-value="form.devices.length" @clear="form.devices = []">
            <el-select v-model="form.devices" multiple style="width:100%"
                       placeholder="包含所有"
                       @change="form.devices = normalizeScope(form.devices, ALL_SCOPE)">
              <el-option :value="ALL_SCOPE" label="包含所有" />
              <el-option v-for="d in devices" :key="d.name" :value="d.name" :label="d.name" />
            </el-select>
          </MultiSelectClear>
          <div class="mp-form-hint">
            个性化放这里：选了设备后，这条规则只出现在这些设备自己的产物里，
            同平台的其他设备不受影响。
          </div>
        </el-form-item>
        <el-form-item label="备注（可选）">
          <el-input v-model="form.note" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用</el-checkbox>
          <el-checkbox v-if="canNoResolve" v-model="form.no_resolve">
            no-resolve（仅匹配 IP 字面量，不触发域名解析）
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDialog" title="批量修改分流规则" width="min(560px, 94vw)">
      <p class="mp-dialog-desc">
        将选中的 {{ selected.length }} 条规则按下面的设置统一修改。
        只勾选的项会生效：勾上但没选内容 = 清空该项；不勾 = 保持原样。
      </p>
      <el-form :model="batch" label-position="top">
        <el-form-item>
          <el-checkbox v-model="batch.useTarget">修改目标</el-checkbox>
        </el-form-item>
        <el-select v-if="batch.useTarget" v-model="batch.target" filterable style="width:100%"
                   placeholder="选择统一的出站">
          <el-option v-for="g in groups" :key="g.name" :value="g.name" :label="g.name" />
          <el-option value="DIRECT" label="DIRECT（直连）" />
          <el-option value="REJECT" label="REJECT（拒绝）" />
        </el-select>

        <el-form-item>
          <el-checkbox v-model="batch.useTargets">修改适用引擎平台</el-checkbox>
        </el-form-item>
        <MultiSelectClear v-if="batch.useTargets"
                          :has-value="batch.targets.length" @clear="batch.targets = []">
          <el-select v-model="batch.targets" multiple style="width:100%"
                     placeholder="包含所有"
                     @change="batch.targets = normalizeScope(batch.targets, ALL_SCOPE)">
            <el-option :value="ALL_SCOPE" label="包含所有" />
            <el-option v-for="t in targets" :key="t.name" :value="t.name" :label="t.name" />
          </el-select>
        </MultiSelectClear>

        <el-form-item>
          <el-checkbox v-model="batch.useEnabled">修改启用状态</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.useEnabled" v-model="batch.enabled">
          <el-radio :value="true">启用</el-radio>
          <el-radio :value="false">停用</el-radio>
        </el-radio-group>

        <el-form-item>
          <el-checkbox v-model="batch.useNote">修改备注</el-checkbox>
        </el-form-item>
        <el-input v-if="batch.useNote" v-model="batch.note" placeholder="留空即清空备注" />

        <el-form-item>
          <el-checkbox v-model="batch.useNoResolve">修改 no-resolve</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.useNoResolve" v-model="batch.no_resolve">
          <el-radio :value="true">是</el-radio>
          <el-radio :value="false">否</el-radio>
        </el-radio-group>
      </el-form>
      <template #footer>
        <el-button @click="batchDialog = false">取消</el-button>
        <el-button :loading="batchSaving" @click="saveBatch" type="primary">应用</el-button>
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
import { ALL_SCOPE, normalizeScope, collapseIfComplete } from '../scopeOptions'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import MultiSelectClear from '../components/MultiSelectClear.vue'
import ErrorState from '../components/ErrorState.vue'

// 与后端 config.RULE_TYPES 保持一致（少一种就会导致该类型根本建不出来）
const ruleTypes = [
  'DOMAIN-SUFFIX', 'DOMAIN', 'DOMAIN-KEYWORD', 'DOMAIN-REGEX',
  'IP-CIDR', 'IP-CIDR6', 'GEOIP', 'GEOSITE', 'RULE-SET',
  'SRC-IP-CIDR', 'DST-PORT', 'PROCESS-NAME', 'MATCH',
]

const rows = ref([])
const isMobile = useMobile()
const selected = ref([])
const batchDialog = ref(false)
const batchSaving = ref(false)
const batch = reactive({
  useTarget: false, target: '',
  useTargets: false, targets: [],
  useEnabled: false, enabled: true,
  useNote: false, note: '',
  useNoResolve: false, no_resolve: false,
})
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const groups = ref([])
const ruleProviders = ref([])
const targets = ref([])
const devices = ref([])
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const tableRef = ref(null)
const sorter = useRowSortable(tableRef, rows, async (ids) => {
  try {
    await api('/api/v1/rules/reorder', { method: 'POST', body: ids })
    ElMessage.success('顺序已更新')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  }
  await load()
})

const NO_RESOLVE_TYPES = ['IP-CIDR', 'IP-CIDR6', 'GEOIP', 'RULE-SET', 'SRC-IP-CIDR']

// 默认一律"包含所有"：新建的规则开箱即对全部平台、全部设备生效
const emptyForm = () => ({
  type: 'DOMAIN-SUFFIX', value: '', target: 'DIRECT', enabled: true, note: '',
  no_resolve: false, targets: [ALL_SCOPE], devices: [ALL_SCOPE],
})
const form = reactive(emptyForm())

// 适用范围展示："*" 是「包含所有」，不直接显示给用户
function scopeText(list) {
  if (!list || !list.length) return '不适用'
  if (list.includes(ALL_SCOPE)) return '全部'
  return list.join('、')
}
const isFinal = computed(() => ['MATCH', 'FINAL'].includes(form.type))
const canNoResolve = computed(() => NO_RESOLVE_TYPES.includes(form.type))

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [paged, gs, rps, targetList, deviceList] = await Promise.all([
      api(`/api/v1/rules/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`),
      api('/api/v1/groups'), api('/api/v1/rule-providers'),
      api('/api/v1/targets'), api('/api/v1/devices'),
    ])
    rows.value = paged.items
    total.value = paged.total
    groups.value = gs
    ruleProviders.value = rps.filter((p) => p.enabled)
    targets.value = targetList
    devices.value = deviceList
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

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    type: row.type, value: row.value, target: row.target, enabled: row.enabled,
    note: row.note, no_resolve: row.no_resolve, targets: [...(row.targets || [])],
    devices: [...(row.devices || [])],
  } : {})
  dialog.value = true
}

async function save() {
  saving.value = true
  try {
    const body = { ...form, value: isFinal.value ? '' : form.value }
    // 逐项选满 = 包含所有：存成 ["*"]，以后新增的平台/设备自动包含
    body.targets = collapseIfComplete(body.targets, targets.value.map((t) => t.name))
    body.devices = collapseIfComplete(body.devices, devices.value.map((d) => d.name))
    if (editing.value) {
      await api(`/api/v1/rules/${editing.value.id}`, { method: 'PUT', body })
    } else {
      await api('/api/v1/rules', { method: 'POST', body })
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

async function move(index, delta) {
  const ids = rows.value.map((r) => r.id)
  const [id] = ids.splice(index, 1)
  ids.splice(index + delta, 0, id)
  try {
    await api('/api/v1/rules/reorder', { method: 'POST', body: ids })
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除规则 “${row.type},${row.value || '(兜底)'} → ${row.target}”？`, '删除规则',
    { type: 'warning' },
  )) return
  try {
    await api(`/api/v1/rules/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function onSelectionChange(selection) {
  selected.value = selection
}

function clearSelection() {
  selected.value = []
  tableRef.value?.clearSelection()
}

function openBatch() {
  if (!selected.value.length) return
  batch.useTarget = false; batch.target = ''
  batch.useTargets = false; batch.targets = []
  batch.useEnabled = false; batch.enabled = true
  batch.useNote = false; batch.note = ''
  batch.useNoResolve = false; batch.no_resolve = false
  batchDialog.value = true
}

async function saveBatch() {
  if (!selected.value.length) return
  const payload = { ids: selected.value.map((r) => r.id) }
  if (batch.useTarget) payload.target = batch.target
  if (batch.useTargets) payload.targets = batch.targets
  if (batch.useEnabled) payload.enabled = batch.enabled
  if (batch.useNote) payload.note = batch.note
  if (batch.useNoResolve) payload.no_resolve = batch.no_resolve
  const keys = Object.keys(payload).filter((k) => k !== 'ids')
  if (!keys.length) {
    ElMessage.warning('请至少勾选一项要修改的内容')
    return
  }
  batchSaving.value = true
  try {
    const resp = await api('/api/v1/rules/batch', { method: 'PATCH', body: payload })
    batchDialog.value = false
    ElMessage.success(`已更新 ${resp.updated} 条分流规则`)
    if (resp.skipped?.length) {
      ElMessage.warning(resp.skipped.map((s) => `${s.name}：${s.reason}`).join('；'), { duration: 8000 })
    }
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    batchSaving.value = false
  }
}

async function batchEnable(enabled) {
  if (!selected.value.length) return
  try {
    const resp = await api('/api/v1/rules/batch', {
      method: 'PATCH',
      body: { ids: selected.value.map((r) => r.id), enabled },
    })
    ElMessage.success(`已${enabled ? '启用' : '停用'} ${resp.updated} 条规则`)
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeSelected() {
  if (!selected.value.length) return
  const ids = selected.value.map((r) => r.id)
  const ok = await confirmBox(
    `删除选中的 ${ids.length} 条分流规则？兜底规则（MATCH / FINAL）不会被删除。`,
    '批量删除分流规则', { type: 'warning', confirmButtonText: '删除' })
  if (!ok) return
  try {
    const resp = await api('/api/v1/rules/batch/delete', {
      method: 'POST', body: { ids },
    })
    if (resp.blocked?.length) {
      ElMessage.warning(
        `已删除 ${resp.deleted.length} 条；${resp.blocked.length} 条未删：`
        + resp.blocked.map((b) => `${b.name}（${b.reason}）`).join('；'), { duration: 9000 })
    } else {
      ElMessage.success(`已删除 ${resp.deleted.length} 条分流规则`)
    }
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.order-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}
.drag-handle {
  cursor: grab;
  color: var(--mp-muted);
  font-size: 15px;
  line-height: 1;
  padding: 4px 3px;
  margin-right: 2px;
  user-select: none;
  touch-action: none;
}
.drag-handle:active { cursor: grabbing; }
.order-cell .el-button { margin: 0; padding: 4px 2px; }
</style>
