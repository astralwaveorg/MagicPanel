<template>
  <div>
    <h2 class="mp-page-title">功能模块</h2>
    <p class="mp-page-desc">
      用于补充脚本、复写、面板等 YAML 片段，构建时按引擎合并至目标配置。
      合并规则：字典递归合并、列表追加、标量覆盖；目标扩展最后生效，优先级最高。
    </p>

    <div class="mp-toolbar">
      <div class="left">
        <el-radio-group v-model="categoryFilter" size="small">
          <el-radio-button value="">全部分类</el-radio-button>
          <el-radio-button v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key">
            {{ label }}
          </el-radio-button>
        </el-radio-group>
      </div>
      <el-button type="primary" @click="openEdit()">添加模块</el-button>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="暂未添加任何功能模块。"
      next="点击“添加模块”即可配置，例如为 Stash 增加面板，或为 Mihomo 追加 DNS 配置。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table :data="filtered" v-loading="loading">
          <el-table-column prop="name" label="名称" min-width="130" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="分类" width="90">
            <template #default="{ row }">{{ CATEGORY_LABELS[row.category] || row.category }}</template>
          </el-table-column>
          <el-table-column label="适用引擎" width="100">
            <template #default="{ row }">{{ ENGINE_LABELS[row.engine] || row.engine }}</template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <span class="mp-status">
                <i class="mp-dot" :class="row.enabled ? 'ok' : 'muted'" />
                {{ row.enabled ? '启用' : '停用' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="sort" label="顺序" width="70" align="right" />
          <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
          <el-table-column label="更新时间" min-width="130">
            <template #default="{ row }">{{ fmtTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="210" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <el-button size="small" @click="preview(row)">内容</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑模块' : '添加模块'"
               width="min(640px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="名称">
              <el-input v-model="form.name" placeholder="例如：首页面板" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="分类">
              <el-select v-model="form.category" style="width:100%">
                <el-option v-for="(label, key) in CATEGORY_LABELS" :key="key"
                           :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="适用引擎">
              <el-select v-model="form.engine" style="width:100%">
                <el-option v-for="(label, key) in ENGINE_LABELS" :key="key"
                           :value="key" :label="label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="合并顺序（小的先合并）">
              <el-input-number v-model="form.sort" :min="0" :max="999" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="内容（YAML 键值片段）">
          <el-input v-model="form.content" type="textarea" :rows="10" class="mono"
                    placeholder="panel:&#10;  首页:&#10;    title: 家庭网络" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" placeholder="用途说明，会展示在门户页" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用（停用后不参与构建）</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialog" :title="`内容 · ${previewName}`"
               width="min(680px, 94vw)">
      <el-input :model-value="previewContent" type="textarea" :rows="14" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import { fmtTime } from '../format'

const CATEGORY_LABELS = {
  script: '脚本', rewrite: '复写', panel: '面板', dns: 'DNS', general: '通用',
}
const ENGINE_LABELS = { stash: '仅 Stash', mihomo: '仅 Mihomo', all: '全部引擎' }

const rows = ref([])
const isMobile = useMobile()
const total = ref(0)
const page = ref(1)
const limit = ref(50)
const loading = ref(false)
const error = ref('')
const dialog = ref(false)
const saving = ref(false)
const editing = ref(null)
const categoryFilter = ref('')
const previewDialog = ref(false)
const previewContent = ref('')
const previewName = ref('')

const emptyForm = () => ({
  name: '', category: 'general', engine: 'all', content: '',
  enabled: true, sort: 0, note: '',
})
const form = reactive(emptyForm())

const filtered = computed(() =>
  categoryFilter.value
    ? rows.value.filter((r) => r.category === categoryFilter.value)
    : rows.value)

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const paged = await api(`/api/v1/snippets/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`)
    rows.value = paged.items
    total.value = paged.total
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openEdit(row) {
  editing.value = row || null
  Object.assign(form, emptyForm(), row ? {
    name: row.name, category: row.category, engine: row.engine,
    content: row.content, enabled: !!row.enabled, sort: row.sort, note: row.note,
  } : {})
  dialog.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写名称')
  if (!form.content.trim()) return ElMessage.warning('请填写内容')
  saving.value = true
  try {
    if (editing.value) {
      await api(`/api/v1/snippets/${editing.value.id}`, { method: 'PUT', body: { ...form } })
    } else {
      await api('/api/v1/snippets', { method: 'POST', body: { ...form } })
    }
    dialog.value = false
    ElMessage.success('已保存，下次构建时生效')
    await load()
  } catch (e) {
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除模块 “${row.name}”？下次构建不再包含该片段。`, '删除功能模块')) return
  try {
    await api(`/api/v1/snippets/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function preview(row) {
  previewContent.value = row.content
  previewName.value = row.name
  previewDialog.value = true
}
</script>
