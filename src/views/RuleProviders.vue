<template>
  <div>
    <h2 class="mp-page-title">规则来源</h2>
    <p class="mp-page-desc">
      服务端抓取规则集并留存快照，构建引用后经订阅地址分发至设备；远程与内联来源独立更新。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing" @click="refreshMany(selected)" type="primary">抓取选中</el-button>
          <el-button :disabled="batchRefreshing" @click="openBatchInterval">修改抓取间隔</el-button>
          <el-button :disabled="batchRefreshing" @click="removeSelected" type="danger" plain>批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
        <template v-else>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing" @click="refreshMany()" type="primary">一键抓取</el-button>
          <span v-if="batchRefreshing" class="mp-toolbar-hint">
            正在抓取 {{ refreshDone }}/{{ refreshTotal }}…
          </span>
        </template>
      </div>
      <el-button @click="openEdit()" type="primary">添加规则来源</el-button>
    </div>

    <div class="mp-toolbar mp-filter-bar">
      <div class="left">
        <el-input
          v-model="query"
          class="mp-filter-search"
          placeholder="搜索名称或 URL"
          clearable
          :prefix-icon="Search"
          @input="onQueryInput"
        />
        <el-select v-model="filters.kind" class="mp-filter-select" placeholder="全部类型"
                   clearable @change="applyFilter">
          <el-option value="remote" label="远程 URL" />
          <el-option value="inline" label="内联内容" />
          <el-option value="repo" label="仓库托管" />
        </el-select>
        <el-select v-model="filters.behavior" class="mp-filter-select" placeholder="全部行为"
                   clearable @change="applyFilter">
          <el-option value="domain" label="域名" />
          <el-option value="ipcidr" label="IP 段" />
          <el-option value="classical" label="经典规则" />
        </el-select>
        <el-select v-model="filters.enabled" class="mp-filter-select" placeholder="全部状态"
                   clearable @change="applyFilter">
          <el-option value="1" label="启用" />
          <el-option value="0" label="停用" />
        </el-select>
        <el-select v-model="filters.status" class="mp-filter-select" placeholder="全部抓取结果"
                   clearable @change="applyFilter">
          <el-option value="ok" label="抓取成功" />
          <el-option value="failed" label="抓取失败" />
          <el-option value="none" label="没有抓取记录" />
        </el-select>
        <el-select v-model="filters.referenced" class="mp-filter-select" placeholder="全部引用情况"
                   clearable @change="applyFilter">
          <el-option value="1" label="被分流规则引用" />
          <el-option value="0" label="没被引用" />
        </el-select>
        <el-button v-if="hasFilter" link @click="clearFilters">清空筛选</el-button>
      </div>
      <span class="mp-toolbar-hint">{{ countText }}</span>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length && !hasFilter"
      reason="还没有规则来源。"
      next="点击“添加规则来源”：远程来源填 URL，内联来源直接粘贴规则内容。"
    />
    <EmptyState
      v-else-if="!rows.length"
      reason="没有符合筛选条件的规则来源。"
      next="换个关键词，或点上方“清空筛选”看全部规则来源。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id" size="small"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column prop="name" label="名称" min-width="110" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ KIND_LABELS[row.kind] || row.kind }}</template>
          </el-table-column>
          <el-table-column prop="behavior" label="行为" width="90" />
          <el-table-column prop="format" label="格式" width="90" />
          <el-table-column label="URL" width="110">
            <template #default="{ row }">
              <el-button v-if="row.kind === 'remote' && row.url" size="small" @click="copyUrl(row)" type="info" plain>复制 URL</el-button>
              <el-tooltip v-else-if="row.kind === 'repo' && row.repo_path"
                          :content="row.repo_path" placement="top">
                <span class="mp-cell-sub">仓库路径</span>
              </el-tooltip>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="抓取状态" min-width="110">
            <template #default="{ row }">
              <!-- 内联规则直接写在面板里，不存在抓取；仓库来源看的是同步状态 -->
              <StatusDot v-if="row.kind !== 'inline'" v-bind="sourceStatus(row)" />
              <el-tooltip v-if="row.kind !== 'inline' && row.last_status === 'failed' && row.rule_count"
                         :content="row.kind === 'repo'
                           ? `同步失败，客户端继续用上次同步的内容（${row.rule_count} 条）`
                           : `抓取失败，客户端继续用上次抓到的内容（${row.rule_count} 条）`"
                         placement="top">
                <span class="mp-cell-sub">仍用上次内容</span>
              </el-tooltip>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="规则数" width="90" align="right">
            <template #default="{ row }">{{ row.rule_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="摘要" min-width="130">
            <template #default="{ row }"><span class="mono mp-nowrap">{{ shortSha(row.sha256) }}</span></template>
          </el-table-column>
          <el-table-column label="被引用" min-width="170">
            <template #default="{ row }">
              <span v-if="!row.referenced_by || !row.referenced_by.length" class="mp-cell-sub">—</span>
              <el-link v-for="ref in (row.referenced_by || [])" :key="ref.id"
                       type="primary" class="mp-ref-link" :title="`跳到引用它的分流规则：${ref.target}`"
                       @click="gotoRule(ref)">
                {{ ref.target }}<span v-if="!ref.enabled">（已停用）</span>
              </el-link>
            </template>
          </el-table-column>
          <el-table-column label="抓取间隔" width="110" align="right">
            <template #default="{ row }">{{ row.kind === 'inline' ? '—' : row.interval }}</template>
          </el-table-column>
          <el-table-column label="最近成功" min-width="160">
            <template #default="{ row }"><span class="mp-nowrap">{{ fmtTime(row.last_fetched_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" :disabled="!row.has_content" @click="preview(row)" type="info" plain>内容</el-button>
                <el-button size="small" v-if="row.kind === 'remote'" :loading="row._refreshing" @click="refresh(row)" type="primary">抓取</el-button>
                <el-button size="small" v-else-if="row.kind === 'repo'" :loading="row._refreshing" @click="refresh(row)" type="primary">从仓库同步</el-button>
                <EnableToggle :enabled="row.enabled" :loading="row._toggling" @toggle="toggleEnabled(row)" />
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" @click="remove(row)" type="danger" plain>删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="pageSize" :total="total"
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
          <el-col :span="form.kind === 'remote' ? 12 : 24">
            <el-form-item label="格式">
              <el-select v-model="form.format" style="width:100%">
                <el-option value="yaml" label="yaml" />
                <el-option value="text" label="text" />
                <el-option value="mrs" label="mrs" />
              </el-select>
            </el-form-item>
          </el-col>
          <!-- 内联内容由本机维护，没有抓取这回事 -->
          <el-col v-if="form.kind === 'remote'" :span="12">
            <el-form-item label="抓取间隔（秒）">
              <el-input-number v-model="form.interval" :min="600" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item :label="form.kind === 'remote'
              ? '客户端更新间隔（秒，0 = 跟随抓取间隔）'
              : '客户端更新间隔（秒）'">
              <el-input-number v-model="form.client_interval" :min="0" :max="604800" style="width:100%" />
            </el-form-item>
            <div v-if="form.kind === 'inline'" class="mp-form-hint">
              内联内容由本机维护：改完保存，构建时即刻生效，客户端按上面的间隔重新拉取。
            </div>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用</el-checkbox>
        </el-form-item>
        <el-form-item v-if="form.kind === 'remote'">
          <el-checkbox v-model="form.use_proxy">
            抓取走代理（服务端直连抓不到这个规则集时，经指定代理中转）
          </el-checkbox>
        </el-form-item>
        <el-form-item v-if="form.kind === 'remote' && form.use_proxy" label="代理地址">
          <el-input v-model="form.proxy_url" class="mono" :placeholder="PROXY_HINT" />
          <div class="mp-form-hint" style="margin-top:6px">
            <template v-if="currentProxy">当前：{{ currentProxy }}　</template>
            留空表示使用默认地址 {{ PROXY_HINT }}；需要直连就取消上面的勾选。
            面板跑在 NAS 上，这里要填 Mac mini 的内网地址，不要写 127.0.0.1。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
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
        <el-button v-for="p in INTERVAL_PRESETS" :key="p.value" size="small" :type="batchInterval === p.value ? 'primary' : 'default'" @click="batchInterval = p.value">{{ p.label }}</el-button>
      </div>
      <template #footer>
        <el-button @click="intervalDialog = false">取消</el-button>
        <el-button :loading="savingInterval" @click="saveBatchInterval" type="primary">应用</el-button>
      </template>
    </el-dialog>

    <RefConfirmDialog
      v-model:visible="refDialog.visible"
      :title="refDialog.title"
      :message="refDialog.message"
      :references="refDialog.references"
      :warnings="refDialog.warnings"
      :hint="refDialog.hint"
      :confirm-text="refDialog.confirmText"
      :busy="refDialog.busy"
      @confirm="onRefConfirm"
    />

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
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import StatusDot from '../components/StatusDot.vue'
import EnableToggle from '../components/EnableToggle.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import Pager from '../components/Pager.vue'
import BatchResultDialog from '../components/BatchResultDialog.vue'
import RefConfirmDialog from '../components/RefConfirmDialog.vue'
import { fmtTime, shortSha, sourceStatus } from '../format'

