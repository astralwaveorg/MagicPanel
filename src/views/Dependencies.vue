<template>
  <div class="mp-deps">
    <!-- 状态条 -->
    <div class="mp-card mp-deps-bar">
      <div class="mp-deps-bar-left">
        <div class="mp-deps-repo">
          <span class="mono">{{ status.url || '还没有配置仓库地址' }}</span>
          <span v-if="status.branch" class="mp-deps-branch">{{ status.branch }}</span>
          <span v-if="status.commit" class="mono mp-deps-commit">{{ status.commit }}</span>
        </div>
        <div class="mp-deps-badges">
          <el-tag v-if="!status.configured" size="small" type="warning" effect="plain">未配置</el-tag>
          <el-tag v-else-if="!status.cloned" size="small" type="warning" effect="plain">未克隆</el-tag>
          <el-tag v-else-if="status.conflicts.length" size="small" type="danger" effect="plain">
            ⚠ {{ status.conflicts.length }} 个冲突
          </el-tag>
          <el-tag v-else-if="status.dirty.length" size="small" type="warning" effect="plain">
            有本地改动 ({{ status.dirty.length }})
          </el-tag>
          <el-tag v-else size="small" type="success" effect="plain">干净</el-tag>
          <el-tag v-if="status.ahead" size="small" type="info" effect="plain">领先 {{ status.ahead }}</el-tag>
          <el-tag v-if="status.behind" size="small" type="info" effect="plain">落后 {{ status.behind }}</el-tag>
          <span v-if="status.last_sync_at" class="mp-toolbar-hint">
            上次同步：{{ fmtTime(status.last_sync_at) }}
          </span>
        </div>
        <p v-if="status.last_error" class="mp-deps-error">{{ status.last_error }}</p>
      </div>
      <div class="mp-deps-bar-actions mp-btn-grid">
        <el-button :loading="syncing" @click="syncNow" type="primary">立即同步</el-button>
        <el-button @click="openHistory">提交历史</el-button>
        <el-button @click="settingsOpen = true">仓库设置</el-button>
      </div>
    </div>

    <!-- 未配置时的引导 -->
    <el-alert v-if="!status.configured" type="info" :closable="false" show-icon
              title="还没有配置依赖仓库"
              description="填好仓库地址与鉴权密钥后克隆，仓库里的 rule/*.yaml 会自动成为规则来源，改完推上去客户端立刻生效。" />

    <ErrorState v-if="error" :error="error" @retry="load" />

    <div v-else-if="status.cloned" class="mp-deps-body">
      <!-- 文件树 -->
      <div class="mp-card mp-deps-tree">
        <div class="mp-deps-tree-head">
          <span>文件</span>
          <el-button size="small" text @click="newFile = true">新建</el-button>
        </div>
        <div class="mp-deps-tree-list">
          <div v-for="dir in treeDirs" :key="dir.path" class="mp-deps-dir">
            <button class="mp-deps-dir-head" @click="toggleDir(dir.path)">
              <span>{{ collapsedDirs.includes(dir.path) ? '▸' : '▾' }} {{ dir.path || '（根目录）' }}</span>
              <span class="mp-deps-count">{{ dir.files.length }}</span>
            </button>
            <div v-if="!collapsedDirs.includes(dir.path)" class="mp-deps-dir-files">
              <button
                v-for="f in dir.files"
                :key="f.path"
                class="mp-deps-file"
                :class="{ active: current && current.path === f.path }"
                @click="openFile(f)"
              >
                <span class="mp-deps-mark" :data-status="f.status">{{ statusMark(f.status) }}</span>
                <span class="mp-deps-file-name">{{ f.path.split('/').pop() }}</span>
                <el-tag v-if="f.rule_source" size="small" type="success" effect="plain">来源</el-tag>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 文件详情 -->
      <div class="mp-card mp-deps-detail">
        <template v-if="current">
          <div class="mp-deps-detail-head">
            <strong class="mono">{{ current.path }}</strong>
            <span class="mp-toolbar-hint">{{ current.size }} 字节</span>
            <span v-if="current.binary" class="mp-toolbar-hint">二进制文件，只读</span>
          </div>
          <p v-if="current.desc" class="mp-form-hint">{{ current.desc }}</p>
          <el-input
            v-model="draft"
            type="textarea"
            :rows="16"
            :readonly="current.binary"
            class="mono"
            placeholder="（内容加载中）"
          />
          <div class="mp-deps-detail-actions mp-btn-grid">
            <el-button :disabled="current.binary" @click="saveFile">保存</el-button>
            <el-button :disabled="current.binary" @click="saveAndCommit">保存并提交</el-button>
            <el-button v-if="current.rule_source" type="primary" plain
                       @click="goRuleSources">在规则来源查看</el-button>
            <el-button type="danger" plain @click="removeFile">删除</el-button>
          </div>
        </template>
        <EmptyState v-else reason="左侧选一个文件查看与编辑。" />
      </div>
    </div>

    <!-- 冲突 -->
    <el-dialog v-model="conflictOpen" title="解决冲突" width="min(1100px, 96vw)">
      <div v-for="c in conflicts" :key="c.path" class="mp-deps-conflict">
        <p class="mp-deps-conflict-path mono">{{ c.path }}</p>
        <div class="mp-deps-three">
          <div><strong>共同祖先 base</strong><pre class="mono">{{ c.base }}</pre></div>
          <div><strong>本地 ours</strong><pre class="mono">{{ c.ours }}</pre></div>
          <div><strong>远端 theirs</strong><pre class="mono">{{ c.theirs }}</pre></div>
        </div>
        <el-input v-model="conflictDraft[c.path]" type="textarea" :rows="8" class="mono" />
        <div class="mp-deps-detail-actions mp-btn-grid">
          <el-button @click="resolve(c.path, 'manual')">提交手工合并</el-button>
          <el-button @click="resolve(c.path, 'theirs')" plain>整体用远端</el-button>
          <el-button @click="resolve(c.path, 'ours')" plain>整体保留本地</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 历史 -->
    <el-drawer v-model="historyOpen" title="提交历史" size="min(640px, 94vw)">
      <el-table :data="history" size="small">
        <el-table-column label="提交" width="90">
          <template #default="{ row }"><span class="mono">{{ row.short }}</span></template>
        </el-table-column>
        <el-table-column prop="author" label="作者" width="110" />
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.date) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button size="small" text @click="showDiff(row)">看改动</el-button>
            <el-button size="small" text type="danger" @click="revert(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <el-dialog v-model="diffOpen" title="改动内容" width="min(820px, 94vw)">
      <el-input :model-value="diffText" type="textarea" :rows="22" readonly class="mono" />
    </el-dialog>

    <!-- 设置抽屉 -->
    <el-drawer v-model="settingsOpen" title="仓库设置" size="min(560px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="启用自主维护">
          <el-switch v-model="settings.enabled" />
        </el-form-item>
        <el-form-item label="仓库地址">
          <el-input v-model="settings.url" placeholder="git@github.com:owner/repo.git" />
        </el-form-item>
        <el-form-item label="分支">
          <el-input v-model="settings.branch" placeholder="main" />
        </el-form-item>
        <el-form-item label="鉴权方式">
          <el-select v-model="settings.auth" style="width:100%">
            <el-option value="ssh" label="SSH 部署密钥" />
            <el-option value="https" label="HTTPS Token" />
            <el-option value="none" label="公开仓库（无需鉴权）" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="settings.auth === 'ssh'" label="SSH 私钥（只写，不回显）">
          <el-input v-model="settings.private_key" type="textarea" :rows="4"
                    placeholder="留空表示不修改" />
          <div class="mp-form-hint">
            已配置：{{ settings.has_private_key ? '是' : '否' }}
            <el-button size="small" text type="primary" @click="genKey">生成密钥对</el-button>
          </div>
        </el-form-item>
        <el-form-item v-if="settings.auth === 'https'" label="HTTPS Token（只写，不回显）">
          <el-input v-model="settings.token" placeholder="留空表示不修改" />
          <div class="mp-form-hint">已配置：{{ settings.has_token ? '是' : '否' }}</div>
        </el-form-item>
        <el-form-item label="提交身份">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="settings.commit_name" placeholder="name" style="flex:1" />
            <el-input v-model="settings.commit_email" placeholder="email" style="flex:1" />
          </div>
        </el-form-item>
        <el-form-item label="同步间隔（小时）">
          <el-input-number v-model="settings.sync_hours" :min="1" :max="168" style="width:100%" />
        </el-form-item>
        <el-form-item label="保存并提交后自动推送">
          <el-switch v-model="settings.auto_push" />
        </el-form-item>
        <el-form-item label="仓库新增 rule/*.yaml 时自动建规则来源">
          <el-switch v-model="settings.auto_create_rule_sources" />
        </el-form-item>
        <el-form-item label="排除路径清单（逗号分隔的 glob）">
          <el-input v-model="settings.exclude_paths" placeholder=".git,.github,.env,*.bak,.*" />
          <div class="mp-form-hint">
            排除的路径在页面里完全不显示；点开头路径（<code>.*</code>）默认都排除。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="settingsOpen = false">取消</el-button>
        <el-button :loading="savingSettings" @click="saveSettings" type="primary">保存</el-button>
      </template>
    </el-drawer>

    <!-- 新建文件 -->
    <el-dialog v-model="newFile" title="新建文件" width="min(520px, 94vw)">
      <el-form label-position="top">
        <el-form-item label="仓库内相对路径">
          <el-input v-model="newPath" placeholder="rule/新集合.yaml" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="newContent" type="textarea" :rows="8" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newFile = false">取消</el-button>
        <el-button @click="createFile" type="primary">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 自主维护：依赖文件库的文件管理器。浏览、编辑、保存、提交、推送都在这里，
