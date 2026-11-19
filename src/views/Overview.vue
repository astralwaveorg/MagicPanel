<template>
  <div>
    <h2 class="mp-page-title">系统概览</h2>
    <p class="mp-page-desc">
      查看当前发布版本、节点来源和设备更新状态。
    </p>

    <ErrorState v-if="error" :error="error" @retry="load" />

    <!-- 概览瓦片：最关键的四件事一眼看完 -->
    <div class="stat-grid">
      <div class="mp-card stat-tile">
        <div class="stat-label">当前生产版本</div>
        <template v-if="data.release_state?.production">
          <div class="stat-main mono">构建 #{{ data.release_state.production.id }}</div>
          <div class="stat-sub">
            发布时间 {{ fmtTime(data.release_state.production.published_at
              || data.release_state.production.created_at) }}<br />
            策略摘要 <span class="mono">{{ shortSha(data.release_state.production.policy_sha) }}</span>
          </div>
        </template>
        <div v-else class="stat-empty">
          尚未发布
          <span>在「构建发布」生成配置并发布后，设备才能更新订阅</span>
        </div>
      </div>

      <div class="mp-card stat-tile">
        <div class="stat-label">基础连通样本</div>
        <template v-if="totalTested">
          <div class="stat-main" :style="{ color: availColor(totalRate) }">{{ totalRate }}%</div>
          <div class="stat-sub">
            <span class="mono">{{ totalOk }}/{{ totalTested }}</span> 个节点可用<br />
            测速于 {{ fmtTime(lastTestedAt) }}
          </div>
        </template>
        <div v-else class="stat-empty">
          暂无基础连通样本
          <span>由服务器通过节点发起，只反映服务器的连通情况</span>
        </div>
      </div>

      <div class="mp-card stat-tile">
        <div class="stat-label">设备</div>
        <div class="stat-main">
          {{ data.devices?.length || 0 }}<span class="stat-unit">台</span>
        </div>
        <div class="stat-sub">
          最近更新 {{ latestConfig ? fmtTime(latestConfig) : '—' }}<br />
          {{ configPulledRecently }}/{{ data.devices?.length || 0 }} 台最近 24 小时有配置拉取记录；是否加载成功另列
        </div>
        <div v-if="data.counts?.devices_stale > 0" class="stat-sub">
          <span class="mp-cell-flag">
            <i class="mp-dot warn" />{{ data.counts.devices_stale }} 台配置未更新
          </span>
        </div>
      </div>

      <div class="mp-card stat-tile">
        <div class="stat-label">策略规模</div>
        <div class="stat-main">
          {{ data.counts?.groups ?? '—' }}<span class="stat-unit">组</span>
          {{ data.counts?.rules ?? '—' }}<span class="stat-unit">条规则</span>
        </div>
        <div class="stat-sub">
          启用 {{ data.counts?.rules_enabled ?? '—' }}/{{ data.counts?.rules ?? '—' }} 条<br />
          规则来源 {{ data.rule_providers?.length ?? 0 }} 个（{{ providerIssues }} 个异常）
        </div>
      </div>

      <div class="mp-card stat-tile">
        <div class="stat-label">出口观测</div>
        <div class="stat-direct">
          <StatusDot :kind="directKind" :text="directTitle" />
          <el-button size="small" type="success" :loading="directLoading" @click="observeNow">
            {{ direct.path_evidence ? '重新检测' : '发起检测' }}
          </el-button>
        </div>
        <div v-if="direct.path_evidence" class="stat-sub">
          境外出口 <span class="mono">{{ direct.path_evidence.foreign?.ip || '—' }}</span>
          （{{ direct.path_evidence.foreign?.country_code || '未知' }}）<br />
          家宽出口 <span class="mono">{{ direct.path_evidence.domestic?.ip || '—' }}</span><br />
          观测于 {{ direct.checked_at ? fmtTime(direct.checked_at) : '时间未确认' }}
        </div>
        <div v-else-if="direct.egress?.ip" class="stat-sub">
          出口 <span class="mono">{{ direct.egress.ip }}</span><br />
          {{ direct.egress.country || direct.egress.country_code || '未知地区' }}
          · 观测于 {{ direct.checked_at ? fmtTime(direct.checked_at) : '时间未确认' }}
        </div>
        <div v-else class="stat-sub">尚未发起路径检测。点「发起检测」验证一次。</div>
        <div v-if="direct.path_evidence" class="stat-sub">路径结论：{{ direct.path_evidence.conclusion }}</div>
        <div v-else class="stat-sub">出口地区无法说明测速是否经过透明代理。点「发起检测」查看两条路径的结果。</div>
        <div v-if="directRequest.state.error" class="stat-sub">记录读取失败，可点击重试。</div>
      </div>

      <div class="mp-card stat-tile" v-loading="!data.release_state">
        <div class="stat-label">发布指针</div>
        <div class="stat-main mono">
          R{{ data.release_state?.release_revisions?.production ?? '—' }}
          <span class="stat-unit">/</span>
          T{{ data.release_state?.release_revisions?.testing ?? '—' }}
        </div>
        <div class="stat-sub">
          生产 revision <span class="mono">{{ data.release_state?.release_revisions?.production ?? '—' }}</span><br />
          测试 revision <span class="mono">{{ data.release_state?.release_revisions?.testing ?? '—' }}</span><br />
          发布失败会保留原指针，不会部分生效
        </div>
      </div>
    </div>


    <div v-if="data.release_state?.testing" class="mp-card">
      <h3>当前测试版本</h3>
      <div class="mp-health-note">
        构建 <span class="mono">#{{ data.release_state.testing.id }}</span>
        · 发布时间 {{ fmtTime(data.release_state.testing.published_at
          || data.release_state.testing.created_at) }}
        · 策略摘要 <span class="mono">{{ shortSha(data.release_state.testing.policy_sha) }}</span>
        · 验证通过后在「构建发布」推上生产
      </div>
    </div>

    <div class="mp-card">
      <h3>运行状态</h3>
      <div v-if="data.health" class="mp-health-ok">
        <StatusDot
          :kind="data.health.ok ? 'ok' : 'warn'"
          :text="data.health.ok ? '一切正常' : '存在待处理项'"
        />
        <div class="mp-health-note">
          测速核心
          {{ data.health.core_available ? coreVersionShort : '未安装（节点测速与核心校验不可用）' }}
          · 最近备份 {{ data.health.last_backup_at ? fmtTime(data.health.last_backup_at) : '—' }}
        </div>
        <div v-for="(issue, i) in data.health.issues" :key="i" class="mp-health-issue">
          <StatusDot kind="warn" :text="issue" />
        </div>
      </div>
    </div>

    <div class="mp-card">
      <h3>节点来源</h3>
      <EmptyState
        v-if="!data.sources?.length"
        reason="还没有节点来源。"
        next="前往「节点来源」添加订阅地址并执行抓取。"
      />
      <div v-else class="mp-table-wrap">
        <el-table :data="data.sources" size="small">
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="抓取状态" min-width="110">
            <template #default="{ row }">
              <StatusDot v-bind="sourceStatus(row)" />
            </template>
          </el-table-column>
          <!-- 数字列左对齐：右对齐时数字贴着列右边缘，和上一列隔得很远 -->
          <el-table-column label="节点数" width="90" align="left">
            <template #default="{ row }">{{ row.node_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="连通 / 已测" width="110" align="left">
            <template #default="{ row }">
              <span v-if="row.tested_ok + row.tested_failed > 0" class="mono">
                {{ row.tested_ok }}/{{ row.tested_ok + row.tested_failed }}
              </span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="最近成功" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_fetched_at) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div v-if="testedSources.length" class="mp-card">
      <h3>已测节点连通率</h3>
      <div class="avail-list">
        <div v-for="s in testedSources" :key="s.name" class="avail-row">
          <span class="avail-name">{{ s.name }}</span>
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
            {{ s.filter_unavailable ? '只分发可用节点：开' : '只分发可用节点：关' }} ·
            {{ fmtTime(s.tested_at) }}
          </span>
        </div>
      </div>
    </div>


  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { createScopedRequest } from '../v2/useScopedRequest'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { fmtTime, shortSha, sourceStatus } from '../format'

