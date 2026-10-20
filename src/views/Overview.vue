<template>
  <div>
    <h2 class="mp-page-title">概览</h2>
    <p class="mp-page-desc">
      下载成功仅代表客户端取回了文件，不代表配置已加载、VPN 已启动或规则已生效。
    </p>

    <ErrorState v-if="error" :error="error" @retry="load" />

    <div class="mp-card">
      <h3>发布通道</h3>
      <el-row :gutter="12">
        <el-col v-for="ch in ['stable', 'candidate']" :key="ch" :xs="24" :sm="12">
          <div class="mp-card" style="margin-bottom:8px">
            <h3>{{ CHANNEL_LABELS[ch] }}通道</h3>
            <template v-if="data.channels?.[ch]">
              <div>候选构建 <span class="mono">#{{ data.channels[ch].id }}</span></div>
              <div style="font-size:12.5px;color:var(--mp-text-secondary);margin-top:4px">
                发布时间 {{ fmtTime(data.channels[ch].created_at) }}<br />
                策略摘要 <span class="mono">{{ shortSha(data.channels[ch].policy_sha) }}</span>
              </div>
            </template>
            <div v-else style="font-size:13px;color:var(--mp-text-secondary)">
              尚未发布。在 <strong>构建发布</strong> 中创建候选构建并发布后，设备才能拉取配置。
            </div>
          </div>
        </el-col>
      </el-row>
    </div>

    <div v-if="data.health" class="mp-card">
      <h3>运行状态</h3>
      <div v-if="data.health.ok" class="mp-health-ok">
        <StatusDot kind="ok" text="一切正常" />
        <span class="mp-health-note">
          数据盘剩余 {{ data.health.disk_free_mb }} MB ·
          最近备份 {{ data.health.last_backup_at ? fmtTime(data.health.last_backup_at) : '—' }} ·
          测速核心 {{ data.health.core_available ? data.health.core_version : '未安装' }}
        </span>
      </div>
      <div v-else class="mp-health-issues">
        <div v-for="(issue, i) in data.health.issues" :key="i" class="mp-health-issue">
          <StatusDot kind="warn" :text="issue" />
        </div>
        <div class="mp-health-note">
          数据盘剩余 {{ data.health.disk_free_mb }} MB ·
          最近备份 {{ data.health.last_backup_at ? fmtTime(data.health.last_backup_at) : '—' }}
        </div>
      </div>
    </div>

    <div class="mp-card">
      <h3>节点来源</h3>
      <EmptyState
        v-if="!data.sources?.length"
        reason="还没有节点来源。"
        next="前往“节点来源”添加订阅地址并执行抓取。"
      />
      <div v-else class="mp-table-wrap">
        <el-table :data="data.sources" size="small">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="状态" min-width="110">
            <template #default="{ row }">
              <StatusDot v-bind="sourceStatus(row)" />
            </template>
          </el-table-column>
          <el-table-column label="节点数" width="80" align="right">
            <template #default="{ row }">{{ row.node_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="最近成功" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_fetched_at) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>节点可用率</h3>
      <EmptyState
        v-if="!data.sources?.length"
        reason="还没有节点来源。"
        next="前往“节点来源”添加订阅地址并执行测速。"
      />
      <template v-else>
        <p v-if="!testedSources.length" style="font-size:13px;color:var(--mp-text-secondary);margin:0">
          还没有测速数据。在 <strong>节点来源</strong> 执行测速后，这里汇总各来源可用率。
        </p>
        <div v-else class="avail-list">
          <div v-for="s in data.sources" :key="s.name" class="avail-row">
            <span class="avail-name">{{ s.name }}</span>
            <template v-if="s.tested_at">
              <el-progress
                :percentage="availRate(s)"
                :color="availColor(availRate(s))"
                :stroke-width="10"
                style="flex:1"
              >
                <span class="mono" style="font-size:12px">
                  {{ s.tested_ok }}/{{ s.tested_ok + s.tested_failed }} 可用
                </span>
              </el-progress>
              <span class="avail-meta">
                {{ s.filter_unavailable ? '过滤不可用：开' : '过滤不可用：关' }} ·
                {{ fmtTime(s.tested_at) }}
              </span>
            </template>
            <span v-else class="avail-meta">未测试</span>
          </div>
        </div>
      </template>
    </div>

    <div class="mp-card">
      <h3>设备最近下载</h3>
      <EmptyState
        v-if="!data.devices?.length"
        reason="还没有设备。"
        next="前往“设备管理”添加设备，取得固定订阅地址。"
      />
      <div v-else class="mp-table-wrap">
        <el-table :data="data.devices" size="small">
          <el-table-column label="文件名" min-width="120">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="设备名" min-width="110">
            <template #default="{ row }">{{ row.display_name || row.name }}</template>
          </el-table-column>
          <el-table-column label="平台" width="90">
            <template #default="{ row }">{{ PLATFORM_LABELS[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column label="通道" width="80">
            <template #default="{ row }">{{ CHANNEL_LABELS[row.channel] || row.channel }}</template>
          </el-table-column>
          <el-table-column label="最近下载" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_pull_at) }}</template>
          </el-table-column>
          <el-table-column prop="pull_count" label="下载次数" width="90" align="right" />
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>最近操作</h3>
      <EmptyState v-if="!data.recent_audit?.length" reason="暂无操作记录。" />
      <div v-else class="mp-table-wrap">
        <el-table :data="data.recent_audit" size="small">
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.at) }}</template>
          </el-table-column>
          <el-table-column prop="actor" label="操作人" width="110" />
          <el-table-column prop="action" label="操作" min-width="140" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { fmtTime, shortSha, sourceStatus, PLATFORM_LABELS, CHANNEL_LABELS } from '../format'

const data = ref({})
const error = ref('')

const testedSources = computed(() =>
  (data.value.sources || []).filter((s) => s.tested_at))

function availRate(s) {
  const total = (s.tested_ok || 0) + (s.tested_failed || 0)
  return total ? Math.round((s.tested_ok / total) * 100) : 0
}

// 可用率配色：每 10% 一档，从红逐步过渡到绿；30% 以上开始明显往绿色走。
// 以前只有"成功/失败"两色，30% 和 80% 看起来一样，看不出差别。
const AVAIL_COLORS = [
  '#e64a4a', // 0%
  '#ee5a45', // 10%
  '#f26a42', // 20%
  '#f47b42', // 30%
  '#f59444', // 40%
  '#eda94c', // 50%
  '#d6bb46', // 60%
  '#a9c34c', // 70%
  '#74bf52', // 80%
  '#45b25a', // 90%
  '#22a45a', // 100%
]

function availColor(percent) {
  const step = Math.min(10, Math.max(0, Math.floor((percent || 0) / 10)))
  return AVAIL_COLORS[step]
}

async function load() {
  error.value = ''
  try {
    data.value = await api('/api/v1/overview')
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.mp-health-ok, .mp-health-issues { display: flex; flex-direction: column; gap: 8px; }
.mp-health-note { font-size: 12.5px; color: var(--mp-text-secondary); }
.avail-list { display: flex; flex-direction: column; gap: 12px; }
.avail-row { display: flex; align-items: center; gap: 14px; }
.avail-name {
  width: 140px;
  flex-shrink: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.avail-meta { font-size: 12px; color: var(--mp-text-secondary); white-space: nowrap; }
@media (max-width: 768px) {
  .avail-row { flex-wrap: wrap; gap: 6px; }
  .avail-name { width: 100%; }
  .avail-meta { width: 100%; }
}
</style>