// 仓库里的 rule/*.yaml 会自动成为规则来源。
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import ErrorState from '../components/ErrorState.vue'
import { fmtTime } from '../format'

const router = useRouter()
const status = ref({})
const files = ref([])
const conflicts = ref([])
const conflictDraft = reactive({})
const history = ref([])
const diffText = ref('')
const current = ref(null)
const draft = ref('')
const error = ref('')
const syncing = ref(false)
const savingSettings = ref(false)
const settingsOpen = ref(false)
const historyOpen = ref(false)
const diffOpen = ref(false)
const conflictOpen = ref(false)
const newFile = ref(false)
const newPath = ref('')
const newContent = ref('')
const collapsedDirs = ref([])

const settings = reactive({
  enabled: false, url: '', branch: 'main', auth: 'ssh',
  private_key: '', token: '',
  has_private_key: false, has_token: false,
  commit_name: 'MagicPanel', commit_email: 'magicpanel@localhost',
  sync_hours: 12, auto_push: true, auto_create_rule_sources: true,
  exclude_paths: '.git,.github,.env,*.bak,.*',
})

const treeDirs = computed(() => {
  const map = new Map()
  for (const f of files.value) {
    const idx = f.path.includes('/') ? f.path.indexOf('/') : -1
    const dir = idx >= 0 ? f.path.slice(0, idx) : ''
    if (!map.has(dir)) map.set(dir, [])
    map.get(dir).push(f)
  }
  return [...map.entries()].map(([path, items]) => ({ path, files: items }))
})

