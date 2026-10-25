<template>
  <div>
    <h2 class="mp-page-title">分流策略</h2>
    <p class="mp-page-desc">
      规则按声明顺序自上而下首次匹配，最后一条须为 MATCH 兜底。按住左侧手柄拖动排序；分页时仅重排当前页，调整后于下一次构建生效。筛选后规则在列表里并不相邻，此时暂停排序以免打乱整体顺序。
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

    <div class="mp-toolbar mp-filter-bar">
      <div class="left">
        <el-input
          v-model="query"
          class="mp-filter-search"
          placeholder="搜索匹配值 / 目标 / 备注 / 类型"
          clearable
          :prefix-icon="Search"
          @input="onQueryInput"
        />
        <el-select v-model="filters.rtype" class="mp-filter-select" placeholder="全部类型"
                   clearable @change="applyFilter">
          <el-option v-for="t in ruleTypes" :key="t" :value="t" :label="t" />
        </el-select>
        <el-select v-model="filters.target" class="mp-filter-select" placeholder="全部目标"
                   clearable filterable @change="applyFilter">
          <el-option v-for="g in groups" :key="g.name" :value="g.name" :label="g.name" />
          <el-option value="DIRECT" label="DIRECT（直连）" />
          <el-option value="REJECT" label="REJECT（拒绝）" />
        </el-select>
        <el-select v-model="filters.enabled" class="mp-filter-select" placeholder="全部状态"
                   clearable @change="applyFilter">
          <el-option value="1" label="启用" />
          <el-option value="0" label="停用" />
        </el-select>
        <el-select v-model="filters.scope" class="mp-filter-select" placeholder="全部适用范围"
                   clearable @change="applyFilter">
          <el-option value="global" label="适用于所有平台与设备" />
          <el-option value="platform" label="限定了引擎平台" />
          <el-option value="device" label="限定了设备" />
        </el-select>
        <el-button v-if="hasFilter" link @click="clearFilters">清空筛选</el-button>
      </div>
      <span class="mp-toolbar-hint">{{ countText }}</span>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      :reason="hasFilter ? '没有符合筛选条件的规则。' : '还没有分流规则。'"
      :next="hasFilter ? '换个关键词，或点上方“清空筛选”看全部规则。' : '点击“添加规则”；构建前至少需要一条 MATCH 兜底规则。'"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id" size="small"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="顺序" :width="isMobile ? 56 : 104" align="center">
            <template #default="{ row, $index }">
              <div class="order-cell">
                <span v-if="!hasFilter" class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
                <el-button text size="small" :disabled="hasFilter || $index === 0" @click="move($index, -1)">↑</el-button>
                <el-button text size="small" :disabled="hasFilter || $index === rows.length - 1" @click="move($index, 1)">↓</el-button>
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
          <!-- no-resolve 与 Stash 修饰符是规则级细节，只在编辑弹窗与批量修改里出现 -->
          <el-table-column label="启用" width="80">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="140">
            <template #default="{ row }">
              <!-- 备注最多显示 8 个字，超出省略；完整内容靠悬浮提示 -->
              <el-tooltip v-if="row.note" placement="top" :show-after="200">
                <template #content>
                  <div class="mp-note-tip">{{ row.note }}</div>
                </template>
                <span class="mp-note-brief">{{ noteBrief(row.note) }}</span>
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
            <el-option value="REJECT-DROP" label="REJECT-DROP（静默丢弃）" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用引擎平台">
          <ScopeSelect v-model="form.targets" all-label="包含所有引擎平台"
                       :options="targetNames" />
          <div class="mp-form-hint">
            只在选中的引擎平台里生效；选「包含所有引擎平台」表示所有平台都生效。
            若该规则指向的策略组不适用于同一平台，规则会被自动剔除。
          </div>
        </el-form-item>
        <el-form-item label="适用设备">
          <ScopeSelect v-model="form.devices" all-label="包含所有设备"
                       :options="deviceNames" />
          <div class="mp-form-hint">
            个性化放这里：选了设备后，这条规则只出现在这些设备自己的产物里，
            同平台的其他设备不受影响；选「包含所有设备」表示所有设备。
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
        <el-form-item label="Stash 专属修饰符">
          <el-checkbox v-if="canNoTrack" v-model="form.no_track">
            不记入连接列表（命中的连接不显示在客户端连接页，流量统计照常）
          </el-checkbox>
          <el-checkbox v-if="canPreMatching" v-model="form.pre_matching">
            提前拒绝（连接还没建立就拒掉，广告类请求最省 CPU 与内存）
          </el-checkbox>
          <div class="mp-form-hint">
            这两项是 Stash 的能力，只有 Stash 产物会带上，Mihomo 产物不受影响。
            「提前拒绝」要求目标直接是 REJECT / REJECT-DROP，
            且只对 Stash iOS/tvOS 3.7+、macOS 4.4+ 生效——版本太旧的客户端可能加载失败。
          </div>
          <div v-if="form.pre_matching && !preMatchingTargetOk" class="mp-form-warn">
            「提前拒绝」的目标只能是 REJECT / REJECT-DROP，请把上面的目标改掉再保存
          </div>
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
        <ScopeSelect v-if="batch.useTargets" v-model="batch.targets"
                     all-label="包含所有引擎平台" :options="targetNames" />

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

        <el-form-item>
          <el-checkbox v-model="batch.useNoTrack">修改「不记入连接列表」</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.useNoTrack" v-model="batch.no_track">
          <el-radio :value="true">是</el-radio>
          <el-radio :value="false">否</el-radio>
        </el-radio-group>

        <el-form-item>
          <el-checkbox v-model="batch.usePreMatching">修改「提前拒绝」</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.usePreMatching" v-model="batch.pre_matching">
          <el-radio :value="true">是</el-radio>
          <el-radio :value="false">否</el-radio>
        </el-radio-group>
        <div v-if="batch.usePreMatching" class="mp-form-hint">
          目标不是 REJECT / REJECT-DROP 的规则会被跳过，兜底规则一律跳过。
        </div>
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
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { ALL_SCOPE, collapseIfComplete } from '../scopeOptions'
import { noteBrief, scopeBrief } from '../format'
import { Search } from '@element-plus/icons-vue'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ScopeSelect from '../components/ScopeSelect.vue'
import ErrorState from '../components/ErrorState.vue'

