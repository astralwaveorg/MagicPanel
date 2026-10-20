<template>
  <div>
    <h2 class="mp-page-title">分流规则</h2>
    <p class="mp-page-desc">
      按声明顺序从上到下首次匹配；最后一条必须是 MATCH 兜底。按住左侧手柄可拖动排序，调整顺序后立即生效于下一次构建。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加规则</el-button>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有分流规则。"
      next="点击“添加规则”；构建前至少需要一条 MATCH 兜底规则。"
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
          <el-table-column prop="type" label="类型" width="130">
            <template #default="{ row }"><span class="mono">{{ row.type }}</span></template>
          </el-table-column>
          <el-table-column label="匹配值" min-width="200">
            <template #default="{ row }"><span class="mono">{{ row.value || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="target" label="目标" min-width="110" />
          <el-table-column label="适用平台" min-width="150">
            <template #default="{ row }">
              <span v-if="!row.targets || !row.targets.length">全部</span>
              <span v-else>{{ row.targets.join('、') }}</span>
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
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
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
          <el-input v-model="form.value" class="mono"
                    :placeholder="form.type === 'IP-CIDR' ? '10.0.1.0/24' : 'example.com'" />
        </el-form-item>
        <el-form-item label="目标（策略组或内置动作）">
          <el-select v-model="form.target" filterable style="width:100%">
            <el-option v-for="g in groups" :key="g.name" :value="g.name" :label="g.name" />
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
            只在选中的引擎平台里生效；若该规则指向的策略组不适用于同一平台，规则会被自动剔除。
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

const ruleTypes = [
  'DOMAIN-SUFFIX', 'DOMAIN', 'DOMAIN-KEYWORD', 'IP-CIDR', 'IP-CIDR6',
  'GEOIP', 'RULE-SET', 'DST-PORT', 'MATCH',
]

const rows = ref([])
const groups = ref([])
const ruleProviders = ref([])
const targets = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const tableRef = ref(null)
const sorter = useRowSortable(tableRef, rows, async (ids) => {
  try {
    await api('/api/v1/rules/reorder', { method: 'POST', body: ids })
    ElMessage.success('顺序已更新')
  } catch (e) {
    ElMessage.error(e.message)
  }
  await load()
})

const NO_RESOLVE_TYPES = ['IP-CIDR', 'IP-CIDR6', 'GEOIP', 'RULE-SET', 'SRC-IP-CIDR']

const emptyForm = () => ({
  type: 'DOMAIN-SUFFIX', value: '', target: 'DIRECT', enabled: true, note: '',
  no_resolve: false, targets: [],
})
const form = reactive(emptyForm())
const isFinal = computed(() => ['MATCH', 'FINAL'].includes(form.type))
const canNoResolve = computed(() => NO_RESOLVE_TYPES.includes(form.type))

async function load() {
  loading.value = true
  try {
    const [rules, gs, rps, targetList] = await Promise.all([
      api('/api/v1/rules'), api('/api/v1/groups'), api('/api/v1/rule-providers'),
      api('/api/v1/targets'),
    ])
    rows.value = rules
    groups.value = gs
    ruleProviders.value = rps.filter((p) => p.enabled)
    targets.value = targetList
  } catch (e) {
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
  } : {})
  dialog.value = true
}

async function save() {
  saving.value = true
  try {
    const body = { ...form, value: isFinal.value ? '' : form.value }
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
