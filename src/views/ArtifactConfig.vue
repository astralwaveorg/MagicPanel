<template>
  <div class="mp-artifact">
    <p class="mp-page-desc">
      配置分三层：<strong>引擎默认配置</strong>（内置基线，随程序发布）→
      <strong>引擎平台配置</strong>（按引擎 + 平台）→
      <strong>设备独立配置</strong>（最终产物个性化）。
      越靠后优先级越高；每层只保存改动项，其余自动继承上一层。
    </p>

    <!-- 手机：作用域改用下拉选择，左侧长列表在窄屏太占版面 -->
    <el-select
      v-if="isMobile"
      v-model="scopePicker"
      class="mp-artifact-picker"
      placeholder="选择要配置的作用域"
    >
      <el-option-group v-for="group in scopeGroups" :key="group.kind" :label="group.title">
        <el-option
          v-for="s in group.items"
          :key="scopeKey(s)"
          :value="scopeKey(s)"
          :label="s.name || s.label"
        />
      </el-option-group>
    </el-select>

    <div class="mp-artifact-grid">
      <!-- 左：作用域 -->
      <aside v-if="!isMobile" class="mp-artifact-aside">
        <div v-for="group in scopeGroups" :key="group.kind" class="mp-scope-group">
          <div class="mp-scope-group-title">
            {{ group.title }}
            <span v-if="group.hint" class="mp-scope-group-hint">{{ group.hint }}</span>
          </div>
          <button
            v-for="s in group.items" :key="scopeKey(s)"
            class="mp-scope-item" :class="{ active: isActive(s) }"
            type="button" :title="s.detail" @click="select(s)"
          >
            <span class="mp-scope-dot" :class="{ on: s.customized }" />
            <span class="mp-scope-name">{{ s.name || s.label }}</span>
            <span class="mp-scope-tag">{{ scopeTag(s) }}</span>
          </button>
        </div>
      </aside>

      <!-- 右：编辑区 -->
      <section class="mp-artifact-main">
        <div class="mp-card">
          <div class="mp-toolbar">
            <div class="left">
              <div class="mp-scope-current">
                <strong>{{ current ? current.label : '基础配置' }}</strong>
                <span class="mp-toolbar-hint">{{ currentHint }}</span>
                <span v-if="inheritChain.length" class="mp-inherit-chain">
                  继承链：{{ inheritChain.join(' → ') }}
                </span>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <!-- 与旁边的按钮同高：小尺寸的下拉会比按钮矮一截，看着不协调 -->
              <el-select v-model="env" style="width:120px">
                <el-option value="production" label="生产环境" />
                <el-option value="testing" label="测试环境" />
              </el-select>
              <el-button v-if="!readonly" @click="openSource" type="info" plain>源码编辑</el-button>
              <el-button v-if="isBuiltin ? builtinOverridden : !readonly" type="warning" plain @click="reset">
                {{ isBuiltin ? '恢复默认' : '清除改动' }}
              </el-button>
              <el-button @click="preview" type="info" plain>预览产物</el-button>
              <el-button v-if="!readonly" :loading="saving" @click="save" type="primary">
                保存
              </el-button>
              <el-button v-if="!readonly" :loading="applying" @click="apply" type="success">
                保存并构建发布
              </el-button>
            </div>
          </div>

          <el-alert v-if="isBuiltin" type="warning" :closable="false" show-icon
                    style="margin-bottom:12px">
            <strong>引擎默认配置是所有客户端的基础</strong>：修改将影响该引擎下的全部客户端，
            并被下层引擎平台配置与设备独立配置继承。保存时仅记录改动项，支持随时「恢复默认」。
          </el-alert>
          <el-alert v-else-if="!changedCount" type="info" :closable="false" show-icon
                    style="margin-bottom:12px">
            当前层级暂无改动，完全继承上层。保存时仅记录改动项。
          </el-alert>
          <el-alert v-else type="success" :closable="false" show-icon
                    style="margin-bottom:12px">
            当前层级已改动 {{ changedCount }} 个键（蓝色为新增，橙色为覆盖），其余继承上层。
          </el-alert>

          <!-- 生效配置：可点击编辑；本层改动过的键用颜色标出 -->
          <div class="mp-effective-toolbar">
            <el-button v-if="!readonly" size="small" @click="openAddParam" type="primary">新增参数</el-button>
            <span class="mp-toolbar-hint">
              点「值」或「编辑」在弹窗里改（按值类型给编辑器）；覆盖键会带继承值删除线对比。保存时仅记录改动项。
            </span>
            <span class="mp-legend">
              <span class="mp-legend-item is-added">本层新增</span>
              <span class="mp-legend-item is-overridden">本层覆盖</span>
            </span>
          </div>
          <!-- 窄屏：表格会把"值"挤到屏幕外，改成卡片列表（键在上、值在下） -->
          <div v-if="isMobile" class="mp-effective-list">
            <div v-for="row in effectiveRows" :key="row.path" class="mp-effective-item"
                 :class="changeClass(row)">
              <div class="mp-effective-item-head">
                <span class="mono mp-effective-key" :class="changeClass(row)">{{ row.path }}</span>
                <el-tag size="small" :type="row.source === layerLabel ? 'primary' : 'info'"
                        effect="plain">{{ row.source }}</el-tag>
              </div>
              <div class="mp-effective-item-value">
                <span class="mono mp-effective-value"
                      :class="{ editable: !readonly && !row.isDict }"
                      @click="openKeyEditor(row)">{{ row.display
                      }}<template v-if="row.change === 'overridden'">
                        <s class="mp-oldval">{{ formatValue(getPath(baseline, row.path)) }}</s></template></span>
              </div>
            </div>
          </div>

          <el-table v-else :data="effectiveRows" size="small" class="mp-effective-table"
                    row-key="path" :row-class-name="rowClass">
            <el-table-column label="键" min-width="210">
              <template #default="{ row }">
                <span class="mono mp-effective-key" :class="changeClass(row)"
                      :style="{ paddingLeft: (row.depth * 16) + 'px' }">
                  <span v-if="row.depth" class="mp-effective-branch">└</span>{{ row.key }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="值" min-width="260">
              <template #default="{ row }">
                <span class="mono mp-effective-value"
                      :class="{ editable: !readonly && !row.isDict }"
                      @click="openKeyEditor(row)">{{ row.display
                      }}<template v-if="row.change === 'overridden'">
                        <s class="mp-oldval">{{ formatValue(getPath(baseline, row.path)) }}</s></template></span>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="110" align="right">
              <template #default="{ row }">
                <el-tag size="small" :type="row.source === layerLabel ? 'primary' : 'info'"
                        effect="plain">{{ row.source }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="!readonly" label="操作" width="150" align="right">
              <template #default="{ row }">
                <el-button v-if="!row.isDict" size="small" text type="primary"
                           @click="openKeyEditor(row)">编辑</el-button>
                <el-button v-if="!row.isDict && row.overridden" size="small" text
                           @click="revertKey(row)" type="warning">恢复继承</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 当前层级编辑 -->
          <template v-if="!readonly">
            <el-form :model="doc" label-position="top">
              <template v-for="group in groupOrder" :key="group">
                <div v-if="fieldsOf(group).length" style="margin-bottom:16px">
                  <div class="mp-subsection">{{ groupLabels[group] || group }}</div>
                  <el-row :gutter="12">
                    <el-col v-for="f in fieldsOf(group)" :key="f.key" :xs="24" :sm="12" :md="8">
                      <el-form-item :label="f.label">
                        <el-select v-if="f.type === 'select'" :model-value="getValue(f.key)"
                                   style="width:100%" @change="(v) => setValue(f.key, v)">
                          <el-option v-for="opt in f.options" :key="opt.value"
                                     :value="opt.value" :label="opt.label" />
                        </el-select>
                        <el-switch v-else-if="f.type === 'switch'" :model-value="getValue(f.key)"
                                   @update:model-value="(v) => setValue(f.key, v)" />
                        <el-input-number v-else-if="f.type === 'number'" :model-value="getValue(f.key)"
                                         :min="f.min ?? 0" :max="f.max ?? 65535"
                                         style="width:100%"
                                         @update:model-value="(v) => setValue(f.key, v)" />
                        <el-input v-else-if="f.type === 'list'" :model-value="listText(f.key)"
                                  type="textarea" :rows="3" class="mono"
                                  :placeholder="f.placeholder || '每行一个'"
                                  @input="(v) => setListText(f.key, v)" />
                        <el-input v-else :model-value="getValue(f.key) || ''"
                                  :placeholder="f.placeholder || ''"
                                  @input="(v) => setValue(f.key, v)" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </div>
              </template>

              <el-form-item label="高级 YAML（其他顶层键）">
                <CodeEditor v-model="raw" language="yaml" height="300px" />
                <div class="mp-form-hint">
                  编辑的是最终生效值，保存时只把与上层不同的部分记到当前层级。
                  字典逐层合并，列表整体替换。
                  不能包含 proxies / proxy-providers / proxy-groups / rule-providers / rules。
                </div>
              </el-form-item>

              <el-form-item label="预设">
                <div class="mp-template-bar">
                  <el-select v-model="presetKey" size="small" style="width:200px"
                             @change="applyPreset">
                    <el-option v-for="p in presets" :key="p.key" :value="p.key" :label="p.label" />
                  </el-select>
                  <span class="mp-form-hint">
                    套用后会覆盖当前层级对应的键。
                    <template v-if="presetKey === 'mtproto'">
                      MTProto 请套用到「设备独立配置」：哪台设备要用就加一份，不想用时删掉该层的 mtproto 段即可。
                    </template>
                  </span>
                </div>
              </el-form-item>
            </el-form>
          </template>

          <template v-else>
            <h3 class="mp-section-title">默认内容（可直接修改）</h3>
            <CodeEditor v-model="raw" language="yaml" height="46vh" />
            <div class="mp-form-hint">
              这里是引擎默认配置的完整内容。保存时只把
              <strong>与默认值不同的部分</strong>记下来，其余保持原样；
              改动会影响该引擎下所有引擎平台配置与设备独立配置。点「恢复默认」即可还原。
            </div>
          </template>
        </div>
      </section>
    </div>

    <el-dialog v-model="keyDialog" title="编辑参数" width="min(620px, 94vw)">
      <div class="mp-key-head">
        <span class="mono mp-key-path">{{ keyForm.path }}</span>
        <el-tag size="small" effect="plain"
                :type="keyChangeType === 'overridden' ? 'warning'
                  : keyChangeType === 'added' ? 'primary' : 'info'">
          {{ keyChangeLabel }}
        </el-tag>
      </div>
      <div v-if="keyChangeType === 'overridden'" class="mp-key-inherited">
        <span class="mp-toolbar-hint">上层继承值</span>
        <div class="mono mp-key-oldval">{{ formatValue(keyInherited) }}</div>
      </div>
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="keyForm.kind === 'bool'" label="布尔值">
          <el-switch v-model="keyForm.bool" />
          <span class="mono mp-key-bool">{{ keyForm.bool }}</span>
        </el-form-item>
        <el-form-item v-else-if="keyForm.kind === 'number'" label="数字">
          <el-input-number v-model="keyForm.num" style="width:100%" />
        </el-form-item>
        <el-form-item v-else-if="keyForm.kind === 'list'" label="字符串列表">
          <div class="mp-key-list">
            <div v-for="(_, i) in keyForm.list" :key="i" class="mp-key-list-row">
              <el-input v-model="keyForm.list[i]" class="mono" size="small"
                        :placeholder="'留空保存时忽略'" />
              <el-button size="small" text type="danger"
                         @click="keyForm.list.splice(i, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="keyForm.list.push('')">添加一项</el-button>
          </div>
        </el-form-item>
        <el-form-item v-else-if="keyForm.kind === 'yaml'" label="值（YAML）">
          <CodeEditor v-model="keyForm.yaml" language="yaml" height="240px" />
        </el-form-item>
        <el-form-item v-else label="文本值（留空保存为 null）">
          <el-input v-model="keyForm.text" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="keyChangeType === 'overridden'" type="warning" plain
                   @click="revertInDialog">恢复继承</el-button>
        <el-button @click="keyDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmKeyEditor">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addDialog" title="新增参数" width="min(560px, 94vw)">
      <p class="mp-dialog-desc">
        在任意节点下新增参数。路径用点号分隔，如 <span class="mono">dns.nameserver</span>；
        顶层参数直接写名字。值按 YAML 解析：<span class="mono">true</span>、<span class="mono">123</span>、
        <span class="mono">["1.1.1.1","8.8.8.8"]</span> 或一段映射。
      </p>
      <el-form :model="addForm" label-position="top">
        <el-form-item label="参数路径">
          <el-input v-model="addForm.path" class="mono" placeholder="例如 dns.nameserver 或 sniffer" />
        </el-form-item>
        <el-form-item label="参数值（YAML）">
          <el-input v-model="addForm.value" type="textarea" :rows="5" class="mono"
                    placeholder='例如：&#10;- "1.1.1.1"&#10;- "8.8.8.8"' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button @click="confirmAddParam" type="primary">新增</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sourceVisible" title="源码编辑" width="min(760px, 94vw)">
      <p class="mp-dialog-desc">
        直接编辑当前层级的 YAML 源码，必须是合法 YAML，层级用缩进表达。
        应用后回到编辑器，确认无误再点「保存」；保存时仍会做键级校验
        （不能包含 proxies / proxy-providers / proxy-groups / rule-providers / rules）。
      </p>
      <CodeEditor v-model="sourceText" language="yaml" height="52vh" />
      <template #footer>
        <el-button @click="sourceVisible = false">取消</el-button>
        <el-button @click="applySource" type="primary">应用到编辑器</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="产物预览" width="min(920px, 94vw)">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <el-select v-model="previewPlatform" size="small" style="width:200px" @change="doPreview">
          <el-option v-for="p in platforms" :key="p.value" :value="p.value" :label="p.label" />
        </el-select>
        <span class="mp-toolbar-hint">{{ previewNote }}</span>
      </div>
      <div v-if="previewWarnings.length" class="mp-form-hint" style="margin-bottom:8px">
        <div v-for="(w, i) in previewWarnings" :key="i">⚠ {{ w }}</div>
      </div>
      <el-input :model-value="previewText" type="textarea" :rows="24" readonly class="mono" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { dump, load as yamlLoad } from 'js-yaml'
import yaml from 'js-yaml'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { PLATFORM_LABELS, ENV_LABELS } from '../format'
import CodeEditor from '../components/CodeEditor.vue'

const scopes = ref([])
const isMobile = useMobile()
const scopePicker = ref('')
const platforms = ref([])
const current = ref(null)
const state = ref(null)
const fields = ref([])
const groups = ref({})
const presets = ref([])
const doc = reactive({})
const raw = ref('')
const env = ref('production')
const saving = ref(false)
const applying = ref(false)
const previewVisible = ref(false)
const previewText = ref('')
const previewPlatform = ref('')
const previewNote = ref('')
const previewWarnings = ref([])
const presetKey = ref('')
const syncing = ref(false)
const keyDialog = ref(false)
const keyForm = reactive({
  path: '', kind: 'string', bool: false, num: 0, text: '', list: [], yaml: '',
})
const keyInherited = ref(undefined)
const keyOriginal = ref(undefined)
const addDialog = ref(false)
const addForm = reactive({ path: '', value: '' })

const groupOrder = computed(() => Object.keys(groups.value))

const scopeGroups = computed(() => {
  const byKind = { builtin: [], general: [], device: [] }
  for (const s of scopes.value) {
    if (!byKind[s.kind]) byKind[s.kind] = []
    byKind[s.kind].push(s)
  }
  return [
    { kind: 'builtin', title: '引擎默认配置', hint: '引擎内置基线', items: byKind.builtin },
    { kind: 'general', title: '引擎平台配置', hint: '按引擎 + 平台', items: byKind.general },
    { kind: 'device', title: '设备独立配置', hint: '按设备', items: byKind.device },
  ].filter((g) => g.items.length)
})

// ---- 源码编辑 ----
const sourceVisible = ref(false)
const sourceText = ref('')

function openSource() {
  sourceText.value = raw.value || ''
  sourceVisible.value = true
}

function applySource() {
  try {
    const parsed = yaml.load(sourceText.value || '') || {}
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
      ElMessage.error('源码必须是 YAML 对象（键值对）')
      return
    }
  } catch (e) {
    ElMessage.error(`YAML 语法有误：${e.message || e}`)
    return
  }
  raw.value = sourceText.value
  sourceVisible.value = false
  ElMessage.success('已应用到编辑器，点「保存」生效')
}

// 引擎默认配置是整条链路最底层，改动前必须明确告知影响范围
async function confirmBuiltinChange() {
  return confirmBox(
    '引擎默认配置是所有客户端的基础：修改将影响该引擎下的全部客户端，'
    + '并被下层引擎平台配置与设备独立配置继承。确定要修改吗？',
    '修改引擎默认配置',
    { type: 'warning', confirmButtonText: '继续修改' })
}

// 引擎默认配置也可改：改的是"默认值之上的差异"，可一键恢复默认
const readonly = computed(() => false)
const isBuiltin = computed(() => current.value?.kind === 'builtin')
const builtinOverridden = computed(() =>
  isBuiltin.value && Object.keys(state.value?.overlay || {}).length > 0)
const layerLabel = computed(() => {
  if (!current.value) return ''
  if (current.value.kind === 'builtin') return '引擎默认配置'
  if (current.value.kind === 'general') return '引擎平台配置'
  return '设备独立配置'
})

// 继承链：本层继承自哪几层，一眼看清"这个值是从哪儿来的"
const inheritChain = computed(() => {
  const layers = state.value?.layers || []
  if (!layers.length) return []
  const self = layers[layers.length - 1]
  if (layers.length === 1) return [`${self.label}（基线，${self.scope}）`]
  return layers.map((l) => `${l.label} · ${l.scope}`)
})

const currentHint = computed(() => {
  if (!current.value) return ''
  const s = current.value
  if (s.kind === 'builtin') return '引擎内置的默认内容，是该引擎全部配置的起点'
  if (s.kind === 'general') return '覆盖引擎默认配置，作用于该引擎 + 平台的全部设备'
  return `覆盖引擎平台配置，仅对当前设备生效（${s.detail}）`
})

// 生效配置展开成"点号路径"的扁平行：字典行是分组标题，叶子行可编辑。
// 这样既能直接改某个叶子参数（如 dns.nameserver），也不会让人误以为
// 顶层键是一整块不可分割的东西。
function flattenDoc(obj, prefix = '', depth = 0, out = []) {
  for (const [k, v] of Object.entries(obj || {})) {
    const path = prefix ? `${prefix}.${k}` : k
    const isDict = !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length > 0
    out.push({ path, key: k, depth, value: v, isDict })
    if (isDict) flattenDoc(v, path, depth + 1, out)
  }
  return out
}

// 基线：上层生效值（引擎默认配置层则是程序内置的默认值）。
// 本层保存的就是"相对基线的差异"，所以拿它对比就能看出哪些键是本层动过的。
const baseline = computed(() => state.value?.inherited || {})

const effectiveRows = computed(() => {
  const leafSrc = state.value?.leaf_sources || {}
  const topSrc = state.value?.sources || {}
  const base = baseline.value
  // 以编辑缓冲区为准：改完立刻能看到，不用等保存
  const rows = flattenDoc(doc)
  const seen = new Set(rows.map((r) => r.path))
  // 被删掉的键仍然要显示：它已经回到基线值，不该凭空消失
  for (const r of flattenDoc(base)) {
    if (!seen.has(r.path)) rows.push({ ...r, restored: true })
  }
  return rows.map((row) => {
    const changed = isOverridden(row.path)
    return {
      ...row,
      simple: row.value === null || typeof row.value !== 'object',
      display: row.isDict ? `{ ${Object.keys(row.value).length} 项 }` : formatValue(row.value),
      source: leafSrc[row.path] || topSrc[row.key] || '引擎默认配置',
      overridden: changed,
      // 本层新增（基线里没有这个键）/ 本层覆盖（基线里有但值不同）
      change: changed && !row.isDict
        ? (getPath(base, row.path) === undefined ? 'added' : 'overridden')
        : '',
    }
  })
})

const changedCount = computed(() => effectiveRows.value.filter((r) => r.change).length)

// 行底色 + 文字颜色：一眼看出哪些是本层动过的
function changeClass(row) {
  if (row.change === 'added') return 'is-added'
  if (row.change === 'overridden') return 'is-overridden'
  return ''
}

function rowClass({ row }) {
  return row.change ? `mp-row-${row.change}` : ''
}

function isOverridden(path) {
  const cur = getPath(doc, path)
  if (cur === undefined) return false
  const inherited = getPath(baseline.value, path)
  return JSON.stringify(cur) !== JSON.stringify(inherited)
}

function deletePath(obj, path) {
  const keys = path.split('.')
  let cur = obj
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (!cur || typeof cur !== 'object') return
    cur = cur[keys[i]]
  }
  if (cur && typeof cur === 'object') delete cur[keys[keys.length - 1]]
}

