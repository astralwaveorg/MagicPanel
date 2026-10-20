<template>
  <div>
    <h2 class="mp-page-title">规则来源</h2>
    <p class="mp-page-desc">
      规则集由服务端抓取并留存快照，经构建引用后通过订阅地址分发给设备；远程与内联两种来源独立更新。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing"
                     @click="refreshMany(selected)">抓取选中</el-button>
          <el-button :disabled="batchRefreshing" @click="openBatchInterval">修改抓取间隔</el-button>
          <el-button type="danger" plain :disabled="batchRefreshing"
                     @click="removeSelected">批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
        <template v-else>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing"
                     @click="refreshMany(remoteRows)">一键抓取</el-button>
          <span v-if="batchRefreshing" class="mp-toolbar-hint">
            正在抓取 {{ refreshDone }}/{{ refreshTotal }}…
          </span>
        </template>
        <el-input
          v-model="query"
          placeholder="按名称或 URL 搜索"
          clearable
          style="width:240px"
        />
      </div>
      <el-button type="primary" @click="openEdit()">添加规则来源</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有规则来源。"
      next="点击“添加规则来源”：远程来源填 URL，内联来源直接粘贴规则内容。"
    />
    <EmptyState
      v-else-if="!filteredRows.length"
      reason="没有匹配的规则来源。"
      next="尝试更换名称或 URL 关键词。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="pagedRows" v-loading="loading" row-key="id"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" fixed />
          <el-table-column prop="name" label="名称" min-width="110" fixed />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ row.kind === 'remote' ? '远程' : '内联' }}</template>
          </el-table-column>
          <el-table-column prop="behavior" label="行为" width="90" />
          <el-table-column prop="format" label="格式" width="80" />
          <el-table-column label="URL" width="110">
            <template #default="{ row }">
              <el-button v-if="row.kind === 'remote' && row.url" size="small"
                         @click="copyUrl(row)">复制 URL</el-button>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="100">
            <template #default="{ row }"><StatusDot v-bind="sourceStatus(row)" /></template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="规则数" width="80" align="right">
            <template #default="{ row }">{{ row.rule_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="摘要" min-width="130">
            <template #default="{ row }"><span class="mono mp-nowrap">{{ shortSha(row.sha256) }}</span></template>
          </el-table-column>
          <el-table-column label="抓取间隔" width="110" align="right" prop="interval" />
          <el-table-column label="最近成功" min-width="160">
            <template #default="{ row }"><span class="mp-nowrap">{{ fmtTime(row.last_fetched_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="192" fixed="right">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" :disabled="!row.has_content" @click="preview(row)">内容</el-button>
                <el-button size="small" v-if="row.kind === 'remote'" :loading="row._refreshing"
                           @click="refresh(row)">抓取</el-button>
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="pageSize" :total="filteredRows.length"
             :sizes="[10, 20, 50, 100]" @change="onPagerChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑规则来源' : '添加规则来源'"
               width="min(620px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称（字母、数字、_ -）">
              <el-input v-model="form.name" class="mono" placeholder="例如：ai" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="行为">
              <el-select v-model="form.behavior" style="width:100%">
                <el-option value="domain" label="domain（域名）" />
                <el-option value="ipcidr" label="ipcidr（IP 段）" />
                <el-option value="classical" label="classical（经典规则）" />
              </el-select>
              <div v-if="form.behavior === 'classical'" class="mp-form-hint">
                Stash 官方不推荐 classical：只能顺序匹配，显著增加耗时与内存。纯域名集合建议改用 domain。
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="来源类型">
          <el-radio-group v-model="form.kind">
            <el-radio value="remote">远程 URL</el-radio>
            <el-radio value="inline">内联内容</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.kind === 'remote'" label="URL">
          <el-input v-model="form.url" class="mono" placeholder="https://…/ruleset.yaml" />
        </el-form-item>
        <el-form-item v-else label="规则内容（yaml payload 或每行一条）">
          <el-input v-model="form.inline_content" type="textarea" :rows="8" class="mono"
                    placeholder="payload:&#10;  - example.com" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="格式">
              <el-select v-model="form.format" style="width:100%">
                <el-option value="yaml" label="yaml" />
                <el-option value="text" label="text" />
                <el-option value="mrs" label="mrs" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="抓取间隔（秒）">
              <el-input-number v-model="form.interval" :min="600" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="客户端更新间隔（秒，0 = 跟随抓取间隔）">
              <el-input-number v-model="form.client_interval" :min="0" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="intervalDialog" title="批量修改抓取间隔"
               width="min(480px, 94vw)">
      <p class="mp-dialog-desc">
        将选中的 {{ selected.length }} 个规则来源的间隔统一设为（秒）。
        间隔会写入后续构建产物，由客户端按 provider 间隔更新；内联来源不参与服务端抓取，
        但同样会写入产物。
      </p>
      <el-input-number v-model="batchInterval" :min="600" :max="604800" style="width:100%" />
      <div class="mp-preset-row">
        <el-button v-for="p in INTERVAL_PRESETS" :key="p.value" size="small"
                   :type="batchInterval === p.value ? 'primary' : 'default'"
                   @click="batchInterval = p.value">{{ p.label }}</el-button>
      </div>
      <template #footer>
        <el-button @click="intervalDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingInterval" @click="saveBatchInterval">应用</el-button>
      </template>
    </el-dialog>

    <BatchResultDialog
      v-model:visible="blockedVisible"
      title="部分规则来源未删除"
      :summary="`已删除 ${deletedCount} 项；${blockedItems.length} 项因仍被引用而保留`"
      :items="blockedItems"
    />

    <el-dialog v-model="urlDialog" :title="urlCopied ? 'URL 已复制' : 'URL 复制失败'"
               width="min(620px, 94vw)">
      <p class="mp-dialog-desc">
        {{ urlCopied ? '已复制以下规则来源 URL：' : '自动复制失败，请手动选择下面的 URL：' }}
      </p>
      <el-input :model-value="urlContent" type="textarea" :rows="3" readonly class="mono" />
    </el-dialog>

    <el-dialog v-model="previewDialog" :title="`内容快照 · ${previewName}`"
               width="min(720px, 94vw)">
      <el-input :model-value="previewContent" type="textarea" :rows="18" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import Pager from '../components/Pager.vue'
