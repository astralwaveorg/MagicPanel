<template>
  <div>
    <ul class="mp-page-desc mp-desc-list">
      <li>服务端按各来源的间隔自动抓取上游、按测速间隔自动测速</li>
      <li>策略变化时按设定间隔创建构建并发布</li>
      <li>页面标题行的「立即发布」会忽略到期时间，强制执行一轮抓取、测速和构建检查</li>
    </ul>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:12px">
        <div class="left">
          <StatusDot :kind="status.running ? 'warn' : 'ok'"
                     :text="status.running ? '正在运行' : '空闲'" />
          <span class="mp-toolbar-hint">上次运行：{{ fmtTime(status.last_tick_at) }}</span>
          <span v-if="!status.autostart" class="mp-toolbar-hint">后台循环未启动</span>
        </div>
        <!-- 「立即发布」是页面级主操作，在标题行右侧，这里不再重复放一个 -->
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
        <div class="mp-switch-row">
          <span class="mp-switch-label">启用服务端定时任务</span>
          <el-switch v-model="form.scheduler_enabled" />
        </div>
      </el-form>
      <p class="mp-form-hint">
        关闭后不再自动抓取、测速和构建，已经发布的内容不受影响。
      </p>
    </div>

    <!-- 宽屏两卡片等高，窄屏按内容自然高度 -->
    <el-row :gutter="16" class="mp-equal-row">
      <el-col :xs="24" :md="12">
        <div class="mp-card mp-equal-card">
          <h3>抓取与测速</h3>
          <div class="mp-switch-row">
            <span class="mp-switch-label">自动抓取节点来源</span>
            <el-switch v-model="form.auto_fetch_sources" />
          </div>
          <div class="mp-switch-row">
            <span class="mp-switch-label">自动测速节点来源</span>
            <el-switch v-model="form.auto_test_sources" />
          </div>
          <div class="mp-switch-row">
            <span class="mp-switch-label">自动抓取规则来源</span>
            <el-switch v-model="form.auto_fetch_rules" />
          </div>
          <div class="mp-switch-row">
            <span class="mp-switch-label">自动抓取拓展模块</span>
            <el-switch v-model="form.auto_fetch_snippets" />
          </div>
          <p class="mp-form-hint">
            每个来源的抓取/测速间隔在对应的来源页面配置，支持批量修改。
          </p>
          <div class="mp-btn-grid mp-auto-links">
            <el-button size="small" @click="router.push('/admin/sources')">节点来源</el-button>
            <el-button size="small" @click="router.push('/admin/rule-providers')">规则来源</el-button>
            <el-button size="small" @click="router.push('/admin/snippets')">拓展模块</el-button>
          </div>
        </div>
      </el-col>
      <el-col :xs="24" :md="12">
        <div class="mp-card mp-equal-card">
          <h3>自动构建与发布</h3>
          <div class="mp-switch-row">
            <span class="mp-switch-label">策略变化时自动创建构建</span>
            <el-switch v-model="form.auto_build_enabled" />
          </div>
          <div class="mp-form-row">
            <span class="mp-switch-label">构建检查间隔（小时）</span>
            <el-input-number v-model="form.auto_build_interval_hours"
                             :min="1" :max="168" :step="1" class="mp-control-end" />
          </div>
          <div class="mp-switch-row">
            <span class="mp-switch-label">校验通过后自动构建发布</span>
            <el-switch v-model="form.auto_publish_enabled" />
          </div>
          <div class="mp-form-row">
            <span class="mp-switch-label">发布环境</span>
            <el-select v-model="form.auto_publish_env" class="mp-control-end"
                       :disabled="!form.auto_publish_enabled">
              <el-option value="production" label="生产环境" />
              <el-option value="testing" label="测试环境" />
            </el-select>
          </div>
          <p class="mp-form-hint">
            只有策略快照变化且校验通过才发布；失败的构建不会覆盖当前生效版本。
          </p>
        </div>
      </el-col>
    </el-row>

    <div class="mp-card" style="display:flex;justify-content:flex-end">
      <el-button :loading="saving" @click="saveAutoSettings" type="primary">保存自动任务设置</el-button>
    </div>

    <div class="mp-card">
      <h3>运行记录（最新 20 次）</h3>
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
          <el-table-column label="结果" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">{{ resultText(row.summary) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>最近自动构建发布（最新 20 次）</h3>
      <EmptyState v-if="!releases.length" reason="还没有自动构建发布记录。" />
      <div v-else class="mp-table-wrap">
        <el-table :data="releases" size="small">
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="构建" width="90">
            <template #default="{ row }"><span class="mono">#{{ row.build_id }}</span></template>
          </el-table-column>
          <el-table-column label="动作" width="130">
            <template #default="{ row }">{{ releaseActionText(row) }}</template>
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
// 「自动运行配置」面板：只管配置与记录，执行类动作在页面标题行。
// 状态与动作来自共享模块，与标题行的「立即发布」按钮同源。
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import StatusDot from './StatusDot.vue'
import EmptyState from './EmptyState.vue'
import { fmtTime } from '../format'
import {
  status, releases, runs, saving, form, lastResultText,
  loadAutoPublish, saveAutoSettings, releaseActionText, resultText,
} from '../useAutoPublish'

const router = useRouter()
onMounted(loadAutoPublish)
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
.mp-auto-links { margin-top: 10px; }
@media (max-width: 640px) {
  .mp-auto-status { font-size: 12.5px; }
}
</style>
