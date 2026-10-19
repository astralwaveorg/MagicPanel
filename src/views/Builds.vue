<template>
  <div>
    <h2 class="mp-page-title">构建与发布</h2>
    <p class="mp-page-desc">
      构建把当前策略固化为不可变候选并逐目标校验；发布只移动通道指针，失败构建不能发布。
      回滚后客户端需下一次拉取才生效。
    </p>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:0">
        <div class="left">
          <span v-for="ch in ['stable', 'candidate']" :key="ch" style="margin-right:18px;font-size:13.5px">
            {{ CHANNEL_LABELS[ch] }}通道：
            <template v-if="channels[ch]">
              <span class="mono">构建 #{{ channels[ch].id }}</span>
              （{{ fmtTime(channels[ch].created_at) }}）
            </template>
            <span v-else style="color:var(--mp-text-secondary)">未发布</span>
          </span>
        </div>
        <el-button type="primary" :loading="building" @click="createBuild">创建候选构建</el-button>
      </div>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有候选构建。"
      next="点击「创建候选构建」把当前策略编译为各目标的完整配置。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
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
          <el-table-column label="操作" width="330" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openDetail(row)">详情</el-button>
              <el-button size="small" :disabled="channels.candidate?.id === row.id"
                         @click="promote(row, 'candidate')">发到候选</el-button>
              <el-button size="small" type="primary" plain
                         :disabled="row.status !== 'success' || channels.stable?.id === row.id"
                         @click="promote(row, 'stable')">发布稳定</el-button>
              <el-button size="small" type="warning" plain
                         :disabled="row.status !== 'success'"
                         @click="rollback(row)">回滚至此</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>发布历史</h3>
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
        产物中订阅地址以 <span class="mono">{FEED}</span> 占位，分发时才注入设备专属地址，不含节点凭据。
      </p>
      <el-input :model-value="artifactContent" type="textarea" :rows="20" readonly class="mono" />
    </el-dialog>

    <el-dialog v-model="diffVisible" :title="`差异 · ${diffTarget}`" width="min(760px, 94vw)">
      <el-input :model-value="diffContent || '（无差异或上一构建不存在该目标）'"
                type="textarea" :rows="20" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import { fmtTime, shortSha, PLATFORM_LABELS, CHANNEL_LABELS } from '../format'

const rows = ref([])
const channels = ref({ stable: null, candidate: null })
const releases = ref([])
const loading = ref(false)
const building = ref(false)
const detail = ref(null)
const detailVisible = ref(false)
const artifactVisible = ref(false)
const artifactTarget = ref('')
const artifactContent = ref('')
const diffVisible = ref(false)
const diffTarget = ref('')
const diffContent = ref('')

async function load() {
  loading.value = true
  try {
    const [builds, ch, rel] = await Promise.all([
      api('/api/v1/builds'), api('/api/v1/channels'), api('/api/v1/releases'),
    ])
    rows.value = builds
    channels.value = ch
    releases.value = rel
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

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
</script>
