<template>
  <div>
    <h2 class="mp-page-title">发布目标</h2>
    <p class="mp-page-desc">
      一个目标对应一类客户端（引擎 + 平台）。同一策略按目标编译为对应方言；目标扩展用于平台差异，整键覆盖。
    </p>

    <div class="mp-toolbar">
      <div class="left"></div>
      <el-button type="primary" @click="openEdit()">添加发布目标</el-button>
    </div>

    <EmptyState
      v-if="!rows.length"
      reason="还没有发布目标。"
      next="点击「添加发布目标」，例如 stash / ios 与 mihomo / android 各建一个。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="rows" v-loading="loading">
          <el-table-column prop="name" label="名称" min-width="130">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column prop="engine" label="引擎" width="90" />
          <el-table-column label="平台" width="90">
            <template #default="{ row }">{{ PLATFORM_LABELS[row.platform] || row.platform }}</template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="160">
            <template #default="{ row }">{{ row.description || '—' }}</template>
          </el-table-column>
          <el-table-column label="目标扩展" min-width="120">
            <template #default="{ row }">{{ row.extra_yaml ? '有（整键覆盖）' : '—' }}</template>
          </el-table-column>
          <el-table-column label="更新提示(小时)" width="120" align="right" prop="update_interval" />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑发布目标' : '添加发布目标'"
               width="min(620px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称（字母、数字、_ -）">
              <el-input v-model="form.name" class="mono" placeholder="例如：stash-ios" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="引擎">
              <el-select v-model="form.engine" style="width:100%">
                <el-option value="stash" label="Stash" />
                <el-option value="mihomo" label="Mihomo" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="平台">
              <el-select v-model="form.platform" style="width:100%">
                <el-option v-for="(label, key) in PLATFORM_LABELS" :key="key" :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="form.description" placeholder="例如：iPhone 主力配置" />
        </el-form-item>
        <el-form-item label="目标扩展（YAML 映射，顶层键整键覆盖生成结果；Stash 的 mitm/rewrite 等平台差异在此维护）">
          <el-input v-model="form.extra_yaml" type="textarea" :rows="8" class="mono"
                    placeholder="# 示例（Stash）：&#10;# mitm:&#10;#   hostnames:&#10;#     - www.google.cn" />
        </el-form-item>
        <el-form-item label="更新提示（小时，写入 profile-update-interval 响应头）">
          <el-input-number v-model="form.update_interval" :min="1" :max="168" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import { PLATFORM_LABELS } from '../format'

const rows = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)

const emptyForm = () => ({
  name: '', engine: 'stash', platform: 'ios', description: '', extra_yaml: '', update_interval: 12,
})
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    rows.value = await api('/api/v1/targets')
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
    name: row.name, engine: row.engine, platform: row.platform,
    description: row.description, extra_yaml: row.extra_yaml,
    update_interval: row.update_interval,
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/targets/${editing.value.id}`, { method: 'PUT', body: form })
    } else {
      await api('/api/v1/targets', { method: 'POST', body: form })
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

async function remove(row) {
  if (!await confirmBox(`删除发布目标「${row.name}」？`, '删除发布目标')) return
  try {
    await api(`/api/v1/targets/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>