function formatValue(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    const text = JSON.stringify(value)
    return text.length > 120 ? `${text.slice(0, 120)}…` : text
  }
  return String(value)
}

// ---- 键编辑弹窗：按值的类型给编辑器，弹窗内可见上层继承值 ----
const keyChangeType = computed(() => {
  if (!keyForm.path) return ''
  const base = getPath(baseline.value, keyForm.path)
  if (base === undefined) return 'added'
  return JSON.stringify(getPath(doc, keyForm.path)) === JSON.stringify(base)
    ? 'unchanged' : 'overridden'
})
const keyChangeLabel = computed(() => ({
  added: '本层新增', overridden: '本层覆盖', unchanged: '继承上层',
}[keyChangeType.value] || ''))

function openKeyEditor(row) {
  if (readonly.value || row.isDict) return
  keyForm.path = row.path
  keyInherited.value = getPath(baseline.value, row.path)
  const v = getPath(doc, row.path)
  keyOriginal.value = v
  if (typeof v === 'boolean') {
    keyForm.kind = 'bool'; keyForm.bool = v
  } else if (typeof v === 'number') {
    keyForm.kind = 'number'; keyForm.num = v
  } else if (Array.isArray(v) && v.every((x) => x === null || typeof x !== 'object')) {
    keyForm.kind = 'list'; keyForm.list = v.map((x) => (x === null ? '' : String(x)))
  } else if (v === null || typeof v === 'string') {
    keyForm.kind = 'string'; keyForm.text = v ?? ''
  } else {
    keyForm.kind = 'yaml'; keyForm.yaml = toYaml(v)
  }
  keyDialog.value = true
}

