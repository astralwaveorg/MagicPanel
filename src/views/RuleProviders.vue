<template>
  <div>
    <h2 class="mp-page-title">规则来源</h2>
    <p class="mp-page-desc">
      规则集由服务端抓取并留存快照，经构建引用后通过订阅地址分发给设备；远程与内联两种来源独立更新。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加规则来源</el-button>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有规则来源。"
      next="点击“添加规则来源”：远程来源填 URL，内联来源直接粘贴规则内容。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
          <el-table-column prop="name" label="名称" min-width="110" fixed />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ row.kind === 'remote' ? '远程' : '内联' }}</template>
          </el-table-column>
          <el-table-column prop="behavior" label="行为" width="90" />
          <el-table-column prop="format" label="格式" width="80" />
          <el-table-column label="URL" min-width="200">
            <template #default="{ row }">
              <span class="mono">{{ row.url || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="100">
            <template #default="{ row }"><StatusDot v-bind="sourceStatus(row)" /></template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="规则数" width="80" align="right">
            <template #default="{ row }">{{ row.rule_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="摘要" min-width="110">
            <template #default="{ row }"><span class="mono">{{ shortSha(row.sha256) }}</span></template>
          </el-table-column>
          <el-table-column label="抓取间隔(秒)" width="100" align="right" prop="interval" />
          <el-table-column label="最近成功" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.last_fetched_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="!row.has_content" @click="preview(row)">内容</el-button>
              <el-button size="small" v-if="row.kind === 'remote'" :loading="row._refreshing"
                         @click="refresh(row)">抓取</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑规则来源' : '添加规则来源'"
               width="min(620px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称（字母、数字、_ -）">
              <el-input v-model="form.name" class="mono" placeholder="例如：ai" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="行为">
              <el-select v-model="form.behavior" style="width:100%">
                <el-option value="domain" label="domain（域名）" />
                <el-option value="ipcidr" label="ipcidr（IP 段）" />
                <el-option value="classical" label="classical（经典规则）" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="来源类型">
          <el-radio-group v-model="form.kind">
            <el-radio value="remote">远程 URL</el-radio>
            <el-radio value="inline">内联内容</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.kind === 'remote'" label="URL">
          <el-input v-model="form.url" class="mono" placeholder="https://…/ruleset.yaml" />
        </el-form-item>
        <el-form-item v-else label="规则内容（yaml payload 或每行一条）">
          <el-input v-model="form.inline_content" type="textarea" :rows="8" class="mono"
                    placeholder="payload:&#10;  - example.com" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="格式">
              <el-select v-model="form.format" style="width:100%">
                <el-option value="yaml" label="yaml" />
                <el-option value="text" label="text" />
                <el-option value="mrs" label="mrs" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="抓取间隔（秒）">
              <el-input-number v-model="form.interval" :min="600" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialog" :title="`内容快照 · ${previewName}`"
               width="min(720px, 94vw)">
      <el-input :model-value="previewContent" type="textarea" :rows="18" readonly class="mono" />
    </el-dialog>
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
const previewDialog = ref(false)
const previewContent = ref('')
const previewName = ref('')

const emptyForm = () => ({
  name: '', behavior: 'domain', format: 'yaml', kind: 'remote',
  url: '', inline_content: '', interval: 86400, enabled: true,
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    rows.value = await api('/api/v1/rule-providers')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, behavior: row.behavior, format: row.format, kind: row.kind,
    url: row.url, inline_content: '', interval: row.interval, enabled: row.enabled,
  } : {})
  dialog.value = true
  if (row && row.kind === 'inline') {
    try {
      const data = await api(`/api/v1/rule-providers/${row.id}/content`)
      form.inline_content = data.content
    } catch (e) {
      ElMessage.error(e.message)
    }
  }
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    const body = { ...form }
    if (editing.value) {
      if (body.kind === 'inline' && !body.inline_content) {
        const current = await api(`/api/v1/rule-providers/${editing.value.id}/content`)
        body.inline_content = current.content
      }
      await api(`/api/v1/rule-providers/${editing.value.id}`, { method: 'PUT', body })
    } else {
      await api('/api/v1/rule-providers', { method: 'POST', body })
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
    const updated = await api(`/api/v1/rule-providers/${row.id}/refresh`, { method: 'POST' })
    Object.assign(row, updated)
    ElMessage.success(`抓取成功：${updated.rule_count} 条规则`)
  } catch (e) {
    ElMessage.error(e.message)
    await load()
  } finally {
    row._refreshing = false
  }
}

async function remove(row) {
  if (!await confirmBox(`删除规则来源 “${row.name}”？`, '删除规则来源')) return
  try {
    await api(`/api/v1/rule-providers/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function preview(row) {
  try {
    const data = await api(`/api/v1/rule-providers/${row.id}/content`)
    previewContent.value = data.content
    previewName.value = row.name
    previewDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>
