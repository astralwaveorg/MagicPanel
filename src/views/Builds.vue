<template>
  <div>
    <h2 class="mp-page-title">构建发布</h2>
    <p class="mp-page-desc">
      构建把当前策略固化为不可变快照并逐目标校验。构建有四种状态：已构建、测试中、生产中、已下线；同一时刻只有一个生产版本和一个测试版本。发布后客户端需下一次拉取才生效。
    </p>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:0">
        <div class="left" style="flex-direction:column;align-items:flex-start;gap:8px">
          <div class="release-list">
            <div class="release-line">
              <span class="release-dot">🟢</span>
              <span class="release-label">当前生产版本：</span>
              <template v-if="releaseState.production">
                <span class="mono">构建 #{{ releaseState.production.id }}</span>
                <span class="release-time">
                  （发布于 {{ fmtTime(publishedAt(releaseState.production)) }}）
                </span>
                <span v-if="releaseState.production.published_by" class="release-meta">
                  {{ releaseState.production.published_by }}
                </span>
                <span v-if="releaseState.production.publish_reason" class="release-reason">
                  {{ releaseState.production.publish_reason }}
                </span>
                <el-button size="small" text type="primary"
                           @click="openDetail(releaseState.production)">查看详情</el-button>
              </template>
              <span v-else class="release-empty">暂无生效版本</span>
            </div>

            <div class="release-line">
              <span class="release-dot">🟡</span>
              <span class="release-label">当前测试版本：</span>
              <template v-if="releaseState.testing">
                <span class="mono">构建 #{{ releaseState.testing.id }}</span>
                <span class="release-time">
                  （发布于 {{ fmtTime(publishedAt(releaseState.testing)) }}）
                </span>
                <span v-if="releaseState.testing.published_by" class="release-meta">
                  {{ releaseState.testing.published_by }}
                </span>
                <span v-if="releaseState.testing.publish_reason" class="release-reason">
                  {{ releaseState.testing.publish_reason }}
                </span>
                <el-button size="small" text type="primary"
                           @click="openDetail(releaseState.testing)">查看详情</el-button>
              </template>
              <span v-else class="release-empty">暂无生效版本</span>
            </div>
          </div>
          <div v-if="selected.length" class="selected-actions">
            <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
            <el-button type="danger" plain @click="removeSelected">批量删除</el-button>
            <el-button link @click="clearSelection">取消选择</el-button>
          </div>
        </div>
        <el-button type="primary" :loading="building" @click="createBuild">创建构建</el-button>
      </div>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有构建。"
      next="点击“创建构建”，把当前策略编译为各目标的完整配置。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="构建" width="90">
            <template #default="{ row }"><span class="mono">#{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column label="发布状态" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="buildStatusTagType(row.status)"
                      :effect="buildStatusTagEffect(row.status)">
                {{ BUILD_STATUS_LABELS[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="校验" width="110">
            <template #default="{ row }">
              <StatusDot :kind="verifyKind(row)" :text="verifyText(row)" />
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="135">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="created_by" label="创建人" width="100" />
          <el-table-column label="策略摘要" min-width="110">
            <template #default="{ row }"><span class="mono">{{ shortSha(row.policy_sha) }}</span></template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="120">
            <template #default="{ row }">{{ row.note || '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="300" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="openDetail(row)">详情</el-button>
                <template v-if="row.status === 'BUILT'">
                  <el-button size="small" type="primary" plain :disabled="!verified(row)"
                             @click="publishToTest(row)">发布至测试</el-button>
                  <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
                </template>
                <template v-else-if="row.status === 'TESTING'">
                  <el-button size="small" type="primary" plain :disabled="!verified(row)"
                             @click="publishToProd(row)">发布至生产</el-button>
                  <el-button size="small" type="warning" plain @click="offlineBuild(row)">下线</el-button>
                </template>
                <template v-else-if="row.status === 'OFFLINE'">
                  <el-button size="small" type="primary" plain :disabled="!verified(row)"
                             @click="publishToTest(row)">重新测试</el-button>
                  <el-button size="small" type="warning" plain :disabled="!verified(row)"
                             @click="rollbackToProd(row)">回滚至生产</el-button>
                </template>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <div class="mp-card">
      <h3>发布历史（最近 10 条）</h3>
      <EmptyState v-if="!releases.length" reason="还没有发布记录。" />
      <div v-else class="mp-table-wrap">
        <el-table :data="releases" size="small">
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="动作" width="130">
            <template #default="{ row }">{{ releaseActionText(row) }}</template>
          </el-table-column>
          <el-table-column label="构建" width="90">
            <template #default="{ row }"><span class="mono">#{{ row.build_id }}</span></template>
          </el-table-column>
          <el-table-column prop="operator" label="操作人" width="110" />
          <el-table-column prop="reason" label="说明" min-width="160">
            <template #default="{ row }">{{ row.reason || '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-drawer v-model="detailVisible" :title="`构建 #${detail?.id}`" size="min(720px, 94vw)">
      <template v-if="detail">
        <p style="font-size:13px;color:var(--mp-text-secondary);margin-top:0">
          {{ fmtTime(detail.created_at) }} · {{ detail.created_by }} ·
          策略摘要 <span class="mono">{{ shortSha(detail.policy_sha) }}</span>
          {{ detail.note ? ` · ${detail.note}` : '' }}
        </p>
        <el-alert v-if="detail.verify_status !== 'success'" type="error" :closable="false"
                  title="存在未通过的校验，不能发布" style="margin-bottom:12px" />
        <div v-for="(result, name) in detail.results" :key="name" class="mp-card">
          <h3 style="display:flex;align-items:center;gap:10px">
            <span class="mono">{{ name }}</span>
            <StatusDot :kind="result.ok ? 'ok' : 'danger'"
                       :text="result.ok ? result.verification : '未通过'" />
            <span style="flex:1"></span>
            <el-button v-if="result.ok" size="small" @click="previewArtifact(name)">预览产物</el-button>
            <el-button size="small" @click="openDiff(name)">与上一构建对比</el-button>
          </h3>
          <div style="font-size:12.5px;color:var(--mp-text-secondary)">
            {{ result.engine }} / {{ PLATFORM_LABELS[result.platform] || result.platform }} ·
            {{ result.size }} 字节 · 摘要 <span class="mono">{{ shortSha(result.sha256) }}</span>
          </div>
          <template v-if="result.errors?.length">
            <div v-for="(e, i) in result.errors" :key="'e' + i"
                 style="color:var(--mp-danger);font-size:12.5px;margin-top:6px">错误：{{ e }}</div>
          </template>
          <template v-if="result.warnings?.length">
            <div v-for="(w, i) in result.warnings" :key="'w' + i"
                 style="color:var(--mp-warn);font-size:12.5px;margin-top:6px">提示：{{ w }}</div>
          </template>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="artifactVisible" :title="`产物预览 · ${artifactTarget}`"
               width="min(760px, 94vw)">
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin-top:0">
        订阅来源以 <span class="mono">{FEED}</span> 占位，分发时才注入设备专属地址；
        本地单节点的凭据会直接写入产物，请仅在管理端预览。
      </p>
      <el-input :model-value="artifactContent" type="textarea" :rows="20" readonly class="mono" />
    </el-dialog>

    <el-dialog v-model="diffVisible" :title="`差异 · ${diffTarget}`" width="min(760px, 94vw)">
      <el-input :model-value="diffContent || '（无差异或上一构建不存在该目标）'"
                type="textarea" :rows="20" readonly class="mono" />
    </el-dialog>

    <BatchResultDialog
      v-model:visible="blockedVisible"
      title="部分构建未删除"
      :summary="`已删除 ${deletedCount} 项；${blockedItems.length} 项因已发布过而保留`"
      :items="blockedItems"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import BatchResultDialog from '../components/BatchResultDialog.vue'
import {
  fmtTime, shortSha, PLATFORM_LABELS, BUILD_STATUS_LABELS, ENV_LABELS,
  RELEASE_ACTION_LABELS, buildStatusTagType, buildStatusTagEffect,
} from '../format'

const rows = ref([])
const isMobile = useMobile()
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const releaseState = ref({ production: null, testing: null })
const releases = ref([])
const loading = ref(false)
const error = ref('')
const building = ref(false)
const detail = ref(null)
const detailVisible = ref(false)
const artifactVisible = ref(false)
const artifactTarget = ref('')
const artifactContent = ref('')
const diffVisible = ref(false)
const diffTarget = ref('')
const diffContent = ref('')
const tableRef = ref(null)
const selected = ref([])
const blockedVisible = ref(false)
const blockedItems = ref([])
const deletedCount = ref(0)

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [state, paged, rel] = await Promise.all([
      api('/api/v1/release-state'),
      api(`/api/v1/builds/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`),
      api('/api/v1/releases'),
    ])
    rows.value = paged.items
    total.value = paged.total
    releaseState.value = state
    releases.value = rel
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
  tableRef.value?.clearSelection()
  selected.value = []
}

// 发布时间：未发布过的构建退回创建时间
function publishedAt(build) {
  return build?.published_at || build?.created_at || ''
}

function verified(row) {
  return row.verify_status === 'success'
}

function verifyKind(row) {
  if (row.verify_status === 'success') return 'ok'
  if (row.verify_status === 'failed') return 'danger'
  return 'warn'
}

function verifyText(row) {
  if (row.verify_status === 'success') return '校验通过'
  if (row.verify_status === 'failed') return '校验失败'
  return '校验中'
}

// 发布历史动作：发布/回滚带上环境，下线只写动作
function releaseActionText(row) {
  const action = RELEASE_ACTION_LABELS[row.action] || row.action
  if (row.action === 'offline') return action
  return `${action}到${ENV_LABELS[row.env] || row.env}`
}

// 当前环境里生效的构建号，没有则写「无」
function currentBuildText(build) {
  return build ? `构建 #${build.id}` : '无'
}

async function createBuild() {
  building.value = true
  try {
    const build = await api('/api/v1/builds', { method: 'POST', body: { note: '' } })
    await load()
    if (build.verify_status === 'success') {
      ElMessage.success(`构建 #${build.id} 校验通过`)
    } else {
      ElMessage.warning(`构建 #${build.id} 存在未通过的校验，请查看详情`)
    }
    openDetail(build)
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    building.value = false
  }
}

function openDetail(build) {
  detail.value = build.results ? build : null
  detailVisible.value = true
  if (!build.results) {
    api(`/api/v1/builds/${build.id}`).then((d) => { detail.value = d }).catch((e) => ElMessage.error(e.message))
  }
}

async function previewArtifact(name) {
  try {
    const data = await api(`/api/v1/builds/${detail.value.id}/artifact/${name}`)
    artifactTarget.value = name
    artifactContent.value = data.content
    artifactVisible.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function openDiff(name) {
  const idx = rows.value.findIndex((r) => r.id === detail.value.id)
  const prev = rows.value[idx + 1]
  if (!prev) return ElMessage.info('没有更早的构建可以对比')
  try {
    const data = await api(`/api/v1/builds/${detail.value.id}/diff/${prev.id}`)
    diffTarget.value = `${name}（#${prev.id} → #${detail.value.id}）`
    diffContent.value = data.targets[name] || ''
    diffVisible.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function publishToTest(row) {
  if (!await confirmBox(
    `确定将构建 #${row.id} 发布至测试环境吗？发布后，当前测试版本（${currentBuildText(releaseState.value.testing)}）将被转为已下线。`,
    '发布至测试环境', { type: 'warning', confirmButtonText: '发布' },
  )) return
  try {
    await api(`/api/v1/builds/${row.id}/publish-to-test`, { method: 'POST', body: { reason: '' } })
    ElMessage.success(`构建 #${row.id} 已发布至测试环境`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function publishToProd(row) {
  if (!await confirmBox(
    `⚠️ 确定将构建 #${row.id} 设为生产版本吗？这将会影响所有线上设备。当前的线上版本（${currentBuildText(releaseState.value.production)}）将被转为已下线。`,
    '发布至生产环境', { type: 'warning', confirmButtonText: '发布' },
  )) return
  try {
    await api(`/api/v1/builds/${row.id}/publish-to-prod`, { method: 'POST', body: { reason: '' } })
    ElMessage.success(`构建 #${row.id} 已成为生产版本`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function rollbackToProd(row) {
  if (!await confirmBox(
    `确定将构建 #${row.id} 回滚为生产版本吗？这将会影响所有线上设备。当前的线上版本（${currentBuildText(releaseState.value.production)}）将被转为已下线。`,
    '回滚生产版本', { type: 'warning', confirmButtonText: '回滚' },
  )) return
  try {
    await api(`/api/v1/builds/${row.id}/rollback-to-prod`, { method: 'POST', body: { reason: '' } })
    ElMessage.success(`已回滚到构建 #${row.id}`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function offlineBuild(row) {
  if (!await confirmBox(
    `确定将构建 #${row.id} 下线吗？下线后测试环境将没有生效版本，客户端会在下次拉取时收到 503。`,
    '下线构建', { type: 'warning', confirmButtonText: '下线' },
  )) return
  try {
    await api(`/api/v1/builds/${row.id}/offline`, { method: 'POST', body: { reason: '' } })
    ElMessage.success(`构建 #${row.id} 已下线`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除构建 #${row.id}？产物文件与相关发布历史会一并删除；`
    + '只有「已构建」状态的构建可以删除，已发布过的版本只能下线归档。',
    `删除构建 #${row.id}`, { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    await api(`/api/v1/builds/${row.id}`, { method: 'DELETE' })
    ElMessage.success(`构建 #${row.id} 已删除`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeSelected() {
  if (!selected.value.length) return
  if (!await confirmBox(
    `删除选中的 ${selected.value.length} 个构建？产物文件与相关发布历史会一并删除；`
    + '已发布过的版本会保留，并列出原因。',
    '批量删除构建', { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    const ids = selected.value.map((r) => r.id)
    const resp = await api('/api/v1/builds/batch/delete', {
      method: 'POST', body: { ids },
    })
    deletedCount.value = resp.deleted.length
    blockedItems.value = resp.blocked
    if (resp.blocked.length) {
      blockedVisible.value = true
    } else {
      ElMessage.success(`已删除 ${resp.deleted.length} 个构建`)
    }
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.op-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.op-grid .el-button {
  margin: 0;
  padding-left: 4px;
  padding-right: 4px;
}
.op-grid .el-button + .el-button { margin-left: 0; }
@media (max-width: 640px) {
  .op-grid { gap: 4px; }
  .op-grid .el-button { font-size: 12px; }
}
.release-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.release-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.release-label { font-weight: 600; min-width: 96px; }
.release-time { color: var(--mp-text-secondary); }
.release-meta { color: var(--mp-text-secondary); }
.release-empty { color: var(--mp-text-secondary); }
.release-reason {
  color: var(--mp-text-secondary);
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selected-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
@media (max-width: 640px) {
  .release-reason { max-width: 220px; }
}
</style>
