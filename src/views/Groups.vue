<template>
  <div>
    <h2 class="mp-page-title">策略组</h2>
    <p class="mp-page-desc">
      为规则设置可用线路。拖动调整组的显示顺序。没有可用成员的组不会改走直连。
    </p>

    <VariantBar page="groups" v-model="variantId" @changed="onVariantsChanged" />

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button @click="openBatch">批量修改</el-button>
          <el-button @click="removeSelected" type="danger" plain>批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
      </div>
      <el-button @click="openEdit()" type="primary">添加策略组</el-button>
    </div>

    <div class="mp-toolbar mp-filter-bar">
      <div class="left">
        <el-input
          v-model="query"
          class="mp-filter-search"
          placeholder="搜索策略组名称"
          clearable
          :prefix-icon="Search"
          @input="onQueryInput"
        />
        <el-select v-model="filters.gtype" class="mp-filter-select" placeholder="全部类型"
                   clearable @change="applyFilter">
          <el-option value="select" label="手动选择" />
          <el-option value="url-test" label="自动测速" />
          <el-option value="fallback" label="故障切换" />
          <el-option value="load-balance" label="负载均衡" />
          <el-option value="relay" label="链式转发" />
        </el-select>
        <el-select v-model="filters.hidden" class="mp-filter-select" placeholder="全部可见性"
                   clearable @change="applyFilter">
          <el-option value="0" label="客户端可见" />
          <el-option value="1" label="客户端隐藏" />
        </el-select>
        <el-select v-model="filters.scope" class="mp-filter-select" placeholder="全部适用范围"
                   clearable @change="applyFilter">
          <el-option value="global" label="适用于所有平台与设备" />
          <el-option value="platform" label="限定了引擎平台" />
          <el-option value="device" label="限定了设备" />
        </el-select>
        <el-select v-model="filters.member" class="mp-filter-select" placeholder="全部成员构成"
                   clearable @change="applyFilter">
          <el-option value="source" label="含节点来源" />
          <el-option value="local" label="含本地节点" />
          <el-option value="manual" label="只靠指定成员" />
        </el-select>
        <el-button v-if="hasFilter" link @click="clearFilters">清空筛选</el-button>
      </div>
      <span class="mp-toolbar-hint">{{ countText }}</span>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!error && !rows.length && !hasFilter"
      reason="还没有策略组。"
      next="点击“添加策略组”，先建入口组（如“节点选择”），再建地区自动组。"
    />
    <EmptyState
      v-else-if="!error && !rows.length"
      reason="没有符合筛选条件的策略组。"
      next="没有符合筛选条件的结果。清除筛选后显示全部。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id" size="small"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="顺序" :width="isMobile ? 56 : 64" align="center">
            <template #default="{ row }">
              <!-- 筛选后组在列表里并不相邻，这时暂停排序以免打乱整体顺序 -->
              <span v-if="!hasFilter" class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="110" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ groupTypeLabel(row.type) }}</template>
          </el-table-column>
          <el-table-column label="适用引擎平台" min-width="150">
            <template #default="{ row }">
              <!-- 列里只给一行摘要，完整清单靠悬浮提示，避免行高被撑开 -->
              <el-tooltip placement="top" :show-after="200">
                <template #content>
                  <div class="mp-scope-tip">
                    <div>平台：{{ scopeText(row.targets) }}</div>
                    <div v-if="row.devices && row.devices.length">
                      设备：{{ scopeText(row.devices) }}
                    </div>
                  </div>
                </template>
                <span class="mp-scope-brief">{{ scopeBrief(row.targets, row.devices) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="客户端可见" width="100">
            <template #default="{ row }">{{ row.hidden ? '隐藏' : '显示' }}</template>
          </el-table-column>
          <el-table-column label="策略成员" width="160">
            <template #default="{ row }">
              <!-- 列里只给一行摘要，完整清单靠悬浮提示，避免行高被撑开 -->
              <el-tooltip v-if="row.proxies && row.proxies.length" placement="top" :show-after="200">
                <template #content>
                  <div class="mp-list-tip">
                    <div v-for="(p, i) in row.proxies" :key="i">{{ i + 1 }}. {{ p }}</div>
                  </div>
                </template>
                <span class="mp-list-brief">{{ proxiesBrief(row.proxies) }}</span>
              </el-tooltip>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="节点来源" width="120">
            <template #default="{ row }">
              <el-tooltip v-if="row.use_sources && row.use_sources.length" placement="top" :show-after="200">
                <template #content>
                  <div class="mp-list-tip">
                    <div v-if="hasAllScope(row.use_sources)">全部来源（含以后新增的）</div>
                    <template v-else>
                      <div v-for="(s, i) in row.use_sources" :key="i">{{ s }}</div>
                    </template>
                  </div>
                </template>
                <span class="mp-list-brief">{{ sourceBrief(row.use_sources) }}</span>
              </el-tooltip>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="本地节点" width="120">
            <template #default="{ row }">
              <el-tooltip v-if="localMembers(row).length" placement="top" :show-after="200">
                <template #content>
                  <div class="mp-list-tip">
                    <div v-for="(n, i) in localMembers(row)" :key="i">{{ i + 1 }}. {{ n }}</div>
                  </div>
                </template>
                <span class="mp-list-brief">{{ localNodeBrief(localMembers(row)) }}</span>
              </el-tooltip>
              <span v-else style="color:var(--mp-muted)">—</span>
            </template>
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

    <el-dialog :close-on-click-modal="false" v-model="dialog" :title="editing ? '编辑策略组' : '添加策略组'"
               width="min(620px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称">
              <el-input v-model="form.name" placeholder="例如：节点选择" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类型">
              <el-select v-model="form.type" style="width:100%">
                <el-option value="select" label="手动选择" />
                <el-option value="url-test" label="自动测速" />
                <el-option value="fallback" label="故障切换" />
                <el-option value="load-balance" label="负载均衡" />
                <el-option value="relay" label="链式转发" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="form.type === 'relay' ? '转发成员' : '策略成员'">
          <MultiSelectClear :has-value="form.proxies.length" @clear="form.proxies = []">
            <el-select v-model="form.proxies" multiple filterable allow-create default-first-option
                       collapse-tags aria-label="策略成员" style="width:100%" placeholder="搜索并添加成员">
              <el-option v-for="g in otherGroups" :key="g" :label="g" :value="g" />
              <el-option v-for="n in enabledLocalNodes" :key="n.display_name"
                         :label="n.display_name" :value="n.display_name" />
              <el-option value="DIRECT" label="DIRECT（直连）" />
              <el-option value="REJECT" label="REJECT（拒绝）" />
            </el-select>
          </MultiSelectClear>
          <SortableSelection v-model="form.proxies" label="策略成员顺序" />
          <div class="mp-form-hint">
            {{ form.type === 'relay' ? '至少选两个成员，流量按此顺序转发。' : '拖动或用箭头调整成员顺序。' }}
          </div>
        </el-form-item>
        <el-form-item label="适用引擎平台">
          <ScopeSelect v-model="form.targets" all-label="包含所有引擎平台"
                       :options="targetNames" />
          <div class="mp-form-hint">
            组和引用它的规则只发给所选平台。
          </div>
        </el-form-item>
        <el-form-item label="适用设备">
          <ScopeSelect v-model="form.devices" all-label="包含所有设备"
                       :options="deviceNames" />
          <div class="mp-form-hint">
            只发给所选设备。
          </div>
        </el-form-item>
        <el-form-item label="本地节点">
          <MultiSelectClear :has-value="selectedLocal.length" @clear="selectedLocal = []">
            <el-select v-model="selectedLocal" multiple filterable collapse-tags
                       aria-label="本地节点" placeholder="搜索并添加本地节点" style="width:100%">
              <el-option v-for="n in localNodes" :key="n.id" :value="n.display_name"
                         :disabled="!n.enabled"
                         :label="`${n.display_name}（${n.protocol}）${n.enabled ? '' : ' · 已停用'}`" />
            </el-select>
          </MultiSelectClear>
          <SortableSelection v-model="selectedLocal" label="本地节点顺序" />
          <div v-if="selectedLocal.length" class="mp-form-hint">
            <el-button link type="primary" @click="pinLocalFirst">本地节点置顶</el-button>
            <span>调整后，上面的成员顺序也会更新。</span>
          </div>
        </el-form-item>
        <template v-if="form.type !== 'relay'">
          <el-form-item label="节点来源">
            <ScopeSelect v-model="form.use_sources" all-label="包含所有来源"
                         :options="sourceNames" />
            <SortableSelection v-if="!hasAllScope(form.use_sources) && form.use_sources.length > 1"
                               v-model="form.use_sources" label="节点来源顺序" />
            <div class="mp-form-hint">
              逐项选择可调整来源顺序；「包含所有来源」会自动加入将来新增的来源。
            </div>
          </el-form-item>
          <el-form-item label="节点筛选（正则，可选）">
            <el-input v-model="form.filter" class="mono" />
          </el-form-item>
        </template>
        <el-form-item v-if="form.type === 'load-balance'" label="分配策略（仅 Mihomo 目标生效）">
          <el-select v-model="form.strategy" style="width:100%">
            <el-option value="consistent-hashing" label="consistent-hashing（同一目标固定到同一节点）" />
            <el-option value="round-robin" label="round-robin（轮询）" />
            <el-option value="sticky-sessions" label="sticky-sessions（会话保持）" />
          </el-select>
        </el-form-item>
        <template v-if="hasHealthCheck">
          <el-form-item :label="form.type === 'relay' ? '测速地址（Stash 目标渲染为 benchmark-url）' : '测速地址'">
            <el-input v-model="form.url" class="mono" maxlength="512" />
          </el-form-item>
          <!-- 一行最多两项 -->
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="间隔（秒）">
                <el-input-number v-model="form.interval" :min="30" :max="86400" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="超时（毫秒）">
                <el-input-number v-model="form.timeout" :min="100" :max="60000" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item v-if="form.type === 'url-test'" label="容差（毫秒）">
                <el-input-number v-model="form.tolerance" :min="0" :max="5000" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        <el-form-item>
          <el-checkbox v-model="form.hidden">在客户端中隐藏该组</el-checkbox>
          <el-checkbox v-if="['url-test','fallback','load-balance'].includes(form.type)" v-model="form.lazy">
            惰性测速（无流量时不测）
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
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

    <el-dialog :close-on-click-modal="false" v-model="batchDialog" title="批量修改策略组" width="min(620px, 94vw)">
      <p class="mp-dialog-desc">
        已选 {{ selected.length }} 个策略组。只替换勾选的项目，留空则清空该项。
        链式转发组不使用节点来源。
      </p>
      <el-form :model="batch" label-position="top">
        <el-form-item>
          <el-checkbox v-model="batch.useProxies">修改策略成员</el-checkbox>
        </el-form-item>
        <MultiSelectClear v-if="batch.useProxies"
                          :has-value="batch.proxies.length" @clear="batch.proxies = []">
          <el-select v-model="batch.proxies" multiple filterable allow-create default-first-option
                     style="width:100%" placeholder="选择或输入（留空即清空）">
            <el-option v-for="g in otherGroups" :key="g" :label="g" :value="g" />
            <el-option value="DIRECT" label="DIRECT（直连）" />
            <el-option value="REJECT" label="REJECT（拒绝）" />
          </el-select>
        </MultiSelectClear>
        <SortableSelection v-if="batch.useProxies && batch.proxies.length > 1"
                           v-model="batch.proxies" label="策略成员顺序" />

        <el-form-item>
          <el-checkbox v-model="batch.useTargets">修改适用引擎平台</el-checkbox>
        </el-form-item>
        <ScopeSelect v-if="batch.useTargets" v-model="batch.targets"
                     all-label="包含所有引擎平台" :options="targetNames" />

        <el-form-item>
          <el-checkbox v-model="batch.useLocalNodes">修改本地节点</el-checkbox>
        </el-form-item>
        <MultiSelectClear v-if="batch.useLocalNodes"
                          :has-value="batch.local_nodes.length" @clear="batch.local_nodes = []">
          <el-select v-model="batch.local_nodes" multiple filterable style="width:100%"
                     placeholder="留空即清空">
            <el-option v-for="n in localNodes" :key="n.id" :value="n.id"
                       :disabled="!n.enabled"
                       :label="`${n.display_name}（${n.protocol}）${n.enabled ? '' : ' · 已停用'}`" />
          </el-select>
        </MultiSelectClear>
        <SortableSelection v-if="batch.useLocalNodes && batch.local_nodes.length > 1"
                           v-model="batch.local_nodes" :labels="localLabels" label="本地节点顺序" />

        <el-form-item>
          <el-checkbox v-model="batch.useSources">修改节点来源</el-checkbox>
        </el-form-item>
        <ScopeSelect v-if="batch.useSources" v-model="batch.use_sources"
                     all-label="包含所有来源（含以后新增的）" :options="sourceNames" />
        <SortableSelection v-if="batch.useSources && !hasAllScope(batch.use_sources) && batch.use_sources.length > 1"
                           v-model="batch.use_sources" label="节点来源顺序" />

        <el-form-item>
          <el-checkbox v-model="batch.useFilter">修改过滤正则</el-checkbox>
        </el-form-item>
        <el-input v-if="batch.useFilter" v-model="batch.filter" class="mono"
                  placeholder="留空即清空过滤正则" />

        <el-form-item>
          <el-checkbox v-model="batch.useHidden">修改客户端可见性</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.useHidden" v-model="batch.hidden">
          <el-radio :value="false">显示</el-radio>
          <el-radio :value="true">隐藏</el-radio>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { ALL_SCOPE, hasAllScope, collapseIfComplete } from '../scopeOptions'
import { groupTypeLabel, scopeBrief, proxiesBrief, sourceBrief, localNodeBrief } from '../format'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import { useRefDialog } from '../useRefDialog'

const { refDialog, openRefDialog, onRefConfirm } = useRefDialog()
import Pager from '../components/Pager.vue'
import MultiSelectClear from '../components/MultiSelectClear.vue'
import ScopeSelect from '../components/ScopeSelect.vue'
import SortableSelection from '../components/SortableSelection.vue'
import ErrorState from '../components/ErrorState.vue'
import RefConfirmDialog from '../components/RefConfirmDialog.vue'
import VariantBar from '../components/VariantBar.vue'

const rows = ref([])
const isMobile = useMobile()
// 当前分流方案：0 = 默认方案；列表、新建、批量都限定在这个方案里
const variantId = ref(0)
// 全量组名（含跨页）：供「包含策略」等下拉点选引用
const allGroupNames = ref([])
const selected = ref([])
const batchDialog = ref(false)
const batchSaving = ref(false)
const batch = reactive({
  useProxies: false, proxies: [],
  useTargets: false, targets: [],
  useLocalNodes: false, local_nodes: [],
  useSources: false, use_sources: [],
  useFilter: false, filter: '',
  useHidden: false, hidden: false,
})
const total = ref(0)
const totalAll = ref(0)
const page = ref(1)
const limit = ref(50)

// 搜索与筛选：组多了以后光看列表找不动
const query = ref('')
const filters = reactive({ gtype: '', hidden: '', scope: '', member: '' })
const hasFilter = computed(() => !!query.value.trim() ||
  !!(filters.gtype || filters.hidden || filters.scope || filters.member))
const countText = computed(() => {
  if (!hasFilter.value) return `共 ${totalAll.value} 个策略组`
  return `筛选出 ${total.value} 个，共 ${totalAll.value} 个；筛选状态下不能拖动排序`
})

let queryTimer = null
function onQueryInput() {
  clearTimeout(queryTimer)
  queryTimer = setTimeout(applyFilter, 300)
}

function applyFilter() {
  page.value = 1
  load()
}

function clearFilters() {
  query.value = ''
  filters.gtype = ''
  filters.hidden = ''
  filters.scope = ''
  filters.member = ''
  applyFilter()
}
const sources = ref([])
const localNodes = ref([])
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
    await api('/api/v1/groups/reorder', { method: 'POST', body: ids })
    ElMessage.success('顺序已更新')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  }
  await load()
})

