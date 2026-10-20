<template>
  <div>
    <h2 class="mp-page-title">审计日志</h2>
    <p class="mp-page-desc">记录维护操作与设备下载；不含订阅地址、令牌或节点凭据。</p>

    <div class="mp-toolbar" style="margin-bottom:12px">
      <div class="left">
        <el-button size="small" :disabled="!selection.length" @click="removeSelected">
          删除选中（{{ selection.length }}）
        </el-button>
        <el-button size="small" type="danger" plain :disabled="!rows.length" @click="clearAll">
          清空全部
        </el-button>
      </div>
      <div class="right">
        <el-button size="small" :disabled="rows.length >= limit" @click="loadMore">
          加载更早记录
        </el-button>
      </div>
    </div>

    <EmptyState v-if="!rows.length" reason="暂无审计记录。" />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading" @selection-change="onSelect">
          <el-table-column type="selection" width="44" />
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.at) }}</template>
          </el-table-column>
          <el-table-column prop="actor" label="操作人" width="110" />
          <el-table-column prop="action" label="操作" min-width="150" />
          <el-table-column label="对象" min-width="130">
            <template #default="{ row }">
              <span v-if="row.object_type" class="mono">{{ row.object_type }}#{{ row.object_id }}</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="详情" min-width="220">
            <template #default="{ row }"><span class="mono">{{ row.detail || '—' }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { fmtTime } from '../format'

const rows = ref([])
const loading = ref(false)
const limit = ref(100)
const selection = ref([])

async function load() {
  loading.value = true
  try {
    rows.value = await api(`/api/v1/audit?limit=${limit.value}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function loadMore() {
  limit.value += 100
  load()
}

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
    selection.value = []
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
    selection.value = []
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>
