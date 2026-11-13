<template>
  <div class="mp-toolbar variant-bar">
    <div class="left">
      <span class="vb-label">分流方案</span>
      <el-select :model-value="modelValue" class="vb-select" @change="onSelect">
        <el-option v-for="v in variants" :key="v.id" :value="v.id"
                   :label="variantLabel(v)">
          <span>{{ v.name }}</span>
          <span v-if="!v.enabled" class="vb-disabled-tag">已停用</span>
          <span v-if="v.is_system" class="vb-system-tag">系统</span>
        </el-option>
      </el-select>
      <span v-if="current?.note" class="vb-note">{{ current.note }}</span>
    </div>
    <el-button @click="manageDialog = true">方案管理</el-button>

    <el-dialog v-model="manageDialog" title="分流方案管理" width="min(680px, 94vw)"
               @open="loadVariants">
      <p class="mp-dialog-desc">
        每个方案是一套完整、独立的策略组与分流规则；构建时每个方案各出一套产物，
        门户下载时可按设备选择方案。默认方案是历史行为，不可删除或改名。
      </p>

      <div class="vb-create">
        <div class="vb-create-title">新建方案</div>
        <el-form :model="createForm" label-position="top" class="vb-create-form">
          <el-row :gutter="10">
            <el-col :span="8">
              <el-form-item label="方案名称">
                <el-input v-model="createForm.name" maxlength="32" placeholder="例如：自建美日" />
              </el-form-item>
            </el-col>
            <el-col :span="10">
              <el-form-item label="备注（可选）">
                <el-input v-model="createForm.note" maxlength="256"
                          placeholder="一句话说明这套方案的用途" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="从哪套复制">
                <el-select v-model="createForm.copy_from" style="width:100%">
                  <el-option v-for="v in variants" :key="v.id" :value="v.id"
                             :label="v.name + (v.id === 0 ? '（推荐起点）' : '')" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-checkbox v-model="createForm.use_sources_empty">
            复制后清空所有组的「节点来源」引用（做「只用本地节点」类方案时勾上）
          </el-checkbox>
          <div class="vb-create-actions">
            <el-button :loading="creating" @click="create" type="primary">创建方案</el-button>
          </div>
        </el-form>
      </div>

      <el-table :data="variants" size="small" v-loading="loadingVariants">
        <el-table-column label="方案" min-width="130">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.is_system" size="small" type="info" class="vb-tag">系统</el-tag>
            <el-tag v-if="!row.enabled" size="small" type="warning" class="vb-tag">已停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="内容" width="120">
          <template #default="{ row }">{{ row.groups_count }} 组 · {{ row.rules_count }} 规则</template>
        </el-table-column>
        <el-table-column label="操作" width="230">
          <template #default="{ row, $index }">
            <div class="op-grid">
              <el-button size="small" @click="move(row, -1)" :disabled="$index === 0">上移</el-button>
              <el-button size="small" @click="move(row, 1)"
                         :disabled="$index === variants.length - 1">下移</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" :disabled="row.is_system" @click="remove(row)" type="danger" plain>删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="editDialog" title="编辑方案" width="min(480px, 94vw)" append-to-body>
      <el-form label-position="top">
        <el-form-item label="方案名称">
          <el-input v-model="editForm.name" maxlength="32"
                    :disabled="editForm.is_system" />
          <div v-if="editForm.is_system" class="mp-form-hint">默认方案不能改名</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" maxlength="256" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="editForm.enabled" :disabled="editForm.is_system">
            启用（停用后不进新构建，已下发的产物照常可用）
          </el-checkbox>
        </el-form-item>
        <div v-if="!editForm.is_system" class="mp-form-hint">
          改名与删除都要求当前生产版本里没有这个方案的产物——有就先发布一版新构建再操作。
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button :loading="saving" @click="saveEdit" type="primary">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