// 默认一律"包含所有"：新建的组/规则开箱即对全部平台、全部设备生效
const emptyForm = () => ({
  name: '', type: 'select', hidden: false, filter: '', use_sources: [ALL_SCOPE],
  local_nodes: [], proxies: [], local_first: false,
  url: 'https://www.gstatic.com/generate_204', interval: 600, timeout: 8000,
  tolerance: 150, lazy: true, strategy: '', targets: [ALL_SCOPE], devices: [ALL_SCOPE],
})
const form = reactive(emptyForm())

// 给 ScopeSelect 用的名称列表
const targetNames = computed(() => targets.value.map((t) => t.name))
const deviceNames = computed(() => devices.value.map((d) => d.name))
const sourceNames = computed(() => sources.value.map((x) => x.name))

// 适用范围展示："*" 是「包含所有」，不直接显示给用户
function scopeText(list) {
  if (!list || !list.length) return '不适用'
  if (list.includes(ALL_SCOPE)) return '全部'
  return list.join('、')
}

const hasHealthCheck = computed(() =>
  ['url-test', 'fallback', 'load-balance', 'relay'].includes(form.type),
)

const otherGroups = computed(() =>
  allGroupNames.value.filter((n) => n !== editing.value?.name),
)

// 可作为成员的本地节点：名字直接用接口给的 display_name，
// 前端不自己拼「名称 (类型)」——拼法变了就会对不上。
const enabledLocalNodes = computed(() =>
  (localNodes.value || []).filter((n) => n.enabled),
)

