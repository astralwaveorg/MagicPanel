<template>
  <div>
    <h2 class="mp-page-title">策略组</h2>
    <p class="mp-page-desc">
      顺序即声明顺序；按住左侧手柄可拖动排序（分页时按当前页内的顺序重排）。地区筛选为空的组保留 <strong>空组保护</strong> 占位，避免被客户端隐式改写为直连。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加策略组</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有策略组。"
      next="点击“添加策略组”，先建入口组（如“节点选择”），再建地区自动组。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id">
          <el-table-column label="顺序" width="104" align="center">
            <template #default="{ row, $index }">
              <div class="order-cell">
                <span class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
                <el-button text size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
                <el-button text size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="110" />
          <el-table-column prop="type" label="类型" width="90" />
          <el-table-column label="适用平台" min-width="150">
            <template #default="{ row }">
              <span v-if="!row.targets || !row.targets.length">全部</span>
              <span v-else>{{ row.targets.join('、') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="隐藏" width="70">
            <template #default="{ row }">{{ row.hidden ? '隐藏' : '显示' }}</template>
          </el-table-column>
          <el-table-column label="包含策略组" min-width="380">
            <template #default="{ row }">{{ row.proxies.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="节点来源" min-width="140">
            <template #default="{ row }">{{ row.use_sources.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="本地节点" min-width="160">
            <template #default="{ row }">
              {{ localNodeNames(row.local_nodes) || '—' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑策略组' : '添加策略组'"
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
                <el-option value="select" label="select（手动选择）" />
                <el-option value="url-test" label="url-test（延迟测速）" />
                <el-option value="fallback" label="fallback（故障切换）" />
                <el-option value="load-balance" label="load-balance（负载均衡）" />
                <el-option value="relay" label="relay（链式转发）" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="form.type === 'relay'
          ? '成员（按顺序组成转发链，至少两个，仅限策略组、本地节点或 DIRECT / REJECT）'
          : '成员（其他策略组或 DIRECT / REJECT，按顺序）'">
          <el-select v-model="form.proxies" multiple filterable allow-create default-first-option
                     style="width:100%" placeholder="选择或输入">
            <el-option v-for="g in otherGroups" :key="g" :label="g" :value="g" />
            <el-option value="DIRECT" label="DIRECT（直连）" />
            <el-option value="REJECT" label="REJECT（拒绝）" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用引擎平台（不选 = 全部）">
          <el-select v-model="form.targets" multiple style="width:100%"
                     placeholder="不选表示适用于全部目标">
            <el-option v-for="t in targets" :key="t.name" :value="t.name" :label="t.name" />
          </el-select>
          <div class="mp-form-hint">
            只在选中的引擎平台里出现该策略组；指向它的规则会随之生效。
          </div>
        </el-form-item>
        <el-form-item label="本地节点（单节点，可多选）">
          <el-select v-model="form.local_nodes" multiple filterable style="width:100%">
            <el-option v-for="n in localNodes" :key="n.id" :value="n.id"
                       :disabled="!n.enabled"
                       :label="`${n.marked_name}（${n.protocol}）${n.enabled ? '' : ' · 已停用'}`" />
          </el-select>
        </el-form-item>
        <template v-if="form.type !== 'relay'">
          <el-form-item label="节点来源（从来源中取节点，可多选）">
            <el-select v-model="form.use_sources" multiple style="width:100%">
              <el-option v-for="s in sources" :key="s.name" :label="s.name" :value="s.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="过滤正则（仅保留匹配的节点，可选）">
            <el-input v-model="form.filter" class="mono" />
          </el-form-item>
        </template>
        <el-form-item v-if="form.type === 'load-balance'" label="分配策略（仅 Mihomo 目标生效）">
          <el-select v-model="form.strategy" style="width:100%">
            <el-option value="consistent-hashing" label="consistent-hashing（同目标固定节点）" />
            <el-option value="round-robin" label="round-robin（轮询）" />
            <el-option value="sticky-sessions" label="sticky-sessions（会话保持）" />
          </el-select>
        </el-form-item>
        <template v-if="hasHealthCheck">
          <el-form-item :label="form.type === 'relay' ? '测速地址（Stash 目标渲染为 benchmark-url）' : '测速地址'">
            <el-input v-model="form.url" class="mono" maxlength="512" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="间隔（秒）">
                <el-input-number v-model="form.interval" :min="30" :max="86400" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="超时（毫秒）">
                <el-input-number v-model="form.timeout" :min="100" :max="60000" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
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
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const sources = ref([])
const localNodes = ref([])
const targets = ref([])
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

const emptyForm = () => ({
  name: '', type: 'select', hidden: false, filter: '', use_sources: [],
  local_nodes: [], proxies: [],
  url: 'https://www.gstatic.com/generate_204', interval: 600, timeout: 8000,
  tolerance: 150, lazy: true, strategy: '', targets: [],
})
const form = reactive(emptyForm())

const hasHealthCheck = computed(() =>
  ['url-test', 'fallback', 'load-balance', 'relay'].includes(form.type),
)

const otherGroups = computed(() =>
  rows.value.map((g) => g.name).filter((n) => n !== editing.value?.name),
)

function localNodeNames(ids) {
  return (ids || [])
    .map((id) => localNodes.value.find((node) => node.id === id)?.marked_name)
    .filter(Boolean)
    .join('、')
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
    const [groups, srcs, nodes, targetList] = await Promise.all([
      api(`/api/v1/groups/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`),
      api('/api/v1/sources'), api('/api/v1/local-nodes'),
      api('/api/v1/targets'),
    ])
    rows.value = groups.items
    total.value = groups.total
    sources.value = srcs.filter((s) => s.enabled)
    localNodes.value = nodes
    targets.value = targetList
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
    name: row.name, type: row.type, hidden: row.hidden, filter: row.filter,
    use_sources: [...row.use_sources], local_nodes: [...(row.local_nodes || [])],
    proxies: [...row.proxies],
    url: row.url, interval: row.interval, timeout: row.timeout,
    tolerance: row.tolerance, lazy: row.lazy, strategy: row.strategy || '',
    targets: [...(row.targets || [])],
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    // 分配策略只对 load-balance 有意义，其余类型必须清空，否则后端直接拒绝
    const body = { ...form, strategy: form.type === 'load-balance' ? form.strategy : '' }
    if (editing.value) {
      await api(`/api/v1/groups/${editing.value.id}`, { method: 'PUT', body })
    } else {
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

async function move(index, delta) {
  const ids = rows.value.map((r) => r.id)
  const [id] = ids.splice(index, 1)
  ids.splice(index + delta, 0, id)
  try {
    await api('/api/v1/groups/reorder', { method: 'POST', body: ids })
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(`删除策略组 “${row.name}”？`, '删除策略组')) return
  try {
    await api(`/api/v1/groups/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
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
  gap: 0;
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