// 来源类型三态：远程 / 内联 / 仓库（仓库托管由自主维护同步而来）
const KIND_LABELS = { remote: '远程', inline: '内联', repo: '仓库' }
const INTERVAL_PRESETS = [  { label: '15 分钟', value: 900 },
  { label: '1 小时', value: 3600 },
  { label: '6 小时', value: 21600 },
  { label: '1 天', value: 86400 },
  { label: '7 天', value: 604800 },
]

const router = useRouter()
const rows = ref([])
const isMobile = useMobile()
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
const refDialog = reactive({
  visible: false, title: '', message: '', references: [], warnings: [],
  hint: '', confirmText: '删除并解除关联', busy: false, action: null,
})
const blockedVisible = ref(false)
const blockedItems = ref([])
const deletedCount = ref(0)
const query = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const totalAll = ref(0)

// 搜索与筛选：规则来源有几十个，靠翻页找不动
const filters = reactive({
  kind: '', behavior: '', enabled: '', status: '', referenced: '',
})
const hasFilter = computed(() => !!query.value.trim() ||
  !!(filters.kind || filters.behavior || filters.enabled || filters.status
     || filters.referenced))
const countText = computed(() => {
  if (!hasFilter.value) return `共 ${totalAll.value} 个规则来源`
  return `筛选出 ${total.value} 个，共 ${totalAll.value} 个`
})