import BatchResultDialog from '../components/BatchResultDialog.vue'
import { fmtTime, shortSha, sourceStatus } from '../format'

const INTERVAL_PRESETS = [
  { label: '15 分钟', value: 900 },
  { label: '1 小时', value: 3600 },
  { label: '6 小时', value: 21600 },
  { label: '1 天', value: 86400 },
  { label: '7 天', value: 604800 },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const previewDialog = ref(false)
const previewContent = ref('')
const previewName = ref('')
const urlDialog = ref(false)
const urlContent = ref('')
const urlCopied = ref(false)
const tableRef = ref(null)
const selected = ref([])
const batchRefreshing = ref(false)
const refreshDone = ref(0)
const refreshTotal = ref(0)
const intervalDialog = ref(false)
const savingInterval = ref(false)
const batchInterval = ref(86400)
const blockedVisible = ref(false)
const blockedItems = ref([])
const deletedCount = ref(0)
const query = ref('')
const page = ref(1)
const pageSize = ref(20)

function onPagerChange({ page: p, limit: l }) {
  if (l && l !== pageSize.value) {
    pageSize.value = l
    page.value = 1
    clearSelection()
    return
  }
  page.value = p
  clearSelection()
}

const remoteRows = computed(() => rows.value.filter((r) => r.kind === 'remote'))
const filteredRows = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) =>
    (r.name || '').toLowerCase().includes(q)
    || (r.url || '').toLowerCase().includes(q))
})
const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

watch(query, () => {
  page.value = 1
  clearSelection()
})
watch([page, pageSize], () => {
  clearSelection()
  const maxPage = Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value))
  if (page.value > maxPage) page.value = maxPage
})
watch(filteredRows, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize.value))
  if (page.value > maxPage) page.value = maxPage
})

const emptyForm = () => ({
  name: '', behavior: 'domain', format: 'yaml', kind: 'remote', client_interval: 0,
  url: '', inline_content: '', interval: 86400, enabled: true,
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api('/api/v1/rule-providers')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function onSelectionChange(selection) {
  selected.value = selection
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selected.value = []
}

async function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, behavior: row.behavior, format: row.format, kind: row.kind,
    client_interval: row.client_interval,
    url: row.url, inline_content: '', interval: row.interval, enabled: row.enabled,
  } : {})
  dialog.value = true
  if (row && row.kind === 'inline') {
    try {
      const data = await api(`/api/v1/rule-providers/${row.id}/content`)
      form.inline_content = data.content
    } catch (e) {
      ElMessage.error(e.message)
    }
  }
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    const body = { ...form }
    if (editing.value) {
      if (body.kind === 'inline' && !body.inline_content) {
        const current = await api(`/api/v1/rule-providers/${editing.value.id}/content`)
        body.inline_content = current.content
      }
      await api(`/api/v1/rule-providers/${editing.value.id}`, { method: 'PUT', body })
    } else {
      await api('/api/v1/rule-providers', { method: 'POST', body })
    }
    dialog.value = false
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function refreshRow(row, silent = false) {
  row._refreshing = true
  try {
    const updated = await api(`/api/v1/rule-providers/${row.id}/refresh`, {
      method: 'POST',
    })
    Object.assign(row, updated)
    if (!silent) ElMessage.success(`抓取成功：${updated.rule_count} 条规则`)
    return true
  } catch (e) {
    if (!silent) ElMessage.error(e.message)
    return false
  } finally {
    row._refreshing = false
  }
}

