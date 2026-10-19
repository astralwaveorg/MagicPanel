<template>
  <div>
    <h2 class="mp-page-title">节点来源</h2>
    <p class="mp-page-desc">
      机场订阅地址加密存储，列表只显示脱敏形式；抓取失败时保留最近一次成功快照。
      测速通过本地 Mihomo 核心逐个拨测节点，结果反映本服务器所在网络的连通性，不代表客户端侧一定可用。
    </p>

    <el-alert
      v-if="core && !core.available"
      type="warning"
      :closable="false"
      style="margin-bottom: 14px"
    >
      <template #title>
        测速核心未安装，无法测试节点可用性。
        <el-button size="small" type="warning" plain :loading="installingCore"
                   style="margin-left: 8px" @click="installCore">
          安装 Mihomo 核心（{{ core.pinned_version }}）
        </el-button>
      </template>
    </el-alert>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加节点来源</el-button>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有节点来源。"
      next="点击右上角「添加节点来源」，填入机场订阅地址后执行抓取。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
          <el-table-column prop="name" label="名称" min-width="100" fixed />
          <el-table-column label="订阅地址（脱敏）" min-width="220">
            <template #default="{ row }"><span class="mono">{{ row.url_masked }}</span></template>
          </el-table-column>
          <el-table-column label="状态" min-width="100">
            <template #default="{ row }"><StatusDot v-bind="sourceStatus(row)" /></template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="节点数" width="80" align="right">
            <template #default="{ row }">{{ row.node_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="摘要" min-width="110">
            <template #default="{ row }"><span class="mono">{{ shortSha(row.sha256) }}</span></template>
          </el-table-column>
          <el-table-column label="最近成功" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_fetched_at) }}</template>
          </el-table-column>
          <el-table-column label="失败次数" width="80" align="right" prop="fail_count" />
          <el-table-column label="抓取间隔(秒)" width="100" align="right" prop="interval" />
          <el-table-column label="最近错误" min-width="160">
            <template #default="{ row }">{{ row.last_error || '—' }}</template>
          </el-table-column>
          <el-table-column label="测速" min-width="150">
            <template #default="{ row }">
              <span v-if="!row.tested_at" style="color:var(--mp-muted)">未测试</span>
              <span v-else>
                <span style="color:var(--mp-ok)">{{ row.tested_ok }} 可用</span>
                <span v-if="row.tested_failed" style="color:var(--mp-danger)"> / {{ row.tested_failed }} 失败</span>
                <div style="font-size:12px;color:var(--mp-text-secondary)">{{ fmtTime(row.tested_at) }}</div>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="过滤不可用" width="100" align="center">
            <template #default="{ row }">{{ row.filter_unavailable ? '开启' : '关闭' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openNodes(row)">节点</el-button>
              <el-button size="small" :loading="row._refreshing" @click="refresh(row)">抓取</el-button>
              <el-button size="small" :loading="row._testing" @click="testNodes(row)">测速</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑节点来源' : '添加节点来源'"
               width="min(560px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：神龙机场" />
        </el-form-item>
        <el-form-item :label="editing ? '订阅地址（留空表示不修改）' : '订阅地址'">
          <el-input v-model="form.url" type="password" show-password
                    placeholder="https://…（保存后不再次显示原文）" autocomplete="off" />
        </el-form-item>
        <el-form-item label="节点过滤正则（可选，用于剔除套餐提示等无效节点）">
          <el-input v-model="form.filter" class="mono" placeholder="(?i)^(?!.*(?:剩余|到期|官网)).+$" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="抓取 UA">
              <el-input v-model="form.ua" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="抓取间隔（秒）">
              <el-input-number v-model="form.interval" :min="600" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用（停用后不进入构建，也不向设备分发）</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.filter_unavailable">
            只分发可用节点（执行「测速」后，拨测失败的节点不再下发给设备；重新抓取后需重新测速）
          </el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.allow_private">
            允许访问内网地址（仅在订阅确实位于家庭内网时开启，存在 SSRF 风险）
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="nodesDrawer" :title="`节点列表 · ${nodesSource?.name || ''}`"
               size="min(520px, 92vw)">
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin-top:0">
        仅显示节点名称、协议与测速结果，凭据不展示。共 {{ nodesSource?.nodes?.length ?? 0 }} 个节点。
        测速口径：从本服务器经节点请求 generate_204，衡量连通性与延迟，不等于带宽或解锁能力。
      </p>
      <el-table :data="nodesSource?.nodes || []" size="small" max-height="70vh">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="type" label="协议" width="100" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusDot v-if="row.status === 'ok'" kind="ok" text="可用" />
            <StatusDot v-else-if="row.status === 'failed'" kind="danger" text="不可用" />
            <StatusDot v-else kind="muted" text="未测试" />
          </template>
        </el-table-column>
        <el-table-column label="延迟" width="90" align="right">
          <template #default="{ row }">
            <span class="mono">{{ row.delay != null ? row.delay + 'ms' : '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import { fmtTime, shortSha, sourceStatus } from '../format'

const rows = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const nodesDrawer = ref(false)
const nodesSource = ref(null)
const core = ref(null)
const installingCore = ref(false)

const emptyForm = () => ({
  name: '', url: '', enabled: true, filter: '', ua: 'Stash',
  interval: 21600, allow_private: false, filter_unavailable: false,
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    const [sources, coreStatus] = await Promise.all([
      api('/api/v1/sources'), api('/api/v1/core/status'),
    ])
    rows.value = sources
    core.value = coreStatus
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function installCore() {
  installingCore.value = true
  try {
    const result = await api('/api/v1/core/install', { method: 'POST' })
    ElMessage.success(`核心已安装：${result.version}`)
    core.value = await api('/api/v1/core/status')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    installingCore.value = false
  }
}

async function testNodes(row) {
  row._testing = true
  try {
    const updated = await api(`/api/v1/sources/${row.id}/test`, { method: 'POST' })
    Object.assign(row, updated)
    ElMessage.success(`测速完成：${updated.tested_ok} 可用 / ${updated.tested_failed} 不可用`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row._testing = false
  }
}

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, url: '', enabled: row.enabled, filter: row.filter,
    ua: row.ua, interval: row.interval, allow_private: row.allow_private,
    filter_unavailable: row.filter_unavailable,
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  if (!editing.value && !form.url) return ElMessage.warning('请填写订阅地址')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/sources/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      await api('/api/v1/sources', { method: 'POST', body: form })
    }
    dialog.value = false
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function refresh(row) {
  row._refreshing = true
  try {
    const updated = await api(`/api/v1/sources/${row.id}/refresh`, { method: 'POST' })
    Object.assign(row, updated)
    ElMessage.success(`抓取成功：${updated.node_count} 个节点`)
  } catch (e) {
    ElMessage.error(e.message)
    await load()
  } finally {
    row._refreshing = false
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除节点来源「${row.name}」？已发布的历史构建不受影响，新的构建将不再包含该来源。`,
    '删除节点来源', { type: 'warning' },
  )) return
  try {
    await api(`/api/v1/sources/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openNodes(row) {
  nodesSource.value = row
  nodesDrawer.value = true
}
</script>
