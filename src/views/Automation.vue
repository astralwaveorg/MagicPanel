<template>
  <div>
    <h2 class="mp-page-title">自动发布</h2>
    <p class="mp-page-desc">
      服务端按各来源的间隔自动抓取上游、按测速间隔自动测速；策略变化时按设定间隔创建构建并发布。
      发布历史只保留最近 10 条，完整操作记录仍可在审计日志中追溯。
      “立即运行一次”会忽略到期时间，强制执行一轮抓取、测速和构建检查。
    </p>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:12px">
        <div class="left">
          <StatusDot :kind="status.running ? 'warn' : 'ok'"
                     :text="status.running ? '正在运行' : '空闲'" />
          <span class="mp-toolbar-hint">上次运行：{{ fmtTime(status.last_tick_at) }}</span>
          <span v-if="!status.autostart" class="mp-toolbar-hint">后台循环未启动</span>
        </div>
        <el-button :loading="triggering" @click="runNow">立即运行一次</el-button>
      </div>
      <div class="mp-auto-status">
        <div>
          <span class="mp-auto-label">上轮结果</span>
          <span>{{ lastResultText }}</span>
        </div>
        <div v-if="status.last_error" style="color:var(--mp-danger)">
          <span class="mp-auto-label">错误</span>
          <span>{{ status.last_error }}</span>
        </div>
      </div>
      <el-form label-position="top" style="max-width:720px;margin-top:8px">
        <el-form-item label="启用服务端定时任务">
          <el-switch v-model="form.scheduler_enabled" />
          <span class="mp-form-hint" style="margin-left:12px">
            关闭后不再自动抓取、测速和构建，已经发布的内容不受影响
          </span>
        </el-form-item>
      </el-form>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <div class="mp-card">
          <h3>抓取与测速</h3>
          <el-form label-position="top">
            <el-form-item label="自动抓取节点来源">
              <el-switch v-model="form.auto_fetch_sources" />
            </el-form-item>
            <el-form-item label="自动测速节点来源">
              <el-switch v-model="form.auto_test_sources" />
            </el-form-item>
            <el-form-item label="自动抓取规则来源">
              <el-switch v-model="form.auto_fetch_rules" />
            </el-form-item>
          </el-form>
          <p class="mp-form-hint">
            每个来源的抓取/测速间隔在对应的来源页面配置，支持批量修改。测速需要已安装 Mihomo 核心。
          </p>
          <div class="mp-auto-links">
            <el-button size="small" @click="router.push('/admin/sources')">节点来源</el-button>
            <el-button size="small" @click="router.push('/admin/rule-providers')">规则来源</el-button>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="mp-card">
          <h3>自动构建与发布</h3>
          <el-form label-position="top">
            <el-form-item label="策略变化时自动创建构建">
              <el-switch v-model="form.auto_build_enabled" />
            </el-form-item>
            <el-form-item label="构建检查间隔（小时）">
              <el-input-number v-model="form.auto_build_interval_hours"
                               :min="1" :max="168" :step="1" style="width:180px" />
            </el-form-item>
            <el-form-item label="校验通过后自动发布">
              <el-switch v-model="form.auto_publish_enabled" />
            </el-form-item>
            <el-form-item label="发布通道">
              <el-select v-model="form.auto_publish_channel" style="width:180px"
                         :disabled="!form.auto_publish_enabled">
                <el-option value="stable" label="稳定" />
                <el-option value="candidate" label="候选" />
              </el-select>
            </el-form-item>
          </el-form>
          <p class="mp-form-hint">
            只有策略快照变化且校验通过才发布；失败的构建不会覆盖当前通道。
          </p>
        </div>
      </el-col>
    </el-row>

    <div class="mp-card" style="display:flex;justify-content:flex-end">
      <el-button type="primary" :loading="saving" @click="save">保存自动任务设置</el-button>
    </div>

    <div class="mp-card">
      <h3>最近运行（最多 10 次）</h3>
      <EmptyState v-if="!runs.length" reason="还没有运行记录。" />
      <div v-else class="mp-table-wrap">
        <el-table :data="runs" size="small">
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.at) }}</template>
          </el-table-column>
          <el-table-column label="触发" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.trigger === 'manual' ? 'warning' : 'info'"
                      effect="plain">
                {{ row.trigger === 'manual' ? '手动' : '定时' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作人" width="110">
            <template #default="{ row }">{{ row.summary?.actor || '—' }}</template>
          </el-table-column>
          <el-table-column label="结果" min-width="380">
            <template #default="{ row }">{{ resultText(row.summary) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>最近自动发布（最多 10 条）</h3>
      <EmptyState v-if="!releases.length" reason="还没有自动发布记录。" />
      <div v-else class="mp-table-wrap">
        <el-table :data="releases" size="small">
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="构建" width="90">
            <template #default="{ row }"><span class="mono">#{{ row.build_id }}</span></template>
          </el-table-column>
          <el-table-column label="动作" width="120">
            <template #default="{ row }">
              {{ row.action === 'promote' ? '发布' : '回滚' }}到{{ CHANNEL_LABELS[row.channel] }}
            </template>
          </el-table-column>
          <el-table-column label="操作人" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.operator === '系统'" size="small" type="success" effect="plain">
                系统
              </el-tag>
              <span v-else>{{ row.operator }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="说明" min-width="180">
            <template #default="{ row }">{{ row.reason || '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import { fmtTime, CHANNEL_LABELS } from '../format'

const router = useRouter()
const status = ref({ running: false, autostart: true, last_tick_at: '', last_result: null, last_error: '' })
const releases = ref([])
const runs = ref([])
const saving = ref(false)
const triggering = ref(false)
const form = reactive({
  scheduler_enabled: true,
  auto_fetch_sources: true,
  auto_test_sources: true,
  auto_fetch_rules: true,
  auto_build_enabled: true,
  auto_build_interval_hours: 12,
  auto_publish_enabled: true,
  auto_publish_channel: 'stable',
})

function resultText(r) {
  if (!r) return '暂无运行记录'
  const parts = []
  if (r.sources_fetched || r.sources_failed) {
    parts.push(`节点抓取 ${r.sources_fetched} 成功 / ${r.sources_failed} 失败`)
  }
  if (r.rules_fetched || r.rules_failed) {
    parts.push(`规则抓取 ${r.rules_fetched} 成功 / ${r.rules_failed} 失败`)
  }
  if (r.tests_run || r.tests_errors) {
    parts.push(`测速 ${r.tests_ok} 可用 / ${r.tests_failed} 失败`)
  }
  if (r.test_skipped) parts.push(r.test_skipped)
  if (r.build) {
    parts.push(typeof r.build === 'string'
      ? `构建：${r.build}`
      : `构建 #${r.build.id}（${r.build.status === 'success' ? '通过' : '失败'}）`)
  }
  if (r.published) parts.push(`已发布到${CHANNEL_LABELS[r.published]}`)
  if (r.build_error) parts.push(`构建错误：${r.build_error}`)
  if (r.errors?.length) parts.push(`${r.errors.length} 个抓取/测速错误`)
  if (r.skipped) parts.push(r.skipped)
  if (!parts.length) {
    return r.trigger === 'manual' ? '强制执行完成，没有可处理的项目' : '本轮没有到期任务'
  }
  return parts.join('；')
}

const lastResultText = computed(() => resultText(status.value.last_result))

function applySettings(s) {
  form.scheduler_enabled = s.scheduler_enabled === '1'
  form.auto_fetch_sources = s.auto_fetch_sources === '1'
  form.auto_test_sources = s.auto_test_sources === '1'
  form.auto_fetch_rules = s.auto_fetch_rules === '1'
  form.auto_build_enabled = s.auto_build_enabled === '1'
  form.auto_build_interval_hours = Number(s.auto_build_interval_hours) || 12
  form.auto_publish_enabled = s.auto_publish_enabled === '1'
  form.auto_publish_channel = s.auto_publish_channel === 'candidate' ? 'candidate' : 'stable'
}

async function load() {
  try {
    const [s, st, rel, runList] = await Promise.all([
      api('/api/v1/settings'), api('/api/v1/automation/status'),
      api('/api/v1/releases?auto_only=true'), api('/api/v1/automation/runs?limit=10'),
    ])
    applySettings(s)
    status.value = st
    releases.value = rel
    runs.value = runList
  } catch (e) {
    ElMessage.error(e.message)
  }
}
onMounted(load)

async function refreshStatus() {
  try {
    const [st, rel, runList] = await Promise.all([
      api('/api/v1/automation/status'),
      api('/api/v1/releases?auto_only=true'),
      api('/api/v1/automation/runs?limit=10'),
    ])
    status.value = st
    releases.value = rel
    runs.value = runList
  } catch { /* 状态刷新失败不打扰 */ }
}

async function save() {
  saving.value = true
  try {
    await api('/api/v1/settings', { method: 'PUT', body: { values: {
      scheduler_enabled: form.scheduler_enabled ? '1' : '0',
      auto_fetch_sources: form.auto_fetch_sources ? '1' : '0',
      auto_test_sources: form.auto_test_sources ? '1' : '0',
      auto_fetch_rules: form.auto_fetch_rules ? '1' : '0',
      auto_build_enabled: form.auto_build_enabled ? '1' : '0',
      auto_build_interval_hours: String(form.auto_build_interval_hours),
      auto_publish_enabled: form.auto_publish_enabled ? '1' : '0',
      auto_publish_channel: form.auto_publish_channel,
    } } })
    ElMessage.success('自动任务设置已保存')
    await refreshStatus()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function runNow() {
  if (triggering.value) return
  triggering.value = true
  const beforeTick = status.value.last_tick_at
  try {
    await api('/api/v1/automation/run', { method: 'POST' })
    ElMessage.success('已开始强制执行，正在等待运行结果…')
    let seenRunning = false
    let finished = false
    for (let i = 0; i < 200; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await refreshStatus()
      if (status.value.running) seenRunning = true
      if (!status.value.running && status.value.last_tick_at
          && status.value.last_tick_at !== beforeTick) {
        finished = true
        break
      }
      if (!status.value.running && !seenRunning && i >= 3) break
    }
    if (finished) {
      ElMessage.success('自动任务执行完成')
      await load()
    } else {
      ElMessage.warning('未获取到本轮结果，请稍后刷新查看运行记录')
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    triggering.value = false
  }
}
</script>

<style scoped>
.mp-auto-status {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--mp-text-secondary);
  padding: 10px 12px;
  border: 1px solid var(--mp-border);
  border-radius: 6px;
  background: var(--mp-surface-2);
}
.mp-auto-label { color: var(--mp-text); font-weight: 600; margin-right: 8px; }
.mp-auto-links { display: flex; gap: 8px; margin-top: 10px; }
.mp-auto-links .el-button { margin: 0; }
@media (max-width: 640px) {
  .mp-auto-status { font-size: 12.5px; }
}
</style>