async function refresh(row) {
  if (!await refreshRow(row)) await load()
}

async function refreshMany(list) {
  if (batchRefreshing.value) return
  const targets = (list || []).filter((r) => r && r.kind === 'remote')
  if (!targets.length) {
    return ElMessage.info('没有可抓取的远程规则来源（内联来源无需抓取）')
  }
  batchRefreshing.value = true
  refreshDone.value = 0
  refreshTotal.value = targets.length
  const queue = [...targets]
  let ok = 0
  let failed = 0
  const worker = async () => {
    while (queue.length) {
      const row = queue.shift()
      if (await refreshRow(row, true)) ok += 1
      else failed += 1
      refreshDone.value += 1
    }
  }
  try {
    await Promise.all(
      Array.from({ length: Math.min(3, targets.length) }, () => worker()),
    )
    if (failed) {
      ElMessage.warning(`抓取完成：${ok} 个成功，${failed} 个失败（失败来源保留最近成功快照）`)
    } else {
      ElMessage.success(`抓取完成：${ok} 个远程来源全部成功`)
    }
  } finally {
    batchRefreshing.value = false
    await load()
  }
}

function openBatchInterval() {
  if (!selected.value.length) return
  batchInterval.value = selected.value[0].interval || 86400
  intervalDialog.value = true
}

async function saveBatchInterval() {
  if (!selected.value.length) return
  savingInterval.value = true
  try {
    const ids = selected.value.map((r) => r.id)
    const resp = await api('/api/v1/rule-providers/batch', {
      method: 'PATCH', body: { ids, interval: batchInterval.value },
    })
    intervalDialog.value = false
    ElMessage.success(`已更新 ${resp.updated} 个规则来源的间隔`)
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingInterval.value = false
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除规则来源 “${row.name}”？删除前会校验分流规则引用；仍被引用的来源不能删除。`,
    '删除规则来源',
  )) return
  try {
    await api(`/api/v1/rule-providers/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeSelected() {
  if (!selected.value.length) return
  if (!await confirmBox(
    `删除选中的 ${selected.value.length} 个规则来源？删除前会逐个校验分流规则引用`
    + '（含停用规则），仍被引用的来源会保留并列出原因。',
    '批量删除规则来源', { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    const ids = selected.value.map((r) => r.id)
    const resp = await api('/api/v1/rule-providers/batch/delete', {
      method: 'POST', body: { ids },
    })
    deletedCount.value = resp.deleted.length
    blockedItems.value = resp.blocked
    if (resp.blocked.length) {
      blockedVisible.value = true
    } else {
      ElMessage.success(`已删除 ${resp.deleted.length} 个规则来源`)
    }
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function copyUrl(row) {
  urlContent.value = row.url
  urlCopied.value = false
  try {
    await navigator.clipboard.writeText(row.url)
    urlCopied.value = true
  } catch {
    try {
      const el = document.createElement('textarea')
      el.value = row.url
      document.body.appendChild(el)
      el.select()
      urlCopied.value = document.execCommand('copy')
      el.remove()
    } catch {
      urlCopied.value = false
    }
  }
  urlDialog.value = true
}

async function preview(row) {
  try {
    const data = await api(`/api/v1/rule-providers/${row.id}/content`)
    previewContent.value = data.content
    previewName.value = row.name
    previewDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.op-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.op-grid .el-button {
  width: 100%;
  margin: 0;
  padding-left: 4px;
  padding-right: 4px;
}
@media (max-width: 640px) {
  .op-grid { gap: 4px; }
  .op-grid .el-button { font-size: 12px; }
}
.mp-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .mp-pagination { justify-content: center; }
}
</style>