function revertInDialog() {
  deletePath(doc, keyForm.path)
  syncRaw()
  keyDialog.value = false
  ElMessage.success(`已恢复 ${keyForm.path} 继承上层，保存后生效`)
}

function confirmKeyEditor() {
  let value
  if (keyForm.kind === 'bool') value = keyForm.bool
  else if (keyForm.kind === 'number') value = keyForm.num
  else if (keyForm.kind === 'list') {
    value = keyForm.list.map((s) => coerceScalar(s))
      .filter((s) => s !== null && s !== '')
  } else if (keyForm.kind === 'string') {
    value = keyForm.text === '' ? null : keyForm.text
  } else {
    try {
      value = yamlLoad(keyForm.yaml) ?? null
    } catch (e) {
      ElMessage.error(`YAML 不合法：${e.message}`)
      return
    }
  }
  setPath(doc, keyForm.path, value)
  syncRaw()
  keyDialog.value = false
  ElMessage.success(`已修改 ${keyForm.path}，保存后生效`)
}

// 标量按 YAML 习惯转成布尔 / 数字，其余按字符串
function coerceScalar(text) {
  const t = String(text).trim()
  if (t === 'true') return true
  if (t === 'false') return false
  if (t === 'null' || t === '') return null
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  return text
}

function revertKey(row) {
  deletePath(doc, row.path)
  syncRaw()
  ElMessage.success(`已恢复 ${row.path} 继承上层，保存后生效`)
}

