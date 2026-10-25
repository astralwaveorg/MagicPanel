<template>
  <div>
    <h2 class="mp-page-title">审计日志</h2>
    <p class="mp-page-desc">记录维护操作与设备下载；不含订阅地址、令牌或节点凭据。</p>

    <div class="mp-toolbar" style="margin-bottom:12px">
      <div class="mp-btn-grid mp-toolbar-actions">
        <el-button size="small" type="danger" plain :disabled="!selection.length" @click="removeSelected">
          删除选中（{{ selection.length }}）
        </el-button>
        <el-button size="small" :disabled="!total" @click="clearAll" type="danger" plain>
          清空全部
        </el-button>
      </div>
      <div class="mp-search-row">
        <el-input v-model="keyword" size="small" placeholder="搜索操作 / 操作人 / 详情"
                  clearable @keyup.enter="reload" @clear="reload" />
        <el-button size="small" @click="reload">搜索</el-button>
      </div>
    </div>

    <EmptyState v-if="!loading && !rows.length" reason="暂无审计记录。" />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading" @selection-change="onSelect" size="small">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.at) }}</template>
          </el-table-column>
          <el-table-column prop="actor" label="操作人" width="110" />
          <el-table-column prop="action" label="动作" min-width="150" />
          <el-table-column label="对象" min-width="130">
            <template #default="{ row }">
              <span v-if="row.object_type" class="mono">{{ row.object_type }}#{{ row.object_id }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="详情" min-width="200">
            <template #default="{ row }"><span class="mono">{{ row.detail || '—' }}</span></template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" :sizes="[50, 100, 200, 500]"
             @change="onPagerChange" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { fmtTime } from '../format'
import { useMobile } from '../mobile'

const isMobile = useMobile()
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const limit = ref(100)
const page = ref(1)
const keyword = ref('')
const selection = ref([])

async function load() {
  loading.value = true
  try {
    const offset = (page.value - 1) * limit.value
    const q = new URLSearchParams({ limit: String(limit.value), offset: String(offset) })
    if (keyword.value.trim()) q.set('keyword', keyword.value.trim())
    const data = await api(`/api/v1/audit?${q.toString()}`)
    rows.value = data.items
    total.value = data.total
    selection.value = []
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onPagerChange({ page: p, limit: l }) {
  if (l && l !== limit.value) {
    limit.value = l
    onSize(l)
    return
  }
  onPage(p)
}

function onPage(p) {
  page.value = p
  load()
}

function onSize(size) {
  limit.value = size
  reload()
}

onMounted(load)

function onSelect(list) {
  selection.value = list
}

async function removeSelected() {
  const ids = selection.value.map((r) => r.id)
  if (!ids.length) return
  if (!await confirmBox(`确定删除选中的 ${ids.length} 条审计记录？`, '删除记录',
                        { type: 'warning' })) return
  try {
    const r = await api('/api/v1/audit/delete', { method: 'POST', body: { ids } })
    ElMessage.success(`已删除 ${r.removed} 条记录`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function clearAll() {
  if (!await confirmBox('确定清空全部审计记录？该操作不可撤销。', '清空审计日志',
                        { type: 'warning' })) return
  try {
    const r = await api('/api/v1/audit/delete', { method: 'POST', body: { all: true } })
    ElMessage.success(`已清空 ${r.removed} 条记录`)
    page.value = 1
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>
