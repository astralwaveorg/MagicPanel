<template>
  <div>
    <h2 class="mp-page-title">设备管理</h2>
    <p class="mp-page-desc">
      每台设备一个固定订阅地址；令牌泄露可轮换使其失效，已下发的节点凭据需联系机场重置。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" :disabled="!targets.length" @click="openEdit()">添加设备</el-button>
    </div>

    <EmptyState
      v-if="!targets.length"
      reason="还没有发布目标，无法添加设备。"
      next="先在“发布目标”中添加目标（引擎 + 平台）。"
    />
    <EmptyState
      v-else-if="!rows.length"
      reason="还没有设备。"
      next="点击“添加设备”；订阅地址只显示一次，请立即保存。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
          <el-table-column label="文件名" min-width="130" fixed>
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="设备名" min-width="130">
            <template #default="{ row }">{{ row.display_name }}</template>
          </el-table-column>
          <el-table-column label="平台" width="90">
            <template #default="{ row }">{{ PLATFORM_LABELS[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column label="发布目标" min-width="130">
            <template #default="{ row }">
              <span class="mono">{{ targetName(row.target_id) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="通道" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.channel === 'stable' ? 'success' : 'warning'" effect="plain">
                {{ CHANNEL_LABELS[row.channel] || row.channel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="令牌指纹" min-width="110">
            <template #default="{ row }"><span class="mono">{{ row.token_hint }}…</span></template>
          </el-table-column>
          <el-table-column label="最近下载" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_pull_at) }}</template>
          </el-table-column>
          <el-table-column prop="pull_count" label="下载次数" width="90" align="right" />
          <el-table-column label="最近来源 IP" min-width="120">
            <template #default="{ row }"><span class="mono">{{ row.last_pull_ip || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="290" fixed="right">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="reveal(row)">复制地址</el-button>
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="warning" plain @click="rotate(row)">轮换令牌</el-button>
                <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑设备' : '添加设备'" width="min(560px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item label="文件名">
          <el-input v-model="form.name" placeholder="例如：Stash-Macmini" />
          <div class="mp-form-hint">下载得到的文件名为“输入值.yaml”，同时用于区分设备，需唯一。</div>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="平台">
              <el-select v-model="form.platform" style="width:100%">
                <el-option v-for="(label, key) in PLATFORM_LABELS" :key="key" :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="发布目标">
              <el-select v-model="form.target_id" style="width:100%">
                <el-option v-for="t in targets" :key="t.id" :value="t.id"
                           :label="`${t.name}（${t.engine} / ${PLATFORM_LABELS[t.platform]}）`" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="更新通道">
          <el-radio-group v-model="form.channel">
            <el-radio value="stable">稳定（跟随正式发布）</el-radio>
            <el-radio value="candidate">候选（提前试用新构建）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="设备名">
          <el-input v-model="form.note" placeholder="例如：客厅 Mac mini" />
          <div class="mp-form-hint">用于后台与门户展示；留空时显示文件名。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <SecretDialog v-model:visible="secretVisible" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import SecretDialog from '../components/SecretDialog.vue'
import { fmtTime, PLATFORM_LABELS, CHANNEL_LABELS } from '../format'

const rows = ref([])
const targets = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const secretVisible = ref(false)

const emptyForm = () => ({ name: '', platform: 'ios', target_id: null, channel: 'stable', note: '' })
const form = reactive(emptyForm())

function targetName(id) {
  return targets.value.find((t) => t.id === id)?.name || `#${id}`
}

async function load() {
  loading.value = true
  try {
    const [devices, ts] = await Promise.all([
      api('/api/v1/devices'), api('/api/v1/targets'),
    ])
    rows.value = devices
    targets.value = ts
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, platform: row.platform, target_id: row.target_id,
    channel: row.channel, note: row.note,
  } : { target_id: targets.value[0]?.id ?? null })
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写文件名')
  if (!form.target_id) return ElMessage.warning('请选择发布目标')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/devices/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      await api('/api/v1/devices', { method: 'POST', body: form })
      secretVisible.value = true
    }
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function reveal(row) {
  try {
    const resp = await api(`/api/v1/devices/${row.id}/reveal`, { method: 'POST' })
    try {
      await navigator.clipboard.writeText(resp.subscription_url)
      ElMessage.success('订阅地址已复制')
    } catch {
      ElMessage.warning('复制失败，请到首页（门户）查看')
    }
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function rotate(row) {
  if (!await confirmBox(
    `轮换 “${row.display_name || row.name}” 的令牌？旧订阅地址立即失效，设备需改用新地址。`,
    '轮换令牌', { type: 'warning', confirmButtonText: '轮换' },
  )) return
  try {
    const resp = await api(`/api/v1/devices/${row.id}/rotate-token`, { method: 'POST' })
    secretVisible.value = true
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除设备 “${row.display_name || row.name}”？其订阅地址同时失效，下载文件名 “${row.name}” 也不再可用。`,
    '删除设备', { type: 'warning' },
  )) return
  try {
    await api(`/api/v1/devices/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
/* 操作列 2×2 排列，覆盖 Element Plus 相邻按钮默认间距 */
.op-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.op-grid .el-button { margin: 0; }
</style>
