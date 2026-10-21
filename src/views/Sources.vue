<template>
  <div>
    <h2 class="mp-page-title">节点来源</h2>
    <p class="mp-page-desc">
      订阅地址加密存储，列表不展示；点击“复制 URL”获取。抓取失败保留最近成功快照。
      测速由本地 Mihomo 逐节点拨测，仅反映服务器网络连通性，不代表客户端可用。
    </p>

    <el-alert
      v-if="core && !core.available"
      type="warning"
      :closable="false"
      style="margin-bottom: 14px"
    >
      <template #title>
        测速核心未安装，测速不可用。
        <el-button size="small" type="warning" plain :loading="installingCore"
                   style="margin-left: 8px" @click="installCore">
          在线安装最新版
        </el-button>
        <el-upload
          :auto-upload="false" :show-file-list="false" :on-change="onUploadCore"
          style="display:inline-block;margin-left:8px"
        >
          <el-button size="small" plain :loading="installingCore">本地上传</el-button>
        </el-upload>
      </template>
    </el-alert>

    <div class="mp-toolbar">
      <div class="left">
        <template v-if="selected.length">
          <span class="mp-selected-hint">已选 {{ selected.length }} 项</span>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing || batchTesting"
                     @click="refreshMany(selected)">抓取选中</el-button>
          <el-button :loading="batchTesting" :disabled="batchRefreshing || batchTesting"
                     @click="testMany(selected)">测速选中</el-button>
          <el-button :disabled="batchRefreshing || batchTesting"
                     @click="openBatchInterval">修改抓取间隔</el-button>
          <el-button type="danger" plain :disabled="batchRefreshing || batchTesting"
                     @click="removeSelected">批量删除</el-button>
          <el-button link @click="clearSelection">取消选择</el-button>
          <span v-if="batchTesting" class="mp-toolbar-hint">
            正在测速 {{ testDone }}/{{ testTotal }}…
          </span>
        </template>
        <template v-else>
          <el-button :loading="batchRefreshing" :disabled="batchRefreshing || batchTesting"
                     @click="refreshMany(rows)">一键抓取</el-button>
          <el-button :loading="batchTesting" :disabled="batchRefreshing || batchTesting"
                     @click="testMany(rows)">一键测速</el-button>
          <span v-if="batchRefreshing" class="mp-toolbar-hint">
            正在抓取 {{ refreshDone }}/{{ refreshTotal }}…
          </span>
          <span v-else-if="batchTesting" class="mp-toolbar-hint">
            正在测速 {{ testDone }}/{{ testTotal }}…
          </span>
        </template>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <el-button type="primary" @click="openEdit()">添加订阅</el-button>
        <el-button type="primary" plain @click="openLocalEdit()">添加节点</el-button>
      </div>
    </div>

    <ErrorState v-if="error" :error="error" @retry="load" />


    <EmptyState
      v-if="!rows.length"
      reason="还没有订阅来源。"
      next="点击“添加订阅”，填入订阅地址后执行抓取。"
    />
    <div v-else class="mp-card">
      <div class="mp-table-wrap">
        <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="id"
                  @selection-change="onSelectionChange">
          <el-table-column type="selection" width="44" :fixed="isMobile ? false : 'left'" />
          <el-table-column prop="name" label="名称" min-width="100" :fixed="isMobile ? false : 'left'" />
          <el-table-column label="订阅地址" width="110">
            <template #default="{ row }">
              <el-button size="small" @click="copyUrl(row)">复制 URL</el-button>
            </template>
          </el-table-column>
          <el-table-column label="抓取状态" min-width="110">
            <template #default="{ row }">
              <StatusDot v-if="row.auto_fetch === false" kind="muted" text="本地快照" />
              <StatusDot v-else v-bind="sourceStatus(row)" />
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="节点数" width="80" align="right">
            <template #default="{ row }">{{ row.node_count ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="摘要" min-width="130">
            <template #default="{ row }"><span class="mono mp-nowrap">{{ shortSha(row.sha256) }}</span></template>
          </el-table-column>
          <el-table-column label="最近成功" min-width="160">
            <template #default="{ row }">
              <span v-if="row.auto_fetch === false" class="mp-nowrap"
                    style="color:var(--mp-text-secondary)">本地快照</span>
              <span v-else class="mp-nowrap">{{ fmtTime(row.last_fetched_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="失败次数" width="80" align="right">
            <template #default="{ row }">{{ row.auto_fetch === false ? '—' : row.fail_count }}</template>
          </el-table-column>
          <el-table-column label="抓取间隔" width="110" align="right">
            <template #default="{ row }">{{ row.auto_fetch === false ? '—' : row.interval }}</template>
          </el-table-column>
          <el-table-column label="客户端更新" width="110" align="right">
            <template #default="{ row }">{{ row.client_interval || '跟随' }}</template>
          </el-table-column>
          <el-table-column label="测速间隔" width="110" align="right">
            <template #default="{ row }">
              {{ row.auto_test === false ? '关' : (row.test_interval ? row.test_interval : '关') }}
            </template>
          </el-table-column>
          <el-table-column label="最近错误" min-width="160">
            <template #default="{ row }">
              {{ row.auto_fetch === false ? '—' : (row.last_error || '—') }}
            </template>
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
          <el-table-column label="操作" width="252" :fixed="isMobile ? false : 'right'">
            <template #default="{ row }">
              <div class="op-grid">
                <el-button size="small" @click="openNodes(row)">节点</el-button>
                <el-button size="small" :loading="row._refreshing" @click="refresh(row)">抓取</el-button>
                <el-button size="small" :loading="row._testing" @click="testNodes(row)">测速</el-button>
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <Pager :page="page" :limit="limit" :total="total" @change="onPageChange" />
    </div>

    <div class="mp-card">
      <div class="mp-toolbar" style="margin-bottom:12px">
        <h3 style="margin:0">本地节点</h3>
        <span class="mp-toolbar-hint">直接保存在面板中的节点，区别于远程订阅拉取</span>
      </div>
      <EmptyState
        v-if="!localNodes.length"
        reason="还没有本地节点。"
        next="点击“添加节点”，手动填写服务器、协议和凭据。"
      />
      <div v-else class="mp-table-wrap">
        <el-table :data="localNodes" size="small">
          <el-table-column label="名称" min-width="180">
            <template #default="{ row }"><span class="mono">{{ row.display_name }}</span></template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ row.node_type || '—' }}</template>
          </el-table-column>
          <el-table-column label="协议" width="140">
            <template #default="{ row }">{{ protocolLabel(row.protocol) }}</template>
          </el-table-column>
          <el-table-column label="服务器" min-width="200">
            <template #default="{ row }">
              <span class="mono">{{ row.server }}:{{ row.port }}</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
          </el-table-column>
          <el-table-column label="测速状态" width="130">
            <template #default="{ row }">
              <StatusDot v-if="row.test_status === 'ok'" kind="ok"
                         :text="`成功 ${row.test_delay} ms`" />
              <StatusDot v-else-if="row.test_status === 'failed'" kind="danger" text="失败" />
              <span v-else style="color:var(--mp-muted)">未测速</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230">
            <template #default="{ row }">
              <el-button size="small" :loading="testingLocal === row.id"
                         @click="testLocal(row)">测速</el-button>
              <el-button size="small" @click="openLocalEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="removeLocal(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="localDialog" :title="localEditing ? '编辑本地节点' : '添加本地节点'"
               width="min(760px, 94vw)">
      <el-form :model="localForm" label-position="top">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="名称">
              <el-input v-model="localForm.name" placeholder="例如：香港-01" />
              <div class="mp-form-hint">
                最终标识：{{ localForm.name.trim() || '未命名' }}<template v-if="localForm.node_type"> ({{ localForm.node_type }})</template>
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="4">
            <el-form-item label="节点类型">
              <el-select v-model="localForm.node_type" style="width:100%" filterable
                         placeholder="选择类型">
                <el-option v-for="t in nodeTypes" :key="t" :value="t" :label="t" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="5">
            <el-form-item label="协议">
              <el-select v-model="localForm.protocol" style="width:100%" @change="onLocalProtocolChange">
                <el-option v-for="p in localProtocols" :key="p.value" :value="p.value" :label="p.label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="3">
            <el-form-item label="端口">
              <el-input-number v-model="localForm.port" :min="1" :max="65535" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="服务器地址">
              <el-input v-model="localForm.server" class="mono" placeholder="example.com 或 1.2.3.4" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="状态">
              <el-checkbox v-model="localForm.enabled">启用该节点</el-checkbox>
              <el-tooltip placement="top">
                <template #reference>
                  <span class="mp-info-dot">ⓘ</span>
                </template>
                停用后，该节点保留在面板中，但不会写入最终生成的设备配置（YAML）里。
              </el-tooltip>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col v-for="field in visibleLocalFields" :key="field.key" :xs="24" :sm="12">
            <el-form-item :label="field.label + (field.required ? ' *' : '')">
              <el-select v-if="field.type === 'select'" v-model="localForm.params[field.key]"
                         style="width:100%">
                <el-option v-for="opt in field.options" :key="opt.value"
                           :value="opt.value" :label="opt.label" />
              </el-select>
              <el-switch v-else-if="field.type === 'switch'" v-model="localForm.params[field.key]" />
              <el-input-number v-else-if="field.type === 'number'"
                               v-model="localForm.params[field.key]"
                               :min="field.min ?? 0" :max="field.max ?? 65535"
                               style="width:100%" />
              <el-input v-else-if="field.type === 'password'"
                        v-model="localForm.params[field.key]" type="password" show-password />
              <el-input v-else v-model="localForm.params[field.key]"
                        :placeholder="field.placeholder || ''" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="高级 YAML（可选，补充当前表单未覆盖的字段）">
          <el-input v-model="localForm.extra_yaml" type="textarea" :rows="4" class="mono" />
          <div class="mp-form-hint">不能覆盖 name / type / server / port；协议差异较大的字段可在这里补充。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="localDialog = false">取消</el-button>
        <el-button type="primary" :loading="localSaving" @click="saveLocal">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialog" :title="editing ? '编辑订阅来源' : '添加订阅来源'"
               width="min(560px, 94vw)">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如：XX机场" />
        </el-form-item>
        <el-form-item :label="editing ? '订阅地址（留空表示不修改）' : '订阅地址'">
          <el-input v-model="form.url" type="password" show-password
                    :placeholder="editing ? 'https://…（留空表示不修改）' : 'https://…'"
                    autocomplete="off" />
          <div v-if="editing" class="mp-form-hint">
            <el-button link type="primary" size="small" @click="toggleRevealUrl">
              {{ revealedUrl ? '隐藏原文' : '查看原文' }}
            </el-button>
            <span>订阅地址含访问凭据，请勿外传。</span>
          </div>
          <el-input v-if="revealedUrl" :model-value="revealedUrl" readonly
                    class="mono" style="margin-top:6px">
            <template #append>
              <el-button @click="copyRevealed">复制</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="过滤正则（可选，过滤套餐提示等无效节点）">
          <el-input v-model="form.filter" class="mono" placeholder="(?i)^(?!.*(?:剩余|到期|官网)).+$" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24"
                  :sm="(form.auto_fetch && form.auto_test) ? 8 : ((form.auto_fetch || form.auto_test) ? 12 : 24)">
            <el-form-item label="抓取 UA">
              <el-input v-model="form.ua" />
            </el-form-item>
          </el-col>
          <el-col v-if="form.auto_fetch" :xs="24" :sm="form.auto_test ? 8 : 12">
            <el-form-item label="抓取间隔">
              <el-input-number v-model="form.interval" :min="600" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col v-if="form.auto_test" :xs="24" :sm="form.auto_fetch ? 8 : 12">
            <el-form-item label="测速间隔">
              <el-input-number v-model="form.test_interval" :min="0" :max="604800" style="width:100%" />
            </el-form-item>
            <el-form-item label="客户端更新间隔">
              <el-input-number v-model="form.client_interval" :min="0" :max="604800" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="mp-form-hint" style="margin:-6px 0 14px">
          {{ intervalHint }}
        </div>
        <el-form-item>
          <el-checkbox v-model="form.auto_fetch">
            自动抓取（关闭后只使用本地快照，定时抓取与一键抓取都会跳过该来源）
          </el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.auto_test">
            自动测速（关闭后仍可一键测速或对单条来源手动测速）
          </el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.enabled">启用（停用后不进入构建，也不向设备分发）</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.filter_unavailable">
            只分发可用节点（测速失败的节点不下发；重新抓取后需重新测速）
          </el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.allow_private">
            允许访问内网地址（仅订阅确位于内网时开启，存在 SSRF 风险）
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="intervalDialog" title="批量修改间隔"
               width="min(480px, 94vw)">
      <p class="mp-dialog-desc">
        将选中的 {{ selected.length }} 个节点来源的间隔统一修改。
        服务端按抓取间隔自动更新快照；测速间隔控制自动测速，0 表示不自动测速。
        客户端更新间隔写进产物的 provider 条目，客户端按它拉取节点子资源；0 表示跟随抓取间隔。
      </p>
      <p style="font-size:13px;margin:0 0 6px">抓取间隔（秒）</p>
      <el-input-number v-model="batchInterval" :min="600" :max="604800" style="width:100%" />
      <div class="mp-preset-row">
        <el-button v-for="p in INTERVAL_PRESETS" :key="p.value" size="small"
                   :type="batchInterval === p.value ? 'primary' : 'default'"
                   @click="batchInterval = p.value">{{ p.label }}</el-button>
      </div>
      <p style="font-size:13px;margin:14px 0 6px">测速间隔（秒，0 = 不自动测速）</p>
      <el-input-number v-model="batchTestInterval" :min="0" :max="604800" style="width:100%" />
      <template #footer>
        <el-button @click="intervalDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingInterval" @click="saveBatchInterval">应用</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="urlDialog" :title="urlCopied ? 'URL 已复制' : 'URL 复制失败'"
               width="min(620px, 94vw)">
      <p class="mp-dialog-desc">
        {{ urlCopied ? '已复制以下节点来源订阅地址：' : '自动复制失败，请手动选择下面的 URL：' }}
      </p>
      <el-input :model-value="urlContent" type="textarea" :rows="3" readonly class="mono" />
    </el-dialog>

    <BatchResultDialog
      v-model:visible="blockedVisible"
      title="部分节点来源未删除"
      :summary="`已删除 ${deletedCount} 项；${blockedItems.length} 项因仍被引用而保留`"
      :items="blockedItems"
    />

    <el-drawer v-model="nodesDrawer" :title="`节点列表 · ${nodesSource?.name || ''}`"
               size="min(520px, 92vw)">
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin-top:0">
        仅显示节点名称、协议与测速结果，凭据不展示。共 {{ nodesSource?.nodes?.length ?? 0 }} 个节点。
        测速口径：从本服务器经节点请求 generate_204，衡量连通性与延迟，不等于带宽或解锁能力。
      </p>
      <el-table :data="nodesSource?.nodes || []" size="small" max-height="70vh">
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="type" label="协议" width="100" />
        <el-table-column label="测速状态" width="110">
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { confirmBox } from '../confirm'
import { api } from '../api'
import { useMobile } from '../mobile'
import { uploadCore } from '../core'
import StatusDot from '../components/StatusDot.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import ErrorState from '../components/ErrorState.vue'
import BatchResultDialog from '../components/BatchResultDialog.vue'
import { fmtTime, shortSha, sourceStatus } from '../format'

const INTERVAL_PRESETS = [
  { label: '15 分钟', value: 900 },
  { label: '1 小时', value: 3600 },
  { label: '6 小时', value: 21600 },
  { label: '1 天', value: 86400 },
  { label: '7 天', value: 604800 },
]

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
const revealedUrl = ref('')
const localNodes = ref([])
const testingLocal = ref(0)
const localSchema = ref({ protocols: [], node_types: [] })
const localDialog = ref(false)
const localSaving = ref(false)
const localEditing = ref(null)
const localForm = reactive({
  name: '', node_type: '本地', protocol: 'ss', server: '', port: 8388,
  params: {}, extra_yaml: '', enabled: true,
})
const nodesDrawer = ref(false)
const nodesSource = ref(null)
const core = ref(null)
const installingCore = ref(false)
const tableRef = ref(null)
const selected = ref([])
const batchRefreshing = ref(false)
const refreshDone = ref(0)
const refreshTotal = ref(0)
const batchTesting = ref(false)
const testDone = ref(0)
const testTotal = ref(0)
const intervalDialog = ref(false)
const savingInterval = ref(false)
const batchInterval = ref(21600)
const batchTestInterval = ref(21600)
const blockedVisible = ref(false)
const blockedItems = ref([])
const deletedCount = ref(0)
const urlDialog = ref(false)
const urlContent = ref('')
const urlCopied = ref(false)

const emptyForm = () => ({
  name: '', url: '', enabled: true, filter: '', ua: 'Stash',
  interval: 21600, test_interval: 21600, client_interval: 0,
  auto_fetch: true, auto_test: true,
  allow_private: false, filter_unavailable: false,
})
const form = reactive(emptyForm())

const intervalHint = computed(() => {
  if (form.auto_fetch && form.auto_test) {
    return '抓取与测速间隔单位为秒；测速间隔填 0 也会关闭自动测速。'
  }
  if (form.auto_fetch) {
    return '抓取间隔单位为秒；已关闭自动测速，仍可一键测速或对单条来源手动测速。'
  }
  if (form.auto_test) {
    return '已关闭自动抓取，只使用本地快照；测速按测速间隔自动执行。'
  }
  return '已关闭自动抓取与自动测速；只使用本地快照，仍可一键测速或单条手动测速。'
})

const localProtocols = computed(() => localSchema.value.protocols || [])
const nodeTypes = computed(() => localSchema.value.node_types || [])
const activeLocalProtocol = computed(() =>
  localProtocols.value.find((p) => p.value === localForm.protocol))
const visibleLocalFields = computed(() => {
  const fields = activeLocalProtocol.value?.fields || []
  return fields.filter((field) => {
    if (!field.show_if) return true
    return (field.show_if.in || []).includes(localForm.params[field.show_if.key])
  })
})

function protocolLabel(protocol) {
  return localProtocols.value.find((p) => p.value === protocol)?.label || protocol
}

function applyLocalDefaults(protocol, resetPort = false) {
  const spec = localProtocols.value.find((p) => p.value === protocol)
  if (!spec) return
  const defaults = {}
  for (const field of spec.fields || []) {
    if ('default' in field) defaults[field.key] = field.default
  }
  localForm.params = defaults
  if (resetPort && spec.default_port) localForm.port = spec.default_port
}

function onLocalProtocolChange(protocol) {
  applyLocalDefaults(protocol, true)
}

function onPageChange({ page: p, limit: l }) {
  page.value = p
  limit.value = l
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [paged, coreStatus, nodes, schema] = await Promise.all([
      api(`/api/v1/sources/page?limit=${limit.value}&offset=${(page.value - 1) * limit.value}`),
      api('/api/v1/core/status'),
      api('/api/v1/local-nodes'), api('/api/v1/local-nodes/schema'),
    ])
    rows.value = paged.items
    total.value = paged.total
    core.value = coreStatus
    localNodes.value = nodes
    localSchema.value = schema
    if (!localForm.name && !localForm.server && !Object.keys(localForm.params).length) {
      const first = schema.protocols?.[0]?.value || 'ss'
      localForm.protocol = first
      applyLocalDefaults(first, true)
    }
  } catch (e) {
    error.value = e.message
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
    error.value = e.message
    ElMessage.error(e.message)
  } finally {
    installingCore.value = false
  }
}

async function onUploadCore(file) {
  installingCore.value = true
  try {
    const result = await uploadCore(file.raw)
    ElMessage.success(`核心已安装：${result.version}`)
    core.value = await api('/api/v1/core/status')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    installingCore.value = false
  }
}

async function testRow(row, silent = false) {
  row._testing = true
  try {
    const updated = await api(`/api/v1/sources/${row.id}/test`, { method: 'POST' })
    Object.assign(row, updated)
    if (!silent) {
      ElMessage.success(`测速完成：${updated.tested_ok} 可用 / ${updated.tested_failed} 不可用`)
    }
    return true
  } catch (e) {
    if (!silent) ElMessage.error(e.message)
    return false
  } finally {
    row._testing = false
  }
}

async function testNodes(row) {
  await testRow(row)
}

async function testMany(list) {
  if (batchTesting.value || batchRefreshing.value) return
  if (core.value && !core.value.available) {
    return ElMessage.warning('测速核心未安装，请先在线安装或本地上传')
  }
  const targets = (list || []).filter(
    (row) => row && row.node_count !== null && row.node_count !== undefined,
  )
  if (!targets.length) {
    return ElMessage.info('没有可测速的节点来源，请先抓取快照')
  }
  batchTesting.value = true
  testDone.value = 0
  testTotal.value = targets.length
  let ok = 0
  let failed = 0
  try {
    // 顺序执行，避免同时启动多个 Mihomo 核心
    for (const row of targets) {
      if (await testRow(row, true)) ok += 1
      else failed += 1
      testDone.value += 1
    }
    if (failed) {
      ElMessage.warning(`测速完成：${ok} 个来源成功，${failed} 个失败`)
    } else {
      ElMessage.success(`测速完成：${ok} 个来源全部成功`)
    }
  } finally {
    batchTesting.value = false
    await load()
  }
}

function onSelectionChange(selection) {
  selected.value = selection
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selected.value = []
}

function openEdit(row) {
  editing.value = row || null
  revealedUrl.value = '' 
  Object.assign(form, emptyForm(), row ? {
    name: row.name, url: '', enabled: row.enabled, filter: row.filter,
    ua: row.ua, interval: row.interval, test_interval: row.test_interval,
    client_interval: row.client_interval,
    auto_fetch: row.auto_fetch !== false,
    auto_test: row.auto_test !== false,
    allow_private: row.allow_private,
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

async function refreshRow(row, silent = false) {
  row._refreshing = true
  try {
    const updated = await api(`/api/v1/sources/${row.id}/refresh`, { method: 'POST' })
    Object.assign(row, updated)
    if (!silent) ElMessage.success(`抓取成功：${updated.node_count} 个节点`)
    return true
  } catch (e) {
    if (!silent) ElMessage.error(e.message)
    return false
  } finally {
    row._refreshing = false
  }
}

async function refresh(row) {
  if (!await refreshRow(row)) await load()
}

async function refreshMany(list) {
  if (batchRefreshing.value || batchTesting.value) return
  const all = (list || []).filter(Boolean)
  const targets = all.filter((row) => row.auto_fetch !== false)
  const skipped = all.length - targets.length
  if (!targets.length) {
    return ElMessage.info(skipped
      ? '选中的来源都已关闭自动抓取，只使用本地快照'
      : '没有可抓取的节点来源')
  }
  batchRefreshing.value = true
  refreshDone.value = 0
  refreshTotal.value = targets.length
  const queue = [...targets]
  let ok = 0
  let failed = 0
  const worker = async () => {
    while (queue.length) {
      const row = queue.shift()
      if (await refreshRow(row, true)) ok += 1
      else failed += 1
      refreshDone.value += 1
    }
  }
  try {
    await Promise.all(
      Array.from({ length: Math.min(3, targets.length) }, () => worker()),
    )
    const skippedText = skipped ? `，跳过 ${skipped} 个仅本地快照来源` : ''
    if (failed) {
      ElMessage.warning(
        `抓取完成：${ok} 个成功，${failed} 个失败（失败来源保留最近成功快照）${skippedText}`,
      )
    } else {
      ElMessage.success(`抓取完成：${ok} 个来源全部成功${skippedText}`)
    }
  } finally {
    batchRefreshing.value = false
    await load()
  }
}

function openBatchInterval() {
  if (!selected.value.length) return
  batchInterval.value = selected.value[0].interval || 21600
  batchTestInterval.value = selected.value[0].test_interval ?? 21600
  intervalDialog.value = true
}

async function saveBatchInterval() {
  if (!selected.value.length) return
  savingInterval.value = true
  try {
    const ids = selected.value.map((r) => r.id)
    const resp = await api('/api/v1/sources/batch', {
      method: 'PATCH',
      body: {
        ids, interval: batchInterval.value,
        test_interval: batchTestInterval.value,
      },
    })
    intervalDialog.value = false
    ElMessage.success(`已更新 ${resp.updated} 个节点来源的间隔`)
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingInterval.value = false
  }
}

async function remove(row) {
  if (!await confirmBox(
    `删除节点来源 “${row.name}”？删除前会校验策略组引用；历史构建不受影响，新构建不再包含该来源。`,
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

async function removeSelected() {
  if (!selected.value.length) return
  if (!await confirmBox(
    `删除选中的 ${selected.value.length} 个节点来源？删除前会逐个校验策略组引用，`
    + '仍被引用的来源会保留并列出原因。',
    '批量删除节点来源', { type: 'warning', confirmButtonText: '删除' },
  )) return
  try {
    const ids = selected.value.map((r) => r.id)
    const resp = await api('/api/v1/sources/batch/delete', {
      method: 'POST', body: { ids },
    })
    deletedCount.value = resp.deleted.length
    blockedItems.value = resp.blocked
    if (resp.blocked.length) {
      blockedVisible.value = true
    } else {
      ElMessage.success(`已删除 ${resp.deleted.length} 个节点来源`)
    }
    clearSelection()
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function toggleRevealUrl() {
  if (revealedUrl.value) {
    revealedUrl.value = ''
    return
  }
  if (!editing.value) return
  try {
    const data = await api(`/api/v1/sources/${editing.value.id}/reveal`, { method: 'POST' })
    revealedUrl.value = data.url
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function copyRevealed() {
  try {
    await navigator.clipboard.writeText(revealedUrl.value)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function testLocal(row) {
  testingLocal.value = row.id
  try {
    const res = await api(`/api/v1/local-nodes/${row.id}/test`, { method: 'POST' })
    const item = localNodes.value.find((n) => n.id === row.id)
    if (item) {
      item.test_status = res.status
      item.test_delay = res.delay
      item.tested_at = res.tested_at
    }
    if (res.ok) ElMessage.success(`节点测速通过（${res.delay} ms）`)
    else ElMessage.warning('节点测速失败：无法通过该节点访问测试地址')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    testingLocal.value = 0
  }
}

async function copyUrl(row) {
  try {
    const data = await api(`/api/v1/sources/${row.id}/reveal`, { method: 'POST' })
    urlContent.value = data.url
    urlCopied.value = false
    try {
      await navigator.clipboard.writeText(data.url)
      urlCopied.value = true
    } catch {
      try {
        const el = document.createElement('textarea')
        el.value = data.url
        document.body.appendChild(el)
        el.select()
        urlCopied.value = document.execCommand('copy')
        el.remove()
      } catch {
        urlCopied.value = false
      }
    }
    urlDialog.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openLocalEdit(row) {
  localEditing.value = row || null
  if (row) {
    Object.assign(localForm, {
      name: row.name, node_type: row.node_type || '本地',
      protocol: row.protocol, server: row.server, port: row.port,
      params: { ...row.params }, extra_yaml: row.extra_yaml, enabled: row.enabled,
    })
  } else {
    const first = localProtocols.value[0]?.value || 'ss'
    Object.assign(localForm, {
      name: '', node_type: localSchema.value.default_node_type || '本地',
      protocol: first, server: '', port: 0,
      params: {}, extra_yaml: '', enabled: true,
    })
    applyLocalDefaults(first, true)
  }
  localDialog.value = true
}

async function saveLocal() {
  if (!localForm.name.trim()) return ElMessage.warning('请填写名称')
  if (!localForm.server.trim()) return ElMessage.warning('请填写服务器地址')
  localSaving.value = true
  try {
    const body = {
      name: localForm.name.trim(),
      node_type: localForm.node_type || '',
      protocol: localForm.protocol,
      server: localForm.server.trim(),
      port: localForm.port,
      params: { ...localForm.params },
      extra_yaml: localForm.extra_yaml,
      enabled: localForm.enabled,
    }
    if (localEditing.value) {
      await api(`/api/v1/local-nodes/${localEditing.value.id}`, { method: 'PUT', body })
    } else {
      await api('/api/v1/local-nodes', { method: 'POST', body })
    }
    localDialog.value = false
    ElMessage.success('已保存')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    localSaving.value = false
  }
}

async function removeLocal(row) {
  if (!await confirmBox(
    `删除本地节点 “${row.display_name}”？被策略组引用时不会删除。`,
    '删除本地节点', { type: 'warning' },
  )) return
  try {
    await api(`/api/v1/local-nodes/${row.id}`, { method: 'DELETE' })
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
</style>