function openAddParam() {
  addForm.path = ''
  addForm.value = ''
  addDialog.value = true
}

function confirmAddParam() {
  const path = addForm.path.trim()
  if (!path) {
    ElMessage.warning('请填写参数路径')
    return
  }
  let value
  const text = addForm.value.trim()
  if (text) {
    try {
      value = yamlLoad(text)
    } catch (e) {
      ElMessage.error(`值不是合法的 YAML：${e.message}`)
      return
    }
  } else {
    value = ''
  }
  setPath(doc, path, value)
  syncRaw()
  addDialog.value = false
  ElMessage.success(`已在 ${path} 新增参数，保存后生效`)
}

function scopeKey(s) {
  return `${s.kind}:${s.engine}:${s.platform || ''}:${s.device_id || 0}`
}

function scopeTag(s) {
  if (s.kind === 'builtin') return '默认'
  if (s.kind === 'general') return '通用'
  return '设备'
}

function isActive(s) {
  return current.value && scopeKey(current.value) === scopeKey(s)
}

function fieldsOf(group) {
  return fields.value.filter((f) => f.group === group)
}

function getPath(obj, path) {
  return path.split('.').reduce((acc, key) => (acc == null ? acc : acc[key]), obj)
}

function setPath(obj, path, value) {
  const keys = path.split('.')
  let cur = obj
  keys.slice(0, -1).forEach((key) => {
    if (typeof cur[key] !== 'object' || cur[key] === null) cur[key] = {}
    cur = cur[key]
  })
  cur[keys[keys.length - 1]] = value
}