function statusMark(s) {
  return { modified: '●', remote: '▲', conflict: '⚠', clean: '○' }[s] || '○'
}

async function load() {
  error.value = ''
  try {
    const [st, fs] = await Promise.all([
      api('/api/v1/deps/status'),
      api('/api/v1/deps/files').catch(() => ({ files: [] })),
    ])
    status.value = st
    files.value = fs.files || []
    const conf = await api('/api/v1/deps/conflicts').catch(() => ({ conflicts: [] }))
    conflicts.value = conf.conflicts || []
    for (const c of conflicts.value) {
      if (!conflictDraft[c.path]) conflictDraft[c.path] = c.ours || ''
    }
    if (conflicts.value.length) conflictOpen.value = true
  } catch (e) {
    error.value = e.message
  }
}
onMounted(load)

function toggleDir(path) {
  const i = collapsedDirs.value.indexOf(path)
  if (i >= 0) collapsedDirs.value.splice(i, 1)
  else collapsedDirs.value.push(path)
}

async function openFile(f) {
  try {
    const data = await api(`/api/v1/deps/file?path=${encodeURIComponent(f.path)}`)
    current.value = { ...f, ...data }
    draft.value = data.binary ? '' : data.content
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveFile() {
  if (!current.value) return
  try {
    await api('/api/v1/deps/file', {
      method: 'PUT',
      body: { path: current.value.path, content: draft.value },
    })
    ElMessage.success('已保存到工作树（还没提交）')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveAndCommit() {
  if (!current.value) return
  try {
    await api('/api/v1/deps/file', {
      method: 'PUT',
      body: { path: current.value.path, content: draft.value },
    })
    await api('/api/v1/deps/commit', {
      method: 'POST',
      body: { message: `更新 ${current.value.path}`, push: true },
    })
    ElMessage.success('已提交并推送')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeFile() {
  if (!current.value) return
  if (!await confirmBox(
    `删除文件 “${current.value.path}”？下次提交后远端也会删掉。`,
    '删除文件', { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    await api(`/api/v1/deps/file?path=${encodeURIComponent(current.value.path)}`,
      { method: 'DELETE' })
    ElMessage.success('已删除')
    current.value = null
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function createFile() {
  if (!newPath.value.trim()) return ElMessage.warning('请填写路径')
  try {
    await api('/api/v1/deps/file', {
      method: 'POST',
      body: { path: newPath.value.trim(), content: newContent.value },
    })
    ElMessage.success('已创建')
    newFile.value = false
    newPath.value = ''
    newContent.value = ''
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function syncNow() {
  syncing.value = true
  try {
    const r = await api('/api/v1/deps/sync', { method: 'POST' })
    const parts = []
    if (r.created) parts.push(`新建来源 ${r.created}`)
    if (r.updated) parts.push(`更新内容 ${r.updated}`)
    if (r.skipped) parts.push(`跳过 ${r.skipped}（面板里已改成远程或内联）`)
    if (r.errors?.length) parts.push(r.errors.join('；'))
    ElMessage[parts.some((p) => p.includes('失败')) ? 'warning' : 'success'](
      parts.length ? parts.join('，') : '没有变化'
    )
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    syncing.value = false
  }
}

async function resolve(path, resolution) {
  try {
    await api('/api/v1/deps/conflicts/resolve', {
      method: 'POST',
      body: { path, resolution, content: conflictDraft[path] || '' },
    })
    ElMessage.success(`已解决 ${path}`)
    conflictOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function openHistory() {
  try {
    const r = await api('/api/v1/deps/history')
    history.value = r.history || []
    historyOpen.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function showDiff(row) {
  try {
    const r = await api(`/api/v1/deps/diff?commit=${encodeURIComponent(row.commit)}`)
    diffText.value = r.diff || ''
    diffOpen.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function revert(row) {
  if (!await confirmBox(
    `回滚到提交 ${row.short}？会生成一个反向提交，不改写历史。`,
    '回滚提交', { type: 'warning', confirmButtonText: '回滚' },
  )) return
  try {
    await api('/api/v1/deps/revert', {
      method: 'POST',
      body: { commit: row.commit, message: `回滚到 ${row.short}` },
    })
    ElMessage.success('已生成回滚提交')
    historyOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function loadSettings() {
  try {
    const s = await api('/api/v1/deps/settings')
    Object.assign(settings, s, { private_key: '', token: '' })
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function openSettings() {
  await loadSettings()
  settingsOpen.value = true
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await api('/api/v1/deps/settings', { method: 'PUT', body: { ...settings } })
    ElMessage.success('设置已保存')
    settingsOpen.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingSettings.value = false
  }
}

async function genKey() {
  try {
    const r = await api('/api/v1/deps/generate-key', { method: 'POST' })
    settings.private_key = r.public_key ? '' : ''
    ElMessage.success('已生成密钥对，私钥已加密保存')
    await loadSettings()
    await navigator.clipboard.writeText(r.public_key || '').catch(() => {})
    ElMessage.info('公钥已复制到剪贴板')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function goRuleSources() {
  router.push('/admin/rule-providers')
}
</script>

<style scoped>
.mp-deps-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
.mp-deps-repo { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13px; }
.mp-deps-branch { color: var(--mp-text-secondary); }
.mp-deps-commit { color: var(--mp-text-secondary); }
.mp-deps-badges { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.mp-deps-error { color: var(--mp-danger); font-size: 12.5px; margin: 6px 0 0; }
.mp-deps-body {
  display: grid;
  grid-template-columns: minmax(240px, 320px) 1fr;
  gap: 14px;
  align-items: start;
}
.mp-deps-tree { max-height: 70vh; overflow: auto; }
.mp-deps-tree-head {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 600; font-size: 13px; margin-bottom: 8px;
}
.mp-deps-dir { margin-bottom: 6px; }
.mp-deps-dir-head {
  width: 100%; display: flex; justify-content: space-between; gap: 8px;
  background: none; border: none; color: var(--mp-text); cursor: pointer;
  font-size: 12.5px; padding: 4px 2px; text-align: left;
}
.mp-deps-count { color: var(--mp-text-secondary); font-size: 11.5px; }
.mp-deps-file {
  width: 100%; display: flex; align-items: center; gap: 8px;
  background: none; border: none; border-radius: 6px; cursor: pointer;
  color: var(--mp-text); font-size: 12.5px; padding: 5px 8px; text-align: left;
}
.mp-deps-file:hover { background: var(--mp-surface-2); }
.mp-deps-file.active { background: var(--mp-surface-2); color: var(--mp-primary); }
.mp-deps-file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mp-deps-mark { width: 14px; text-align: center; color: var(--mp-text-secondary); }
.mp-deps-mark[data-status='modified'] { color: var(--mp-warn); }
.mp-deps-mark[data-status='remote'] { color: var(--mp-info, #409eff); }
.mp-deps-mark[data-status='conflict'] { color: var(--mp-danger); }
.mp-deps-detail-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.mp-deps-detail-actions { margin-top: 12px; }
.mp-deps-conflict { margin-bottom: 20px; }
.mp-deps-conflict-path { font-size: 13px; margin: 0 0 8px; }
.mp-deps-three { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 8px; }
.mp-deps-three pre {
  background: var(--mp-surface-2); border-radius: 6px; padding: 8px;
  font-size: 11.5px; max-height: 220px; overflow: auto; margin: 4px 0 0;
  white-space: pre-wrap; word-break: break-all;
}
@media (max-width: 900px) {
  .mp-deps-body { grid-template-columns: 1fr; }
  .mp-deps-three { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  /* 窄屏：状态信息独占一行，按钮组换到下面 */
  .mp-deps-bar { flex-wrap: wrap; }
  .mp-deps-bar-left { flex: 1 1 100%; }
}
</style>
