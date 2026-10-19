<template>
  <div>
    <h2 class="mp-page-title">策略组</h2>
    <p class="mp-page-desc">
      顺序即声明顺序；地区筛选为空的组保留 <strong>空组保护</strong> 占位，避免被客户端隐式改写为直连。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加策略组</el-button>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有策略组。"
      next="点击“添加策略组”，先建入口组（如“节点选择”），再建地区自动组。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
          <el-table-column label="顺序" width="90" align="center">
            <template #default="{ $index }">
              <el-button text size="small" :disabled="$index === 0" @click="move($index, -1)">↑</el-button>
              <el-button text size="small" :disabled="$index === rows.length - 1" @click="move($index, 1)">↓</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="110" />
          <el-table-column prop="type" label="类型" width="90" />
          <el-table-column label="隐藏" width="70">
            <template #default="{ row }">{{ row.hidden ? '隐藏' : '显示' }}</template>
          </el-table-column>
          <el-table-column label="成员（引用）" min-width="180">
            <template #default="{ row }">{{ row.proxies.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="节点来源" min-width="140">
            <template #default="{ row }">{{ row.use_sources.join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="过滤正则" min-width="180">
            <template #default="{ row }"><span class="mono">{{ row.filter || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="测速地址" min-width="180">
            <template #default="{ row }">
              <span class="mono">{{ ['url-test','fallback'].includes(row.type) ? row.url : '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="间隔/超时/容差" width="150" align="center">
            <template #default="{ row }">
              <span v-if="['url-test','fallback'].includes(row.type)" class="mono">
                {{ row.interval }}/{{ row.timeout }}/{{ row.tolerance }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
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
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="成员（其他策略组或 DIRECT / REJECT，按顺序）">
          <el-select v-model="form.proxies" multiple filterable allow-create default-first-option
                     style="width:100%" placeholder="选择或输入">
            <el-option v-for="g in otherGroups" :key="g" :label="g" :value="g" />
            <el-option value="DIRECT" label="DIRECT（直连）" />
            <el-option value="REJECT" label="REJECT（拒绝）" />
          </el-select>
        </el-form-item>
        <el-form-item label="节点来源（从来源中取节点，可多选）">
          <el-select v-model="form.use_sources" multiple style="width:100%">
            <el-option v-for="s in sources" :key="s.name" :label="s.name" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="过滤正则（仅保留匹配的节点，可选）">
          <el-input v-model="form.filter" class="mono" />
        </el-form-item>
        <template v-if="['url-test','fallback'].includes(form.type)">
          <el-form-item label="测速地址">
            <el-input v-model="form.url" class="mono" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="间隔（秒）">
                <el-input-number v-model="form.interval" :min="30" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="超时（毫秒）">
                <el-input-number v-model="form.timeout" :min="100" :max="60000" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="容差（毫秒）">
                <el-input-number v-model="form.tolerance" :min="0" :max="5000" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        <el-form-item>
          <el-checkbox v-model="form.hidden">在客户端中隐藏该组</el-checkbox>
          <el-checkbox v-if="['url-test','fallback'].includes(form.type)" v-model="form.lazy">
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'

const rows = ref([])
const sources = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)

const emptyForm = () => ({
  name: '', type: 'select', hidden: false, filter: '', use_sources: [], proxies: [],
  url: 'https://www.gstatic.com/generate_204', interval: 600, timeout: 8000,
  tolerance: 150, lazy: true,
})
const form = reactive(emptyForm())

const otherGroups = computed(() =>
  rows.value.map((g) => g.name).filter((n) => n !== editing.value?.name),
)

async function load() {
  loading.value = true
  try {
    const [groups, srcs] = await Promise.all([
      api('/api/v1/groups'), api('/api/v1/sources'),
    ])
    rows.value = groups
    sources.value = srcs.filter((s) => s.enabled)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, type: row.type, hidden: row.hidden, filter: row.filter,
    use_sources: [...row.use_sources], proxies: [...row.proxies],
    url: row.url, interval: row.interval, timeout: row.timeout,
    tolerance: row.tolerance, lazy: row.lazy,
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/groups/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      await api('/api/v1/groups', { method: 'POST', body: form })
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