function getValue(key) {
  const value = getPath(doc, key)
  return value === undefined ? null : value
}

function setValue(key, value) {
  setPath(doc, key, value)
  syncRaw()
}

function listText(key) {
  const value = getPath(doc, key)
  if (Array.isArray(value)) return value.join('\n')
  return value ? String(value) : ''
}

function setListText(key, text) {
  const lines = String(text).split('\n').map((s) => s.trim()).filter(Boolean)
  setPath(doc, key, lines)
  syncRaw()
}

function syncRaw() {
  syncing.value = true
  raw.value = toYaml(doc)
  nextTick(() => { syncing.value = false })
}

function toYaml(obj) {
  return dump(obj, { lineWidth: 120, noRefs: true, sortKeys: false })
}

function parseYaml(text) {
  const data = yamlLoad(text)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('基础配置必须是键值映射')
  }
  return data
}

// 高级 YAML 是同一份文档的另一个视图：改动文本后回填表单
watch(raw, (text) => {
  if (syncing.value) return
  try {
    const parsed = parseYaml(text)
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, parsed)
  } catch { /* 非法 YAML 保留原文，保存时由服务端提示 */ }
})

async function loadScopes() {
  const data = await api('/api/v1/base-config/scopes')
  scopes.value = data.scopes
}

