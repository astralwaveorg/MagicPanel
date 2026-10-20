<template>
  <div>
    <h2 class="mp-page-title">构建发布</h2>
    <p class="mp-page-desc">
      构建把当前策略固化为不可变候选并逐目标校验；发布只移动通道指针，失败构建不能发布。
      回滚后客户端需下一次拉取才生效。
    </p>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:0">
        <div class="left" style="flex-direction:column;align-items:flex-start;gap:8px">
          <div class="channel-list">
            <div v-for="ch in ['stable', 'candidate']" :key="ch" class="channel-line">
              <span class="channel-label">{{ CHANNEL_LABELS[ch] }}通道</span>
              <template v-if="channels[ch]">
                <span class="mono">构建 #{{ channels[ch].id }}</span>
                <span class="mono" style="color:var(--mp-text-secondary)">
                  策略 {{ shortSha(channels[ch].policy_sha) }}
                </span>
                <template v-if="channels[ch].publish?.at">
                  <el-tag size="small" effect="plain"
                          :type="channels[ch].publish.operator === '系统' ? 'success' : 'info'">
                    {{ channels[ch].publish.operator === '系统' ? '自动' : '手动' }}
                  </el-tag>
                  <span>
                    {{ channels[ch].publish.action === 'rollback' ? '回滚' : '发布' }}于
                    {{ fmtTime(channels[ch].publish.at) }}
                  </span>
                  <span class="mono">{{ channels[ch].publish.operator || '—' }}</span>
                  <span v-if="channels[ch].publish.reason" class="channel-reason">
                    · {{ channels[ch].publish.reason }}
                  </span>
                </template>
                <span v-else style="color:var(--mp-text-secondary)">
                  构建于 {{ fmtTime(channels[ch].created_at) }}
                </span>
              </template>
              <span v-else style="color:var(--mp-text-secondary)">未发布</span>
            </div>
          </div>
          <div v-if="selected.length" class="selected-actions">
            <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
            <el-button type="danger" plain @click="removeSelected">批量删除</el-button>
            <el-button link @click="clearSelection">取消选择</el-button>
          </div>
        </div>
        <el-button type="primary" :loading="building" @click="createBuild">创建候选构建</el-button>
      </div>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有候选构建。"
      next="点击“创建候选构建”，把当前策略编译为各目标的完整配置。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" fixed />
          <el-table-column label="构建" width="90">
            <template #default="{ row }"><span class="mono">#{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <StatusDot :kind="row.status === 'success' ? 'ok' : 'danger'"
                         :text="row.status === 'success' ? '校验通过' : '校验失败'" />
            </template>
          </el-table-column>
          <el-table-column label="当前通道" min-width="110">
            <template #default="{ row }">
              <template v-for="ch in ['stable', 'candidate']" :key="ch">
                <el-tag v-if="channels[ch]?.id === row.id" size="small" style="margin-right:6px"
                        :type="ch === 'stable' ? 'success' : 'warning'" effect="plain">
                  {{ CHANNEL_LABELS[ch] }}
                </el-tag>
              </template>
              <span v-if="channels.stable?.id !== row.id && channels.candidate?.id !== row.id">—</span>
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
          <el-table-column label="操作" width="360" fixed="right">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="openDetail(row)">详情</el-button>
                <el-button size="small" :disabled="channels.candidate?.id === row.id"
                           @click="promote(row, 'candidate')">发到候选</el-button>
                <el-button size="small" type="primary" plain
                           :disabled="row.status !== 'success' || channels.stable?.id === row.id"
                           @click="promote(row, 'stable')">发布稳定</el-button>
                <el-button size="small" type="warning" plain
                           :disabled="row.status !== 'success'"
                           @click="rollback(row)">回滚至此</el-button>
                <el-button size="small" type="danger" plain
                           @click="remove(row)">删除</el-button>
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
          <el-table-column label="动作" width="110">
            <template #default="{ row }">
              {{ row.action === 'promote' ? '发布' : '回滚' }}到{{ CHANNEL_LABELS[row.channel] }}
            </template>
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

    <el-drawer v-model="detailVisible" :title="`候选构建 #${detail?.id}`" size="min(720px, 94vw)">
      <template v-if="detail">
        <p style="font-size:13px;color:var(--mp-text-secondary);margin-top:0">
          {{ fmtTime(detail.created_at) }} · {{ detail.created_by }} ·
          策略摘要 <span class="mono">{{ shortSha(detail.policy_sha) }}</span>
          {{ detail.note ? ` · ${detail.note}` : '' }}
        </p>
        <el-alert v-if="detail.status !== 'success'" type="error" :closable="false"
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
      :summary="`已删除 ${deletedCount} 项；${blockedItems.length} 项因仍在通道中而保留`"
      :items="blockedItems"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import BatchResultDialog from '../components/BatchResultDialog.vue'
import { fmtTime, shortSha, PLATFORM_LABELS, CHANNEL_LABELS } from '../format'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const channels = ref({ stable: null, candidate: null })
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
    const [builds, ch, rel] = await Promise.all([
      api('/api/v1/builds'), api('/api/v1/channels'), api('/api/v1/releases'),
    ])
    const paged = await api(`/api/v1/builds/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`)
    rows.value = paged.items
    total.value = paged.total
    channels.value = ch
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

async function createBuild() {
  building.value = true
  try {
    const build = await api('/api/v1/builds', { method: 'POST', body: { note: '' } })
    await load()
    if (build.status === 'success') {
      ElMessage.success(`候选构建 #${build.id} 校验通过`)
    } else {
      ElMessage.warning(`候选构建 #${build.id} 存在未通过的校验，请查看详情`)
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

async function promote(row, channel) {
  const label = channel === 'stable' ? '稳定' : '候选'
  let value
  try {
    ;({ value } = await ElMessageBox.prompt(
      `将候选构建 #${row.id} 发布到${label}通道？该通道下设备将在下次拉取时获得新配置。`,
      `发布到${label}通道`,
      { confirmButtonText: '发布', inputPlaceholder: '说明（可选）', type: 'warning' },
    ))
  } catch { return }
  try {
    await api(`/api/v1/builds/${row.id}/promote`, {
      method: 'POST', body: { channel, reason: value || '' },
    })
    ElMessage.success(`已发布到${label}通道`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function rollback(row) {
  let value
  try {
    ;({ value } = await ElMessageBox.prompt(
      `把稳定通道回滚到构建 #${row.id}？客户端在下次拉取时生效，已建立的连接不受影响。`,
      '回滚稳定通道',
      { confirmButtonText: '回滚', inputPlaceholder: '回滚原因', type: 'warning' },
    ))
  } catch { return }
  try {
    await api('/api/v1/channels/stable/rollback', {
      method: 'POST', body: { build_id: row.id, reason: value || '' },
    })
    ElMessage.success('已回滚')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除候选构建 #${row.id}？产物文件与相关发布历史会一并删除；`
    + '仍在稳定或候选通道中的构建不能删除，需先把通道移到其他构建。',
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
    + '仍在稳定或候选通道中的构建会保留，并列出原因。',
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
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}
.op-grid .el-button {
  width: 100%;
  margin: 0;
  padding-left: 4px;
  padding-right: 4px;
}
@media (max-width: 640px) {
  .op-grid { gap: 4px; }
  .op-grid .el-button { font-size: 12px; }
}
.channel-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.channel-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.channel-label { font-weight: 600; min-width: 64px; }
.channel-reason {
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
  .channel-reason { max-width: 220px; }
}
</style>