const overviewRequest = createScopedRequest((scope, signal) => api('/api/v1/overview', { signal }))
const directRequest = createScopedRequest((scope, signal) => api('/api/v1/direct-check', { signal }))
const data = computed(() => overviewRequest.state.data || {})
const error = computed(() => overviewRequest.state.error?.message || '')
const direct = computed(() => directRequest.state.data || {})
const directLoading = computed(() => directRequest.state.loading)
const directKind = computed(() => {
  const t = direct.value.path_evidence?.transparent_proxy
  if (t === 'active') return 'warn'
  if (t === 'bypassed') return 'ok'
  return 'warn'
})
const directTitle = computed(() => {
  const t = direct.value.path_evidence?.transparent_proxy
  if (t === 'active') return '境外经透明代理'
  if (t === 'bypassed') return '测速已旁路'
  return '路径未验证'
})

async function observeNow() {
  try {
    const entry = await api('/api/v1/direct-observe', { method: 'POST' })
    directRequest.state.data = entry
    directRequest.state.error = null
  } catch (e) {
    directRequest.state.error = e
  }
}

const testedSources = computed(() =>
  (data.value.sources || []).filter((s) => (s.tested_ok || 0) + (s.tested_failed || 0) > 0))

// 总体可用率：与「节点来源」页口径一致，按来源汇总
const totalOk = computed(() =>
  testedSources.value.reduce((sum, s) => sum + (s.tested_ok || 0), 0))