async function loadSchema(engine) {
  const schema = await api(`/api/v1/base-config/schema?engine=${engine}`)
  fields.value = schema.fields
  groups.value = schema.groups
  presets.value = schema.presets
  presetKey.value = ''
}

// 手机上下拉切换作用域
watch(scopePicker, (key) => {
  if (!key) return
  const target = scopes.value.find((s) => scopeKey(s) === key)
  if (target && (!current.value || scopeKey(current.value) !== key)) select(target)
})

async function select(scope) {
  const previous = current.value
  current.value = scope
  try {
    await loadSchema(scope.engine)
    const params = new URLSearchParams({ engine: scope.engine })
    if (scope.platform) params.set('platform', scope.platform)
    if (scope.device_id) params.set('device_id', String(scope.device_id))
    const data = await api(`/api/v1/base-config?${params.toString()}`)
    state.value = data
    scopePicker.value = scopeKey(scope)
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, data.effective || {})
    raw.value = data.content || ''
    syncing.value = true
    nextTick(() => { syncing.value = false })
  } catch (e) {
    // 切换失败时回滚到上一个作用域，避免标题与内容对不上
    current.value = previous
    ElMessage.error(e.message)
  }
}

// 现场生成 32 位十六进制密钥（MTProto 用；官方建议 openssl rand -hex 16）
function randomSecret() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function applyPreset(key) {
  const preset = presets.value.find((p) => p.key === key)
  if (!preset) return
  const content = preset.content.includes('{{mtproto_secret}}')
    ? preset.content.replace('{{mtproto_secret}}', randomSecret())
    : preset.content
  raw.value = content
  try {
    const parsed = parseYaml(content)
    Object.keys(doc).forEach((k) => delete doc[k])
    Object.assign(doc, parsed)
  } catch { /* 预设由服务端保证合法 */ }
  if (content !== preset.content) {
    ElMessage.success('已套用预设并生成新的 MTProto 密钥，请复制到 Telegram 客户端')
  }
}