let queryTimer = null
function onQueryInput() {
  clearTimeout(queryTimer)
  queryTimer = setTimeout(applyFilter, 300)
}

function applyFilter() {
  page.value = 1
  clearSelection()
  load()
}

function clearFilters() {
  query.value = ''
  filters.kind = ''
  filters.behavior = ''
  filters.enabled = ''
  filters.status = ''
  filters.referenced = ''
  applyFilter()
}

function onPagerChange({ page: p, limit: l }) {
  const sizeChanged = l && l !== pageSize.value
  if (l) pageSize.value = l
  page.value = sizeChanged ? 1 : p
  clearSelection()
  load()
}

const emptyForm = () => ({
  name: '', behavior: 'domain', format: 'yaml', kind: 'remote', client_interval: 0,
  url: '', inline_content: '', interval: 86400, enabled: true,
  use_proxy: false, proxy_url: '', current_proxy: '',
})
const form = reactive(emptyForm())

// 抓取走代理时的默认地址：Mac mini 上的 Stash 混合端口。
// 面板跑在 NAS 上、抓取也是从 NAS 出网，所以这里必须写 Mac mini 的内网地址；
// 写 127.0.0.1 会连到 NAS 自己（实测 connection refused）。
const PROXY_HINT = 'http://10.0.1.8:7890'
const currentProxy = computed(() => form.current_proxy || '')