const totalTested = computed(() => testedSources.value.reduce(
  (sum, s) => sum + (s.tested_ok || 0) + (s.tested_failed || 0), 0))
const totalRate = computed(() =>
  totalTested.value ? Math.round((totalOk.value / totalTested.value) * 100) : 0)
const lastTestedAt = computed(() =>
  testedSources.value.map((s) => s.tested_at).sort().pop() || '')

// 只看「配置本体」的更新：规则集、节点来源这些子资源也会刷新拉取时间，
// 混在一起会让"设备很久没拿到新配置"这件事在概览上完全看不出来。
const latestConfig = computed(() => (data.value.devices || [])
  .map((d) => d.last_config_at).filter(Boolean).sort().pop() || '')

const configPulledRecently = computed(() => {
  const dayAgo = Date.now() - 24 * 3600 * 1000
  return (data.value.devices || []).filter((d) => {
    if (!d.last_config_at) return false
    const t = Date.parse(d.last_config_at)
    return Number.isFinite(t) && t >= dayAgo
  }).length
})

// 内核版本只展示到版本号，编译细节（go 版本/日期）不进概览
const coreVersionShort = computed(() => {
  const v = String(data.value.health?.core_version || '')
  const m = v.match(/v?[0-9]+\.[0-9]+\.[0-9]+/)
  return m ? `Mihomo Meta ${m[0]}` : v
})

const providerIssues = computed(() => (data.value.rule_providers || [])
  .filter((p) => p.enabled && p.last_status && p.last_status !== 'ok').length)

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

function loadDirect() {
  return directRequest.load('nas:last-observation')
}

async function load() {
  await Promise.all([overviewRequest.load('overview'), loadDirect()])
}

onMounted(load)
onUnmounted(() => { overviewRequest.cancel(); directRequest.cancel() })
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.stat-tile { margin-bottom: 0; }
.stat-label {
  font-size: 12.5px;
  color: var(--mp-text-secondary);
  margin-bottom: 6px;
}
.stat-main {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.3;
}
.stat-unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--mp-text-secondary);
  margin-left: 4px;
}
.stat-sub {
  font-size: 12.5px;
  color: var(--mp-text-secondary);
  margin-top: 6px;
  line-height: 1.7;
}
.stat-empty {
  font-size: 13.5px;
  color: var(--mp-text-secondary);
  line-height: 1.7;
}
.stat-empty span { font-size: 12.5px; }
.stat-direct {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
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
@media (max-width: 1024px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}

/* 全站窄屏断点 768px：以下单列，避免长 mono 文本被挤压 */
@media (max-width: 768px) {
  .stat-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .stat-grid { grid-template-columns: 1fr; }
  .avail-row { flex-wrap: wrap; gap: 6px; }
  .avail-name { width: 100%; }
  .avail-meta { width: 100%; }
}
</style>