function scopeQuery() {
  const s = current.value
  if (!s) return ''
  const params = new URLSearchParams({ engine: s.engine })
  if (s.platform) params.set('platform', s.platform)
  if (s.device_id) params.set('device_id', String(s.device_id))
  return params.toString()
}

async function save() {
  if (!current.value) return
  if (isBuiltin.value && !(await confirmBuiltinChange())) return
  saving.value = true
  try {
    const r = await api(`/api/v1/base-config?${scopeQuery()}`, {
      method: 'PUT',
      body: { content: raw.value, updated_at: state.value?.updated_at || '' },
    })
    state.value = r
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, r.effective || {})
    raw.value = r.content || ''
    await loadScopes()
    ElMessage.success('已保存，重新构建并发布后生效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function reset() {
  if (!current.value) return
  if (isBuiltin.value) {
    const ok = await confirmBox(
      '恢复默认会丢弃对引擎默认配置的所有修改，回到随程序发布的默认内容。确定继续？',
      '恢复默认', { type: 'warning', confirmButtonText: '恢复默认' })
    if (!ok) return
  } else if (!await confirmBox('清空当前层改动，恢复继承上层？', '清除改动',
                        { type: 'warning' })) return
  try {
    const r = await api(`/api/v1/base-config/reset?${scopeQuery()}`, { method: 'POST' })
    state.value = r
    const kept = Object.keys(r.overlay || {}).length
    if (isBuiltin.value) {
      ElMessage.success('已恢复为引擎默认配置内容')
    } else {
      ElMessage.success(kept
        ? `已恢复继承上层（保留个人直连域名与 Fake-IP 过滤 ${kept} 项）`
        : '已恢复继承上层')
    }
    Object.keys(doc).forEach((key) => delete doc[key])
    Object.assign(doc, r.effective || {})
    raw.value = r.content || ''
    await loadScopes()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function apply() {
  if (!current.value) return
  if (isBuiltin.value && !(await confirmBuiltinChange())) return
  applying.value = true
  try {
    const s = current.value
    const r = await api('/api/v1/base-config/apply', {
      method: 'POST',
      body: {
        engine: s.engine, platform: s.platform, device_id: s.device_id,
        content: raw.value, env: env.value, note: '更新基础配置',
      },
    })
    ElMessage.success(`已构建 #${r.build_id} 并发布到${ENV_LABELS[env.value] || env.value}`)
    await loadScopes()
    await select(current.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    applying.value = false
  }
}

async function preview() {
  previewVisible.value = true
  if (!previewPlatform.value && current.value?.platform) {
    previewPlatform.value = current.value.platform
  }
  await doPreview()
}

async function doPreview() {
  if (!previewPlatform.value) return
  try {
    const r = await api('/api/v1/base-config/preview', {
      method: 'POST',
      body: {
        engine: current.value?.engine || 'stash',
        platform: previewPlatform.value,
        device_id: current.value?.device_id || 0,
      },
    })
    previewText.value = r.content
    previewNote.value = r.note
    previewWarnings.value = r.warnings || []
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  try {
    await loadScopes()
    // 默认落在「引擎默认配置」的第一个（Stash 默认）：这是整条配置链的起点
    const first = scopes.value.find((s) => s.kind === 'builtin') || scopes.value[0]
    if (first) await select(first)
    const seen = new Set()
    for (const s of scopes.value) {
      if (s.kind === 'general' && !seen.has(s.platform)) {
        seen.add(s.platform)
        platforms.value.push({ value: s.platform, label: PLATFORM_LABELS[s.platform] || s.platform })
      }
    }
    previewPlatform.value = current.value?.platform || platforms.value[0]?.value || ''
  } catch (e) {
    ElMessage.error(e.message)
  }
})
</script>


<style scoped>
.mp-artifact-picker {
  width: 100%;
  margin-bottom: 10px;
}

.mp-artifact-grid {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .mp-artifact-grid { grid-template-columns: 1fr; }
}
.mp-artifact-aside {
  background: var(--mp-card-bg, #1b1c20);
  border: 1px solid var(--mp-border, #2c2e33);
  border-radius: 10px;
  padding: 12px;
}
.mp-scope-group + .mp-scope-group { margin-top: 14px; }
.mp-scope-group-title {
  font-size: 12px;
  color: var(--mp-text-secondary);
  letter-spacing: .04em;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.mp-scope-group-hint { font-size: 11px; opacity: .7; }
.mp-scope-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 7px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--mp-text, #e6e7ea);
  font-size: 13px;
  cursor: pointer;
}
.mp-scope-item:hover { background: var(--mp-hover, rgba(255, 255, 255, .05)); }
.mp-scope-item.active {
  background: var(--mp-accent-soft, rgba(64, 158, 255, .16));
  color: var(--mp-accent, #409eff);
}
.mp-scope-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--mp-border, #3a3d44); flex: none;
}
.mp-scope-dot.on { background: var(--mp-accent, #409eff); }
.mp-scope-name {
  flex: 1; min-width: 0; line-height: 1.5;
  overflow-wrap: anywhere;
}
.mp-scope-tag { font-size: 11px; opacity: .55; }
.mp-scope-current { display: flex; flex-direction: column; gap: 2px; }
.mp-inherit-chain {
  font-size: 12px;
  color: var(--mp-text-secondary);
  border-left: 2px solid var(--mp-border);
  padding-left: 8px;
}
.mp-section-title { font-size: 13px; font-weight: 600; margin: 18px 0 8px; }
.mp-subsection { font-size: 12px; color: var(--mp-text-secondary); margin-bottom: 8px; }
.mp-effective-table { margin-bottom: 4px; }
.mp-effective-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mp-effective-item {
  border: 1px solid var(--el-border-color-lighter, #eee);
  border-radius: 8px;
  padding: 8px 10px;
}
.mp-effective-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.mp-effective-item-value {
  font-size: 13px;
}

.mp-effective-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.mp-effective-key {
  white-space: nowrap;
}
.mp-effective-branch {
  color: var(--mp-text-dim, #888);
  margin-right: 4px;
}
.mp-effective-value {
  cursor: default;
  word-break: break-all;
  white-space: pre-wrap;
}
.mp-effective-value.editable {
  cursor: text;
  border-bottom: 1px dashed rgba(64, 158, 255, 0.45);
}
.mp-effective-value.editable:hover {
  color: var(--el-color-primary);
}
.mp-effective-actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

/* 本层改动过的键：蓝色=新增，橙色=覆盖 */
.mp-legend {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  font-size: 12px;
  color: var(--mp-text-secondary);
}
.mp-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.mp-legend-item::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.mp-legend-item.is-added::before { background: var(--el-color-primary); }
.mp-legend-item.is-overridden::before { background: var(--el-color-warning); }

.mp-effective-key.is-added { color: var(--el-color-primary); }
.mp-effective-key.is-overridden { color: var(--el-color-warning); }
.mp-effective-item.is-added {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.mp-effective-item.is-overridden {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}

/* 表格行底色：改动过的行淡染一下，扫一眼就能看到 */
.mp-effective-table :deep(.mp-row-added) { background: var(--el-color-primary-light-9); }
.mp-effective-table :deep(.mp-row-overridden) { background: var(--el-color-warning-light-9); }
/* 键编辑弹窗 */
.mp-key-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.mp-key-path { font-size: 13.5px; font-weight: 600; }
.mp-key-inherited {
  background: var(--mp-surface-2);
  border: 1px dashed var(--mp-border);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 12px;
}
.mp-key-oldval { margin-top: 4px; font-size: 12.5px; color: var(--mp-text-secondary); }
.mp-key-bool { margin-left: 10px; }
.mp-key-list { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.mp-key-list-row { display: flex; gap: 8px; align-items: center; }

/* 值列：覆盖键在当前值后面带继承值删除线 */
.mp-oldval {
  margin-left: 12px;
  color: var(--mp-muted);
  font-size: 12px;
}
</style>
