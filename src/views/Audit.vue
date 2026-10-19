<template>
  <div>
    <h2 class="mp-page-title">审计日志</h2>
    <p class="mp-page-desc">记录维护操作与设备下载；不含订阅地址、令牌或节点凭据。</p>

    <EmptyState v-if="!rows.length" reason="暂无审计记录。" />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
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
      <div style="margin-top:12px;text-align:right">
        <el-button size="small" :disabled="rows.length >= limit" @click="loadMore">
          加载更早记录
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { fmtTime } from '../format'

const rows = ref([])
const loading = ref(false)
const limit = ref(100)

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
</script>
