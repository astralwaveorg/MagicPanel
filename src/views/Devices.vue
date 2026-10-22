<template>
  <div>
    <h2 class="mp-page-title">设备管理</h2>
    <p class="mp-page-desc">
      每台设备一个固定订阅地址；令牌泄露可轮换使其失效，已下发的节点凭据需联系机场重置。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button @click="openBatch">批量修改</el-button>
          <el-button @click="removeSelected" type="danger" plain>批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
        </template>
      </div>
      <el-button :disabled="!targets.length" @click="openEdit()" type="primary">添加设备</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!targets.length"
      reason="还没有引擎平台，无法添加设备。"
      next="先在“引擎平台”中添加（引擎 + 平台）。"
    />
    <EmptyState
      v-else-if="!rows.length"
      reason="还没有设备。"
      next="点击“添加设备”；订阅地址只显示一次，请立即保存。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id" size="small"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="顺序" :width="isMobile ? 56 : 96" align="center">
            <template #default="{ row, $index }">
              <div class="order-cell">
                <span class="drag-handle" :data-id="row.id" title="按住拖动排序">⠿</span>
                <el-button text size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
                <el-button text size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="文件名" min-width="165" :fixed="isMobile ? false : 'left'">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="设备名" min-width="150">
            <template #default="{ row }">{{ row.display_name }}</template>
          </el-table-column>
          <el-table-column label="平台" width="90">
            <template #default="{ row }">{{ PLATFORM_LABELS[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column label="引擎平台" min-width="130">
            <template #default="{ row }">
              <span class="mono">{{ targetName(row.target_id) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="订阅环境" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.env === 'production' ? 'success' : 'warning'" effect="plain">
                {{ ENV_LABELS[row.env] || row.env }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近下载" min-width="150">
            <template #default="{ row }">
              <span class="mp-nowrap">{{ fmtTime(row.last_pull_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="pull_count" label="下载次数" width="90" align="right" />
          <el-table-column label="最近来源 IP" min-width="120">
            <template #default="{ row }"><span class="mono">{{ row.last_pull_ip || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="reveal(row)" type="info" plain>复制地址</el-button>
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" @click="rotate(row)" type="warning" plain>轮换令牌</el-button>
                <el-button size="small" @click="remove(row)" type="danger" plain>删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑设备' : '添加设备'" width="min(560px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item label="文件名">
          <el-input v-model="form.name" placeholder="例如：Stash-Macmini" />
          <div class="mp-form-hint">将作为下载配置的文件名（.yaml），并作为设备的唯一标识，请勿重复。</div>
        </el-form-item>
        <el-form-item label="引擎平台">
          <el-select v-model="form.target_id" style="width:100%" @change="onTargetChange">
            <el-option v-for="t in targets" :key="t.id" :value="t.id"
                       :label="`${t.name}（${ENGINE_LABELS[t.engine] || t.engine} / ${PLATFORM_LABELS[t.platform] || t.platform}）`" />
          </el-select>
          <div class="mp-form-hint">
            设备平台由所选引擎自动决定（当前：{{ PLATFORM_LABELS[form.platform] || form.platform }}）。
          </div>
        </el-form-item>
        <el-form-item label="订阅环境">
          <el-radio-group v-model="form.env">
            <el-radio value="production">生产环境（跟随正式发布）</el-radio>
            <el-radio value="testing">测试环境（提前试用）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="设备名">
          <el-input v-model="form.note" placeholder="例如：客厅 Mac mini" />
          <div class="mp-form-hint">用于界面展示；留空时默认使用文件名。</div>
        </el-form-item>
        <el-form-item label="设备独立配置">
          <div class="mp-form-hint">
            端口、DNS、日志等个性化配置，请前往「产物配置 → 设备独立配置」修改。
            该页面可查看配置的逐层继承来源。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button :loading="saving" @click="save" type="primary">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchDialog" title="批量修改设备" width="min(560px, 94vw)">
      <p class="mp-dialog-desc">
        将选中的 {{ selected.length }} 台设备按下面的设置统一修改。
        只勾选的项会生效：勾上但内容为空 = 清空该项；不勾 = 保持原样。
        换引擎平台时，设备的平台取值会跟着目标一起改。
      </p>
      <el-form :model="batch" label-position="top">
        <el-form-item>
          <el-checkbox v-model="batch.useTarget">修改引擎平台</el-checkbox>
        </el-form-item>
        <el-select v-if="batch.useTarget" v-model="batch.target_id" filterable style="width:100%"
                   placeholder="选择统一的引擎平台">
          <el-option v-for="t in targets" :key="t.id" :value="t.id"
                     :label="`${t.name}（${t.engine}/${t.platform}）`" />
        </el-select>

        <el-form-item>
          <el-checkbox v-model="batch.useEnv">修改订阅环境</el-checkbox>
        </el-form-item>
        <el-radio-group v-if="batch.useEnv" v-model="batch.env">
          <el-radio value="production">生产环境</el-radio>
          <el-radio value="testing">测试环境</el-radio>
        </el-radio-group>

        <el-form-item>
          <el-checkbox v-model="batch.useNote">修改设备名（备注）</el-checkbox>
        </el-form-item>
        <el-input v-if="batch.useNote" v-model="batch.note" placeholder="留空即清空" />
      </el-form>
      <template #footer>
        <el-button @click="batchDialog = false">取消</el-button>
        <el-button :loading="batchSaving" @click="saveBatch" type="primary">应用</el-button>
      </template>
    </el-dialog>

    <SecretDialog v-model:visible="secretVisible" :url="secretUrl" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { useRowSortable } from '../useRowSortable'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import SecretDialog from '../components/SecretDialog.vue'
import { fmtTime, PLATFORM_LABELS, ENV_LABELS, ENGINE_LABELS } from '../format'

const rows = ref([])
const isMobile = useMobile()
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const targets = ref([])
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const secretVisible = ref(false)
const secretUrl = ref('')
const selected = ref([])
const batchDialog = ref(false)
const batchSaving = ref(false)
const tableRef = ref(null)
const batch = reactive({
  useTarget: false, target_id: null,
  useEnv: false, env: 'production',
  useNote: false, note: '',
})

const sorter = useRowSortable(tableRef, rows, async (ids) => {
  try {
    await api('/api/v1/devices/reorder', { method: 'POST', body: ids })
    ElMessage.success('顺序已更新')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  }
  await load()
})

const emptyForm = () => ({
  name: '', platform: 'ios', target_id: null, env: 'production', note: '',
})
const form = reactive(emptyForm())

function onTargetChange(id) {
  const t = targets.value.find((x) => x.id === id)
  if (t) form.platform = t.platform
}

function targetName(id) {
  return targets.value.find((t) => t.id === id)?.name || `#${id}`
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
    const [paged, ts] = await Promise.all([
      api(`/api/v1/devices/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`),
      api('/api/v1/targets'),
    ])
    rows.value = paged.items
    total.value = paged.total
    targets.value = ts
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
  selected.value = []
  tableRef.value?.clearSelection()
}

async function move(index, delta) {
  const next = index + delta
  if (next < 0 || next >= rows.value.length) return
  const list = [...rows.value]
  const [item] = list.splice(index, 1)
  list.splice(next, 0, item)
  try {
    await api('/api/v1/devices/reorder', { method: 'POST', body: list.map((r) => r.id) })
    ElMessage.success('顺序已更新')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openBatch() {
  if (!selected.value.length) return
  batch.useTarget = false; batch.target_id = null
  batch.useEnv = false; batch.env = 'production'
  batch.useNote = false; batch.note = ''
  batchDialog.value = true
}

async function saveBatch() {
  if (!selected.value.length) return
  const payload = { ids: selected.value.map((r) => r.id) }
  if (batch.useTarget) payload.target_id = batch.target_id
  if (batch.useEnv) payload.env = batch.env
  if (batch.useNote) payload.note = batch.note
  const keys = Object.keys(payload).filter((k) => k !== 'ids')
  if (!keys.length) {
    ElMessage.warning('请至少勾选一项要修改的内容')
    return
  }
  batchSaving.value = true
  try {
    const resp = await api('/api/v1/devices/batch', { method: 'PATCH', body: payload })
    batchDialog.value = false
    ElMessage.success(`已更新 ${resp.updated} 台设备`)
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
    `删除选中的 ${ids.length} 台设备？订阅地址会立即失效，设备独立配置一并删除。`,
    '批量删除设备', { type: 'warning', confirmButtonText: '删除' })
  if (!ok) return
  try {
    const resp = await api('/api/v1/devices/batch/delete', {
      method: 'POST', body: { ids },
    })
    ElMessage.success(`已删除 ${resp.deleted.length} 台设备`
      + (resp.missing?.length ? `，${resp.missing.length} 台已不存在` : ''))
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, platform: row.platform, target_id: row.target_id,
    env: row.env, note: row.note,
  } : { target_id: targets.value[0]?.id ?? null })
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写文件名')
  if (!form.target_id) return ElMessage.warning('请选择引擎平台')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/devices/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      const created = await api('/api/v1/devices', { method: 'POST', body: form })
      secretUrl.value = created.subscription_url || ''
      secretVisible.value = true
    }
    dialog.value = false
    await load()
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function reveal(row) {
  try {
    const resp = await api(`/api/v1/devices/${row.id}/reveal`, { method: 'POST' })
    try {
      await navigator.clipboard.writeText(resp.subscription_url)
      ElMessage.success('订阅地址已复制')
    } catch {
      ElMessage.warning('复制失败，请到 Magic Panel 首页查看')
    }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function rotate(row) {
  if (!await confirmBox(
    `轮换 “${row.display_name || row.name}” 的令牌？旧订阅地址立即失效，设备需改用新地址。`,
    '轮换令牌', { type: 'warning', confirmButtonText: '轮换' },
  )) return
  try {
    const resp = await api(`/api/v1/devices/${row.id}/rotate-token`, { method: 'POST' })
    secretUrl.value = resp.subscription_url || ''
    secretVisible.value = true
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除设备 “${row.display_name || row.name}”？其订阅地址同时失效，下载文件名 “${row.name}” 也不再可用。`,
    '删除设备', { type: 'warning' },
  )) return
  try {
    await api(`/api/v1/devices/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