// 启停：只改启用状态，别的字段一个都不动
async function toggleEnabled(row) {
  row._toggling = true
  try {
    const updated = await api(`/api/v1/rule-providers/${row.id}/enabled`, {
      method: 'PATCH', body: { enabled: !row.enabled },
    })
    Object.assign(row, updated)
    ElMessage.success(updated.enabled ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row._toggling = false
  }
}

// 跳到引用了这条规则来源的分流规则，直接打开编辑弹窗
function gotoRule(ref) {
  router.push({ path: '/admin/rules', query: { edit: String(ref.id) } })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({
      limit: String(pageSize.value),
      offset: String((page.value - 1) * pageSize.value),
    })
    const kw = query.value.trim()
    if (kw) params.set('keyword', kw)
    if (filters.kind) params.set('kind', filters.kind)
    if (filters.behavior) params.set('behavior', filters.behavior)
    if (filters.enabled) params.set('enabled', filters.enabled)
    if (filters.status) params.set('status', filters.status)
    if (filters.referenced) params.set('referenced', filters.referenced)
    const paged = await api(`/api/v1/rule-providers/page?${params.toString()}`)
    rows.value = paged.items
    total.value = paged.total
    totalAll.value = paged.total_all ?? paged.total
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
    use_proxy: !!row.use_proxy, proxy_url: '', current_proxy: row.proxy_url_masked || '',
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
    if (body.use_proxy) {
      body.proxy_url = (body.proxy_url || '').trim() || PROXY_HINT
    } else {
      body.proxy_url = ''
    }
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
    if (e.status === 409 && e.detail?.code === 'rule_provider_in_use' && e.detail?.rename_to) {
      openRefDialog({
        title: `重命名规则来源“${e.detail.provider.name}”`,
        message: e.message,
        references: e.detail.references,
        hint: `改名后，上面这些分流规则会自动改为引用新名字“${e.detail.rename_to}”。`,
        confirmText: '改名并同步引用',
        action: () => forceRenameProvider(editing.value, body),
      })
      return
    }
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
    if (!silent) {
      ElMessage.success(row.kind === 'repo'
        ? `已从仓库同步：${updated.rule_count} 条规则`
        : `抓取成功：${updated.rule_count} 条规则`)
    }
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
  // 不传列表时抓全部远程来源（表格现在只显示当前页）
  const pool = list || await api('/api/v1/rule-providers')
  const targets = (pool || []).filter((r) => r && r.kind === 'remote')
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

function openRefDialog({ title, message, references, warnings = [], hint, action, confirmText }) {
  Object.assign(refDialog, {
    visible: true, title, message, references, warnings, hint,
    confirmText: confirmText || '删除并解除关联', busy: false, action,
  })
}

async function onRefConfirm() {
  if (refDialog.action) await refDialog.action()
}

async function forceRenameProvider(row, body) {
  refDialog.busy = true
  try {
    await api(`/api/v1/rule-providers/${row.id}?force=1`, { method: 'PUT', body })
    refDialog.visible = false
    dialog.value = false
    ElMessage.success('已改名，分流规则引用同步更新')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除规则来源 “${row.name}”？删除前会校验分流规则引用；仍被引用的会先提示引用关系。`,
    '删除规则来源',
  )) return
  try {
    await api(`/api/v1/rule-providers/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e.status === 409 && e.detail?.code === 'rule_provider_in_use') {
      openRefDialog({
        title: `删除规则来源“${row.name}”`,
        message: e.message,
        references: e.detail.references,
        hint: '删除时会一并删除上面这些引用该规则集的分流规则。',
        action: () => forceDeleteProvider(row),
      })
      return
    }
    ElMessage.error(e.message)
  }
}

async function forceDeleteProvider(row) {
  refDialog.busy = true
  try {
    const resp = await api(`/api/v1/rule-providers/${row.id}?force=1`, { method: 'DELETE' })
    refDialog.visible = false
    const n = resp.deleted_rules?.length || 0
    ElMessage.success(n ? `已删除，并同时删除 ${n} 条引用它的分流规则` : '已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
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
    const withRefs = resp.blocked.filter((b) => b.references?.length)
    if (withRefs.length) {
      openRefDialog({
        title: '部分规则来源仍被引用',
        message: `有 ${withRefs.length} 个规则来源仍被分流规则引用`,
        references: withRefs.flatMap((b) =>
          b.references.map((r) => ({ ...r, extra: `来源：${b.name}` }))),
        hint: '继续删除会一并删除引用它们的分流规则。',
        action: () => forceBatchDelete(ids),
      })
    } else if (resp.blocked.length) {
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

async function forceBatchDelete(ids) {
  refDialog.busy = true
  try {
    const resp = await api('/api/v1/rule-providers/batch/delete', {
      method: 'POST', body: { ids, force: true },
    })
    refDialog.visible = false
    const n = resp.deleted_rules?.length || 0
    ElMessage.success(`已删除 ${resp.deleted.length} 个规则来源，并删除 ${n} 条相关分流规则`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
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
    previewContent.value = data.binary
      ? `（${row.format} 二进制格式，${data.size} 字节，无可读原文）`
      : data.content
    previewName.value = row.name
    previewDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
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