// 分流方案切换与管理：策略组 / 分流策略两页共用。
// 页面通过 v-model 拿当前方案 id（0 = 默认方案），管理操作完成后发 changed
// 让页面重载列表（删除方案时选中项自动落回默认方案）。
const props = defineProps({
  modelValue: { type: Number, default: 0 },
  // localStorage 存储键后缀，两个页面的选择互不影响
  page: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const variants = ref([])
const manageDialog = ref(false)
const editDialog = ref(false)
const loadingVariants = ref(false)
const creating = ref(false)
const saving = ref(false)
const createForm = ref({ name: '', note: '', copy_from: 0, use_sources_empty: false })
const editForm = ref({ id: 0, name: '', note: '', enabled: true, is_system: false })

const current = computed(() =>
  variants.value.find((v) => v.id === props.modelValue) || null)

function variantLabel(v) {
  return v.id === 0 ? '默认方案' : v.name
}

function storageKey() {
  return `mp-variant-${props.page}`
}

function onSelect(id) {
  emit('update:modelValue', id)
  try { localStorage.setItem(storageKey(), String(id)) } catch { /* 隐私模式忽略 */ }
}

async function loadVariants() {
  loadingVariants.value = true
  try {
    variants.value = await api('/api/v1/variants')
    // 选中的方案被删除后落回默认方案
    if (!variants.value.some((v) => v.id === props.modelValue)) {
      onSelect(0)
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loadingVariants.value = false
  }
}

onMounted(async () => {
  let saved = 0
  try { saved = Number(localStorage.getItem(storageKey()) || 0) || 0 } catch { /* 忽略 */ }
  await loadVariants()
  if (saved && variants.value.some((v) => v.id === saved) && saved !== props.modelValue) {
    onSelect(saved)
  }
})

async function create() {
  if (!createForm.value.name.trim()) {
    return ElMessage.warning('请填写方案名称')
  }
  creating.value = true
  try {
    const body = { ...createForm.value, copy_from: createForm.value.copy_from ?? 0 }
    const v = await api('/api/v1/variants', { method: 'POST', body })
    ElMessage.success(`方案「${v.name}」已创建${body.copy_from ? '（含复制的内容）' : ''}`)
    createForm.value = { name: '', note: '', copy_from: 0, use_sources_empty: false }
    await loadVariants()
    onSelect(v.id)
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    creating.value = false
  }
}

function openEdit(row) {
  editForm.value = {
    id: row.id, name: row.name, note: row.note,
    enabled: !!row.enabled, is_system: !!row.is_system,
  }
  editDialog.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    const body = { note: editForm.value.note }
    if (!editForm.value.is_system) {
      body.name = editForm.value.name
      body.enabled = editForm.value.enabled
    }
    await api(`/api/v1/variants/${editForm.value.id}`, { method: 'PUT', body })
    editDialog.value = false
    ElMessage.success('方案已更新')
    await loadVariants()
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function move(row, delta) {
  const ids = variants.value.map((v) => v.id)
  const i = ids.indexOf(row.id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  try {
    await api('/api/v1/variants/reorder', { method: 'POST', body: ids })
    await loadVariants()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function remove(row) {
  const { confirmBox } = await import('../confirm')
  if (!await confirmBox(
    `删除方案「${row.name}」？该方案的 ${row.groups_count} 个策略组与 ${row.rules_count} 条规则会一并删除。`,
    '删除分流方案', { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    await api(`/api/v1/variants/${row.id}`, { method: 'DELETE' })
    ElMessage.success('方案已删除')
    await loadVariants()
    emit('changed')
  } catch (e) {
    // 生产产物仍在引用时后端返回 409，提示先发布新版本
    ElMessage.error(e.message, { duration: 8000 })
  }
}
</script>

<style scoped>
.variant-bar {
  align-items: center;
}
.vb-label {
  color: var(--mp-muted);
  font-size: 13px;
  flex: none;
}
.vb-select {
  width: 180px;
}
.vb-note {
  color: var(--mp-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vb-system-tag,
.vb-disabled-tag {
  margin-left: 6px;
}
.vb-disabled-tag {
  color: var(--el-color-warning);
  font-size: 12px;
}
.vb-create {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px 12px;
  margin-bottom: 12px;
}
.vb-create-title {
  font-size: 13px;
  color: var(--mp-muted);
  margin-bottom: 4px;
}
.vb-create-actions {
  margin-top: 8px;
  text-align: right;
}
.vb-tag {
  margin-left: 6px;
}
</style>