// 与后端 config.RULE_TYPES 保持一致（少一种就会导致该类型根本建不出来）
const ruleTypes = [
  'DOMAIN-SUFFIX', 'DOMAIN', 'DOMAIN-KEYWORD', 'DOMAIN-REGEX',
  'IP-CIDR', 'IP-CIDR6', 'GEOIP', 'GEOSITE', 'RULE-SET',
  'SRC-IP-CIDR', 'DST-PORT', 'PROCESS-NAME', 'MATCH',
]

const route = useRoute()
const router = useRouter()
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
  useNoTrack: false, no_track: false,
  usePreMatching: false, pre_matching: false,
})
const total = ref(0)
const totalAll = ref(0)
const page = ref(1)
const limit = ref(50)

// 搜索与筛选：规则条数多，定位靠翻页太慢
const query = ref('')
const filters = reactive({ rtype: '', target: '', enabled: '', scope: '' })
const hasFilter = computed(() => !!query.value.trim() ||
  !!(filters.rtype || filters.target || filters.enabled || filters.scope))
const countText = computed(() => {
  if (!hasFilter.value) return `共 ${totalAll.value} 条`
  return `筛选出 ${total.value} 条，共 ${totalAll.value} 条；筛选状态下不能拖动排序`
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
  filters.rtype = ''
  filters.target = ''
  filters.enabled = ''
  filters.scope = ''
  applyFilter()
}
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
// Stash 的 pre-matching 只能用"连接建立前就能判断"的规则类型
const PRE_MATCHING_TYPES = [
  'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-WILDCARD', 'DOMAIN-REGEX',
  'GEOSITE', 'IP-CIDR', 'IP-CIDR6', 'GEOIP', 'IP-ASN', 'DST-PORT', 'SRC-IP',
  'SRC-PORT', 'NETWORK', 'RULE-SET', 'AND', 'OR', 'NOT',
]
const PRE_MATCHING_TARGETS = ['REJECT', 'REJECT-DROP']

// 默认一律"包含所有"：新建的规则开箱即对全部平台、全部设备生效
const emptyForm = () => ({
  type: 'DOMAIN-SUFFIX', value: '', target: 'DIRECT', enabled: true, note: '',
  no_resolve: false, no_track: false, pre_matching: false,
  targets: [ALL_SCOPE], devices: [ALL_SCOPE],
})
const form = reactive(emptyForm())

// 适用范围展示："*" 是「包含所有」，不直接显示给用户
function scopeText(list) {
  if (!list || !list.length) return '不适用'
  if (list.includes(ALL_SCOPE)) return '全部'
  return list.join('、')
}
const targetNames = computed(() => targets.value.map((t) => t.name))
const deviceNames = computed(() => devices.value.map((d) => d.name))
const isFinal = computed(() => ['MATCH', 'FINAL'].includes(form.type))
const canNoResolve = computed(() => NO_RESOLVE_TYPES.includes(form.type))
// 兜底规则命中的是所有未列出的流量，勾上等于让客户端不记录任何连接
const canNoTrack = computed(() => !isFinal.value)
const canPreMatching = computed(() => PRE_MATCHING_TYPES.includes(form.type))
const preMatchingTargetOk = computed(
  () => PRE_MATCHING_TARGETS.includes(form.target))

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
    })
    const kw = query.value.trim()
    if (kw) params.set('keyword', kw)
    if (filters.rtype) params.set('rtype', filters.rtype)
    if (filters.target) params.set('target', filters.target)
    if (filters.enabled) params.set('enabled', filters.enabled)
    if (filters.scope) params.set('scope', filters.scope)
    const [paged, gs, rps, targetList, deviceList] = await Promise.all([
      api(`/api/v1/rules/page?${params.toString()}`),
      api('/api/v1/groups'), api('/api/v1/rule-providers'),
      api('/api/v1/targets'), api('/api/v1/devices'),
    ])
    rows.value = paged.items
    total.value = paged.total
    totalAll.value = paged.total_all ?? paged.total
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
onMounted(async () => {
  await load()
  await openFromQuery()
})
onBeforeUnmount(sorter.destroy)

// 支持从别处跳过来直接编辑某条规则：/admin/rules?edit=123
async function openFromQuery() {
  const id = Number(route.query.edit)
  if (!id) return
  const all = await api('/api/v1/rules')
  const row = all.find((r) => r.id === id)
  if (!row) {
    ElMessage.warning('这条规则已经不存在了')
    return
  }
  openEdit(row)
  router.replace({ path: '/admin/rules' })
}

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    type: row.type, value: row.value, target: row.target, enabled: row.enabled,
    note: row.note, no_resolve: row.no_resolve,
    no_track: !!row.no_track, pre_matching: !!row.pre_matching,
    targets: [...(row.targets || [])],
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
  batch.useNoTrack = false; batch.no_track = false
  batch.usePreMatching = false; batch.pre_matching = false
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
  if (batch.useNoTrack) payload.no_track = batch.no_track
  if (batch.usePreMatching) payload.pre_matching = batch.pre_matching
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