const localNames = computed(() => new Set(localNodes.value.map((node) => node.display_name)))
const localLabels = computed(() => Object.fromEntries(localNodes.value.map((node) => [node.id, node.display_name])))
const selectedLocal = computed({
  get: () => form.proxies.filter((name) => localNames.value.has(name)),
  set(next) {
    // 保持其他成员的位置。新增本地节点追加；调序只替换原有本地节点的位置。
    const chosen = new Set(next)
    const ordered = [...chosen]
    const rest = form.proxies.filter((name) => !localNames.value.has(name) || chosen.has(name))
    let index = 0
    form.proxies = [
      ...rest.map((name) => localNames.value.has(name) ? ordered[index++] : name),
      ...ordered.slice(index),
    ]
  },
})

function pinLocalFirst() {
  form.proxies = [...selectedLocal.value, ...form.proxies.filter((name) => !localNames.value.has(name))]
}

function localMembers(row) {
  const names = (row.proxies || []).filter((name) => localNames.value.has(name))
  const legacy = localNodeList(row.local_nodes)
  return [...new Set(row.local_first ? [...legacy, ...names] : [...names, ...legacy])]
}

function localNodeList(ids) {
  return (ids || [])
    .map((id) => localNodes.value.find((node) => node.id === id)?.display_name)
    .filter(Boolean)
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
    const params = new URLSearchParams({
      limit: String(limit.value),
      offset: String((page.value - 1) * limit.value),
      variant: String(variantId.value),
    })
    const kw = query.value.trim()
    if (kw) params.set('keyword', kw)
    if (filters.gtype) params.set('gtype', filters.gtype)
    if (filters.hidden) params.set('hidden', filters.hidden)
    if (filters.scope) params.set('scope', filters.scope)
    if (filters.member) params.set('member', filters.member)
    const [groups, srcs, nodes, targetList, deviceList, allGroups] = await Promise.all([
      api(`/api/v1/groups/page?${params.toString()}`),
      api('/api/v1/sources'), api('/api/v1/local-nodes'),
      api('/api/v1/targets'), api('/api/v1/devices'),
      // 候选组全量拉取：跨页的策略组也要能点选引用（不能只用当前页 rows）
      api(`/api/v1/groups?variant=${variantId.value}`),
    ])
    rows.value = groups.items ?? []
    total.value = groups.total
    totalAll.value = groups.total_all ?? groups.total
    sources.value = srcs.filter((s) => s.enabled)
    localNodes.value = nodes
    targets.value = targetList
    devices.value = deviceList
    allGroupNames.value = (allGroups ?? []).map((g) => g.name)
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
  await sorter.init()
}
onMounted(load)

function onVariantsChanged() {
  page.value = 1
  load()
}

// 切换方案即重载列表（方案之间互不可见）
watch(variantId, () => {
  page.value = 1
  load()
})

onBeforeUnmount(sorter.destroy)

function openEdit(row) {
  editing.value = row || null
  const local = localNodeList(row?.local_nodes)
  const proxies = row?.proxies || []
  const ordered = row?.local_first ? [...local, ...proxies] : [...proxies, ...local]
  Object.assign(form, emptyForm(), row ? {
    name: row.name, type: row.type, hidden: row.hidden, filter: row.filter,
    use_sources: [...row.use_sources], proxies: [...new Set(ordered)],
    url: row.url, interval: row.interval, timeout: row.timeout,
    tolerance: row.tolerance, lazy: row.lazy, strategy: row.strategy || '',
    targets: [...(row.targets || [])],
    devices: [...(row.devices || [])],
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    // 分配策略只对 load-balance 有意义，其余类型必须清空，否则后端直接拒绝
    const body = { ...form, strategy: form.type === 'load-balance' ? form.strategy : '' }
    // 平台和设备按范围处理。节点来源的显式列表有顺序，不能折叠成全部。
    body.targets = collapseIfComplete(body.targets, targets.value.map((t) => t.name))
    body.devices = collapseIfComplete(body.devices, devices.value.map((d) => d.name))
    if (editing.value) {
      // 编辑时不换方案：variant_id 跟随原组，后端也拒绝跨方案移动
      body.variant_id = editing.value.variant_id ?? 0
      await api(`/api/v1/groups/${editing.value.id}`, { method: 'PUT', body })
    } else {
      body.variant_id = variantId.value
      await api('/api/v1/groups', { method: 'POST', body })
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
  if (!await confirmBox(`删除策略组 “${row.name}”？`, '删除策略组',
    { type: 'warning', confirmButtonText: '删除' })) return
  try {
    await api(`/api/v1/groups/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e.status === 409 && e.detail?.code === 'group_in_use') {
      openRefDialog({
        title: `删除策略组“${row.name}”`,
        message: e.message,
        references: e.detail.references,
        hint: '删除时会自动解除其它策略组对它的成员引用，并删除指向它的分流规则。',
        action: () => forceDeleteGroup(row),
      })
      return
    }
    ElMessage.error(e.message)
  }
}

async function forceDeleteGroup(row) {
  refDialog.busy = true
  try {
    const resp = await api(`/api/v1/groups/${row.id}?force=1`, { method: 'DELETE' })
    refDialog.visible = false
    const n = resp.removed_rules?.length || 0
    const m = resp.detached_groups?.length || 0
    const parts = []
    if (m) parts.push(`解除 ${m} 个策略组的成员引用`)
    if (n) parts.push(`删除 ${n} 条分流规则`)
    ElMessage.success(parts.length ? `已删除，${parts.join('，')}` : '已删除')
    if (resp.warnings?.length) {
      ElMessage.warning(resp.warnings[0])
    }
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
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
  // 每次打开都重置：只保留"要改什么"的勾选，值取第一个选中项的当前值
  batch.useProxies = false; batch.proxies = []
  batch.useTargets = false; batch.targets = []
  batch.useLocalNodes = false; batch.local_nodes = []
  batch.useSources = false; batch.use_sources = []
  batch.useFilter = false; batch.filter = ''
  batch.useHidden = false; batch.hidden = false
  batchDialog.value = true
}

async function saveBatch() {
  if (!selected.value.length) return
  const payload = { ids: selected.value.map((r) => r.id) }
  if (batch.useProxies) payload.proxies = batch.proxies
  if (batch.useTargets) payload.targets = batch.targets
  if (batch.useLocalNodes) payload.local_nodes = batch.local_nodes
  if (batch.useSources) payload.use_sources = batch.use_sources
  if (batch.useFilter) payload.filter = batch.filter
  if (batch.useHidden) payload.hidden = batch.hidden
  const keys = Object.keys(payload).filter((k) => k !== 'ids')
  if (!keys.length) {
    ElMessage.warning('请至少勾选一项要修改的内容')
    return
  }
  batchSaving.value = true
  try {
    const resp = await api('/api/v1/groups/batch', { method: 'PATCH', body: payload })
    batchDialog.value = false
    ElMessage.success(`已更新 ${resp.updated} 个策略组`)
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

async function removeSelected() {
  if (!selected.value.length) return
  const ids = selected.value.map((r) => r.id)
  const ok = await confirmBox(
    `删除选中的 ${ids.length} 个策略组？被其它策略组或分流规则引用的会保留并说明原因。`,
    '批量删除策略组', { type: 'warning', confirmButtonText: '删除' })
  if (!ok) return
  try {
    const resp = await api('/api/v1/groups/batch/delete', {
      method: 'POST', body: { ids },
    })
    const withRefs = (resp.blocked || []).filter((b) => b.references?.length)
    if (withRefs.length) {
      openRefDialog({
        title: '部分策略组仍被引用',
        message: `有 ${withRefs.length} 个策略组仍被其它策略组或分流规则引用`,
        references: withRefs.flatMap((b) =>
          b.references.map((r) => ({ ...r, extra: r.extra || `策略组：${b.name}` }))),
        hint: '继续删除会自动解除成员引用，并删除指向它们的分流规则。',
        action: () => forceBatchDelete(ids),
      })
    } else if (resp.blocked?.length) {
      ElMessage.warning(
        `已删除 ${resp.deleted.length} 个；${resp.blocked.length} 个未删：`
        + resp.blocked.map((b) => `${b.name}（${b.reason}）`).join('；'), { duration: 9000 })
    } else {
      ElMessage.success(`已删除 ${resp.deleted.length} 个策略组`)
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
    const resp = await api('/api/v1/groups/batch/delete', {
      method: 'POST', body: { ids, force: true },
    })
    refDialog.visible = false
    const n = resp.removed_rules?.length || 0
    ElMessage.success(`已删除 ${resp.deleted.length} 个策略组，并删除 ${n} 条相关分流规则`)
    if (resp.warnings?.length) ElMessage.warning(resp.warnings[0])
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refDialog.busy = false
  }
}
</script>

