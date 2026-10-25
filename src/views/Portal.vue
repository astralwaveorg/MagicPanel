<template>
  <div class="pt-page">
    <!-- PIN 门禁 -->
    <div v-if="!data" class="pt-gate">
      <div class="pt-gate-card" :class="{ shake: shaking }">
        <img class="pt-gate-logo" src="/logo.svg" alt="MagicPanel">
        <div class="pt-logo">MagicPanel</div>
        <p class="pt-gate-desc">输入 PIN（4 位；历史 6 位仍可用）查看订阅与资源</p>
        <!-- 用 form 包起来：回车即提交，浏览器也能把密码框和表单关联起来 -->
        <form class="pt-pin-form" @submit.prevent="submitPin">
          <input
            ref="pinInput"
            v-model="pin"
            class="pt-pin"
            type="password"
            inputmode="numeric"
            pattern="\d{4}"
            maxlength="6"
            autocomplete="off"
            placeholder="····"
            :disabled="locked"
            @input="onPinInput"
          >
          <button type="submit" class="pt-pin-submit" :disabled="locked || pin.length < 4">
            进入
          </button>
        </form>
        <p v-if="gateError" class="pt-gate-error">{{ gateError }}</p>
        <p v-if="locked" class="pt-gate-error">已锁定，{{ lockRemain }} 秒后重试</p>
        <button class="pt-gate-login" @click="goLogin">维护者登录</button>
      </div>
    </div>

    <!-- 内容页 -->
    <template v-else>
      <header class="pt-hero">
        <div class="pt-hero-inner">
          <div class="pt-hero-top">
            <span class="pt-hero-brand">
              <img class="pt-hero-logo" src="/logo.svg" alt="">MagicPanel
            </span>
            <h1 class="pt-hero-title">订阅中心</h1>
            <button v-if="isMaintainer" class="pt-exit" @click="goAdmin">管理后台</button>
            <button v-else class="pt-exit" @click="exitPortal">退出查看</button>
          </div>
          <form class="pt-search" @submit.prevent="doSearch">
            <div class="pt-search-box">
              <input
                v-model="query"
                placeholder="搜索订阅、规则、客户端…"
                aria-label="搜索"
              >
              <button
                v-if="query"
                type="button"
                class="pt-search-clear"
                aria-label="清空搜索"
                @click="clearSearch"
              >×</button>
            </div>
            <button class="pt-search-btn" type="submit">搜索</button>
          </form>
          <p class="pt-hero-sub">
            {{ devices.length }} 台设备 · {{ data.rules.length }} 条个人规则 ·
            {{ data.rule_providers.length }} 个规则来源 ·
            {{ releaseText('production') }} · {{ releaseText('testing') }}
          </p>
        </div>
      </header>

      <main class="pt-main">
        <!-- 核心配置 -->
        <section v-if="engineGroups.length">
          <div class="pt-sec-head">
            <h2 class="pt-sec-title">核心配置</h2>
            <div class="pt-chips">
              <button
                v-for="p in platformFilters"
                :key="p.key"
                class="pt-chip"
                :data-platform="p.key"
                :class="{ active: platformFilter === p.key, empty: !p.count }"
                :aria-pressed="platformFilter === p.key"
                :title="platformFilter === p.key
                  ? '取消筛选'
                  : (p.count ? `只看 ${p.label} 设备（${p.count} 台）` : `${p.label}：暂无设备`)"
                @click="togglePlatform(p.key)"
              >
                <span class="pt-chip-dot"></span>{{ p.label }}
              </button>
            </div>
          </div>
          <p v-if="platformFilter && !devices.length" class="pt-empty">
            {{ platformLabel(platformFilter) }} 暂无订阅设备
          </p>
          <template v-for="g in engineGroups" :key="g.engine">
            <div v-if="g.devices.length || !platformFilter" class="pt-engine">
              <h3 class="pt-engine-title">{{ g.label }}</h3>
              <div class="pt-grid">
                <article v-for="d in g.devices" :key="d.name" class="pt-card" :data-platform="d.platform">
                  <div class="pt-card-head">
                    <span class="pt-card-name">{{ cardTitle(d) }}</span>
                    <span class="pt-tag" :data-env="d.env">
                      {{ d.env === 'production' ? '生产环境' : '测试环境' }}
                    </span>
                  </div>
                  <p class="pt-card-meta">
                    <span class="pt-plat">{{ platformLabel(d.platform) }}</span> · {{ d.target_name }}
                    <template v-if="hasOwnProfile(d)">
                      · 设备：{{ d.display_name }}
                    </template>
                  </p>
                  <div class="pt-card-actions">
                    <button
                      class="pt-btn primary"
                      :disabled="!d.subscription_url"
                      @click="copy(d.subscription_url, 'dev-' + d.name)"
                    >{{ copied === 'dev-' + d.name ? '已复制' : '复制地址' }}</button>
                    <a
                      v-if="d.subscription_url"
                      class="pt-btn"
                      :href="installUrl(d)"
                    >一键导入</a>
                    <button
                      class="pt-btn"
                      :disabled="!d.subscription_url"
                      @click="showQr(d)"
                    >二维码</button>
                  </div>
                </article>
              </div>
            </div>
          </template>
        </section>
        <p v-else-if="!appliedQuery" class="pt-empty">
          暂无订阅地址：设备尚未创建或尚未发布版本，请联系维护者在管理后台完成配置与发布。
        </p>

        <!-- 客户端资源 -->
        <section v-if="clients.length">
          <h2 class="pt-sec-title">客户端资源</h2>
          <div class="pt-grid">
            <a
              v-for="c in clients" :key="c.name"
              class="pt-card pt-link-card" :href="c.url" target="_blank" rel="noopener"
            >
              <div class="pt-card-head">
                <span class="pt-card-name">{{ c.name }}</span>
                <span class="pt-tag soft">{{ c.platform }}</span>
              </div>
              <p class="pt-card-note">{{ c.desc }}</p>
            </a>
          </div>
        </section>

        <!-- 分流规则 -->
        <section v-if="rules.length || (!appliedQuery && ruleTotal)">
          <div class="pt-sec-head">
            <h2 class="pt-sec-title">分流规则<small>个人维护，点击复制</small></h2>
          </div>
          <p class="pt-prov-summary">{{ ruleSummary }}</p>
          <div v-for="g in ruleGroups" :key="g.key" class="pt-prov-group">
            <button class="pt-prov-group-head" @click="toggleGroup(g.key)">
              <span class="pt-prov-group-name">{{ g.label }}</span>
              <span class="pt-prov-group-meta">{{ g.count }} 条</span>
              <span class="pt-prov-group-caret">{{ groupOpen(g.key) ? '▾' : '▸' }}</span>
            </button>
            <ul v-if="groupOpen(g.key)" class="pt-rules">
              <li v-for="it in g.items" :key="it.i" @click="copyRule(it.r, it.i)">
                <span class="pt-rule-line">{{ ruleLine(it.r) }}</span>
                <span class="pt-rule-note">{{ copied === 'rule-' + it.i ? '已复制' : (it.r.note || '') }}</span>
              </li>
            </ul>
          </div>
        </section>

        <!-- 规则来源 -->
        <section v-if="ruleProviders.length">
          <div class="pt-sec-head">
            <h2 class="pt-sec-title">规则来源<small>已随配置下发</small></h2>
            <div class="pt-chips">
              <button
                v-for="d in PROVIDER_DIMENSIONS"
                :key="d.key"
                class="pt-chip pt-chip-toggle"
                :class="{ active: providerDimension === d.key }"
                :aria-pressed="providerDimension === d.key"
                @click="providerDimension = d.key"
              >{{ d.label }}</button>
            </div>
          </div>
          <p class="pt-prov-summary">{{ providerSummary }}</p>
          <div v-for="g in providerGroups" :key="g.key" class="pt-prov-group">
            <button class="pt-prov-group-head" @click="toggleGroup(providerGroupKey(g))">
              <span class="pt-prov-group-name">{{ g.label }}</span>
              <span class="pt-prov-group-meta">{{ providerGroupMeta(g) }}</span>
              <span class="pt-prov-group-caret">{{ groupOpen(providerGroupKey(g)) ? '▾' : '▸' }}</span>
            </button>
            <ul v-if="groupOpen(providerGroupKey(g))" class="pt-prov-list">
              <li v-for="p in g.items" :key="p.name" class="pt-prov-row">
                <div class="pt-prov-main">
                  <span class="pt-prov-name">{{ p.name }}</span>
                  <span v-if="p.desc" class="pt-prov-desc">{{ p.desc }}</span>
                </div>
                <span class="pt-prov-meta">{{ providerMeta(p) }}</span>
                <span class="pt-prov-kind" :data-kind="p.kind">
                  {{ p.kind === 'inline' ? '内联' : '远程' }}
                </span>
                <div class="pt-prov-actions">
                  <button
                    class="pt-mini"
                    :disabled="!p.url"
                    @click="copy(p.url, 'prov-' + p.name)"
                  >{{ copied === 'prov-' + p.name ? '已复制' : '复制地址' }}</button>
                  <button class="pt-mini" @click="openProvider(p)">预览</button>
                </div>
              </li>
            </ul>
          </div>
        </section>

        <!-- 功能模块 -->
        <section v-if="snippetGroups.length">
          <div class="pt-sec-head">
            <h2 class="pt-sec-title">功能模块<small>已随配置下发</small></h2>
          </div>
          <p class="pt-prov-summary">{{ snippetSummary }}</p>
          <div v-for="g in snippetGroups" :key="g.category" class="pt-prov-group">
            <button class="pt-prov-group-head" @click="toggleGroup(snippetGroupKey(g))">
              <span class="pt-prov-group-name">{{ g.label }}</span>
              <span class="pt-prov-group-meta">{{ g.items.length }} 个</span>
              <span class="pt-prov-group-caret">{{ groupOpen(snippetGroupKey(g)) ? '▾' : '▸' }}</span>
            </button>
            <div v-if="groupOpen(snippetGroupKey(g))" class="pt-snippet-group">
              <span v-for="s in g.items" :key="s.name" class="pt-chip" :title="s.note">
                {{ s.name }}<i v-if="s.engine !== 'all'">{{ engineLabel(s.engine) }}</i>
              </span>
            </div>
          </div>
        </section>

        <!-- 导入指引 -->
        <section v-if="guides.length">
          <h2 class="pt-sec-title">导入指引</h2>
          <div v-for="g in guides" :key="g.platform" class="pt-guide">
            <div class="pt-guide-title">{{ g.platform }}</div>
            <ol>
              <li v-for="(step, i) in g.steps" :key="i">{{ step }}</li>
            </ol>
          </div>
        </section>

        <footer class="pt-footer">
          <a href="https://www.gstatic.com/generate_204" target="_blank" rel="noopener">
            连通性自检
          </a>
          <span>·</span>
          <span>链接拉取无需额外鉴权，请仅发给受信设备</span>
        </footer>

        <div v-if="appliedQuery && !hasAnyResult" class="pt-noresult">
          没有匹配 “{{ appliedQuery }}” 的内容
        </div>
      </main>

      <!-- 二维码弹层 -->
      <div v-if="qrUrl" class="pt-modal" @click.self="closeQr">
        <div class="pt-modal-card">
          <p class="pt-modal-title">{{ qrDevice }}</p>
          <img :src="qrUrl" alt="订阅二维码">
          <p class="pt-url">{{ qrText }}</p>
          <button class="pt-btn" @click="closeQr">关闭</button>
        </div>
      </div>

      <!-- 规则来源详情 -->
      <div v-if="providerDetail" class="pt-modal" @click.self="closeProvider">
        <div class="pt-modal-card wide">
          <p class="pt-modal-title">{{ providerDetail.name }}</p>
          <p v-if="providerDetail.desc" class="pt-detail-desc">{{ providerDetail.desc }}</p>
          <dl class="pt-detail-grid">
            <div><dt>行为</dt><dd>{{ behaviorLabel(providerDetail.behavior) }}</dd></div>
            <div><dt>格式</dt><dd>{{ formatLabel(providerDetail.format) }}</dd></div>
            <div><dt>条目</dt><dd>{{ providerDetail.rule_count || '—' }}</dd></div>
            <div><dt>大小</dt><dd>{{ sizeText(providerDetail.size) }}</dd></div>
            <div><dt>抓取</dt><dd>{{ providerDetail.last_status || '—' }}</dd></div>
            <div><dt>最近抓取</dt><dd>{{ timeText(providerDetail.last_fetched_at) }}</dd></div>
            <div><dt>面板抓取间隔</dt><dd>{{ durationText(providerDetail.interval) }}</dd></div>
            <div><dt>客户端间隔</dt><dd>{{ providerDetail.client_interval ? durationText(providerDetail.client_interval) : '跟随面板' }}</dd></div>
          </dl>
          <p
            class="pt-detail-url"
            :class="{ empty: !providerDetail.url }"
            @click="providerDetail.url && copy(providerDetail.url, 'detail-url')"
          >{{ providerDetail.url || '面板内联内容，没有上游地址' }}</p>
          <pre class="pt-detail-preview">{{ providerDetail.preview || '二进制规则集，没有可读文本内容' }}</pre>
          <p v-if="providerDetail.truncated" class="pt-detail-note">
            仅显示前 120 行，共 {{ providerDetail.total_lines }} 行
          </p>
          <div class="pt-detail-actions">
            <button
              class="pt-btn"
              :disabled="!providerDetail.url"
              @click="copy(providerDetail.url, 'detail-url')"
            >{{ copied === 'detail-url' ? '已复制' : '复制地址' }}</button>
            <button class="pt-btn" @click="closeProvider">关闭</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import QRCode from 'qrcode'
import { api } from '../api'

const GATE_TITLE = 'MagicPanel - 订阅配置服务中心'
const CONTENT_TITLE = '订阅中心 · MagicPanel'

const router = useRouter()
const PIN_KEY = 'mp-portal-pin'

const pin = ref('')
const data = ref(null)
const isMaintainer = ref(false)
const gateError = ref('')
const shaking = ref(false)
const locked = ref(false)
const lockRemain = ref(0)
// query 是输入框里的字，appliedQuery 是实际生效的搜索词（点按钮或回车才更新）
const query = ref('')
const appliedQuery = ref('')
const platformFilter = ref('')
const copied = ref('')
const pinInput = ref(null)
const qrUrl = ref('')
const qrText = ref('')
const qrDevice = ref('')
const qrCache = new Map()
let lockTimer = null

const CATEGORY_LABELS = {
  script: '脚本', rewrite: '复写', panel: '面板', dns: 'DNS', general: '通用',
}
const PLATFORM_LABELS = {
  ios: 'iOS', macos: 'macOS', tvos: 'tvOS', windows: 'Windows', android: 'Android',
  linux: 'Linux',
}
// 平台标签的固定排列顺序，保证两个引擎下的标签列一致
const PLATFORM_ORDER = ['ios', 'macos', 'tvos', 'windows', 'android', 'linux']
const ENGINE_LABELS = { stash: 'Stash', mihomo: 'Mihomo' }

const norm = (s) => (s || '').toLowerCase()
const hit = (...fields) => !appliedQuery.value
  || fields.some((f) => norm(f).includes(norm(appliedQuery.value)))
function doSearch() { appliedQuery.value = query.value }
function clearSearch() { query.value = ''; appliedQuery.value = '' }

const devices = computed(() =>
  (data.value?.devices || []).filter((d) =>
    (!platformFilter.value || d.platform === platformFilter.value)
    && hit(d.name, d.display_name, d.platform, d.target_name, d.note)))

const engineGroups = computed(() => {
  // 引擎分组基于**全部**设备，不受搜索与平台筛选影响——
  // 否则筛选后整个区块会消失，用户就没法切回别的平台了。
  const groups = {}
  for (const d of data.value?.devices || []) {
    const key = d.engine || 'other'
    ;(groups[key] ||= []).push(d)
  }
  return Object.entries(groups).map(([engine, list]) => ({
    engine,
    label: ENGINE_LABELS[engine] || engine,
    devices: list.filter((d) => devices.value.includes(d)),
  }))
})

// 平台标签固定列出全部支持的平台，包括当前还没有设备的（如 Linux），
// 标签不随筛选消失，用户随时能切回去。平台是跨引擎的统一概念，
// 点任意一个平台标签，Stash 与 Mihomo 两个引擎的设备一起筛。
const platformFilters = computed(() =>
  PLATFORM_ORDER.map((key) => ({
    key,
    label: PLATFORM_LABELS[key] || key,
    count: (data.value?.devices || []).filter((d) => d.platform === key).length,
  })))

// 平台筛选：点标签只看该平台，再点一次取消。两个引擎共用同一筛选状态——
// 平台是跨引擎的统一概念，点任意一个引擎的 iOS 都应该看到所有 iOS 设备。
function togglePlatform(key) {
  platformFilter.value = platformFilter.value === key ? '' : key
}

const clients = computed(() =>
  (data.value?.clients || []).filter((c) => hit(c.name, c.desc, c.platform)))

const rules = computed(() =>
  (data.value?.rules || []).filter((r) => hit(r.type, r.value, r.target, r.note)))

const ruleTotal = computed(() => data.value?.rules?.length || 0)

const ruleProviders = computed(() =>
  (data.value?.rule_providers || []).filter((p) =>
    hit(p.name, p.behavior, p.kind, p.format, p.origin, p.desc)))

// 首页的三个折叠区块（分流规则 / 规则来源 / 功能模块）共用一套展开状态：
// 默认全折叠，只记展开的分组 key。
const expanded = ref([])
function groupOpen(key) { return expanded.value.includes(key) }
function toggleGroup(key) {
  const i = expanded.value.indexOf(key)
  if (i >= 0) expanded.value.splice(i, 1)
  else expanded.value.push(key)
}

// 分流规则按目标策略组分组：规则本来就是「什么流量走哪组」，
// 同一个目标组的规则在产物里也是连续一块。
const ruleGroups = computed(() => {
  const map = new Map()
  rules.value.forEach((r, i) => {
    const key = r.target || '未指定目标'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push({ r, i })
  })
  return [...map.entries()].map(([key, items]) => ({
    key, label: key, count: items.length, items,
  }))
})

const ruleSummary = computed(() => {
  const list = rules.value
  const targets = new Set(list.map((r) => r.target).filter(Boolean)).size
  const fallback = list.filter((r) => ['MATCH', 'FINAL'].includes(r.type)).length
  const tail = fallback ? ` · 含 ${fallback} 条兜底` : ''
  return `${list.length} 条 · ${targets} 个目标${tail}`
})

// 规则来源分组：按行为（客户端语义）或按上游仓库（来源归属）都能看
const PROVIDER_DIMENSIONS = [
  { key: 'behavior', label: '按行为' },
  { key: 'origin', label: '按来源' },
]
const BEHAVIOR_LABELS = { domain: '域名', ipcidr: 'IP 段', classical: '混合' }
const FORMAT_LABELS = { yaml: 'YAML', mrs: 'MRS', text: 'Text' }
const BEHAVIOR_ORDER = ['domain', 'ipcidr', 'classical']
const providerDimension = ref('behavior')
const providerDetail = ref(null)

// 分组 key 带前缀，避免与其它区块撞名；换了分组维度也各记各的展开状态
function providerGroupKey(g) { return `prov:${providerDimension.value}:${g.key}` }
function snippetGroupKey(g) { return `snip:${g.category}` }

const providerGroups = computed(() => {
  const byBehavior = providerDimension.value === 'behavior'
  const map = new Map()
  for (const p of ruleProviders.value) {
    const key = byBehavior ? p.behavior : (p.origin || '其他来源')
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(p)
  }
  const groups = [...map.entries()].map(([key, items]) => ({
    key,
    label: byBehavior ? (BEHAVIOR_LABELS[key] || key) : key,
    items: items.slice().sort((a, b) => (b.rule_count || 0) - (a.rule_count || 0)),
    count: items.length,
    total: items.reduce((s, p) => s + (p.rule_count || 0), 0),
    // 二进制集合（MRS）数不出条目数，组标题别显示成「0 条」
    uncounted: items.filter((p) => !p.rule_count).length,
  }))
  if (byBehavior) {
    groups.sort((a, b) => BEHAVIOR_ORDER.indexOf(a.key) - BEHAVIOR_ORDER.indexOf(b.key))
  } else {
    groups.sort((a, b) => b.count - a.count)
  }
  return groups
})

const providerSummary = computed(() => {
  const list = ruleProviders.value
  const remote = list.filter((p) => p.kind !== 'inline').length
  const total = list.reduce((s, p) => s + (p.rule_count || 0), 0)
  const uncounted = list.filter((p) => !p.rule_count).length
  const kinds = BEHAVIOR_ORDER
    .map((b) => `${BEHAVIOR_LABELS[b]} ${list.filter((p) => p.behavior === b).length}`)
    .join(' · ')
  const tail = uncounted ? `共 ${total} 条（另有 ${uncounted} 个二进制集合未统计）` : `共 ${total} 条`
  return `${list.length} 个来源 · 远程 ${remote} · 内联 ${list.length - remote} · ${kinds} · ${tail}`
})

// 分组标题的条目数：整组都数不出来时别显示「0 条」
function providerGroupMeta(g) {
  if (g.total) return `${g.count} 个 · ${g.total} 条`
  if (g.uncounted) return `${g.count} 个 · 条数未统计`
  return `${g.count} 个`
}

function behaviorLabel(b) { return BEHAVIOR_LABELS[b] || b }
function formatLabel(f) { return FORMAT_LABELS[f] || f }

function providerMeta(p) {
  const parts = [behaviorLabel(p.behavior), formatLabel(p.format)]
  parts.push(p.rule_count ? `${p.rule_count} 条` : (p.format === 'mrs' ? '二进制' : '未统计'))
  parts.push(p.client_interval ? `客户端 ${durationText(p.client_interval)}` : '客户端跟随面板')
  return parts.join(' · ')
}

function durationText(sec) {
  if (!sec) return '—'
  if (sec % 86400 === 0) return `${sec / 86400} 天`
  if (sec % 3600 === 0) return `${sec / 3600} 小时`
  if (sec % 60 === 0) return `${sec / 60} 分钟`
  return `${sec} 秒`
}

function sizeText(n) {
  if (!n) return '—'
  if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}

// 后端给的是 ISO 时间，详情里只显示到分钟
function timeText(v) {
  if (!v) return '未抓取'
  const m = String(v).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
  return m ? `${m[1]} ${m[2]}` : String(v)
}

// 原始内容不进首屏数据，点预览时再按需拉
async function openProvider(p) {
  providerDetail.value = { name: p.name, desc: p.desc, preview: '加载中…' }
  try {
    const resp = await fetch('/api/v1/portal/provider-detail', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: p.name, pin: pin.value }),
    })
    if (!resp.ok) throw new Error('拉取失败')
    providerDetail.value = await resp.json()
  } catch {
    providerDetail.value = { name: p.name, desc: p.desc, preview: '拉取失败，请刷新页面重试' }
  }
}

function closeProvider() { providerDetail.value = null }

const snippetGroups = computed(() => {
  const groups = {}
  for (const s of data.value?.snippets || []) {
    if (!hit(s.name, s.note, s.category)) continue
    ;(groups[s.category] ||= []).push(s)
  }
  return Object.entries(groups).map(([category, items]) => ({
    category, label: CATEGORY_LABELS[category] || category, items,
  }))
})

const snippetSummary = computed(() => {
  const list = snippetGroups.value
  const total = list.reduce((s, g) => s + g.items.length, 0)
  return `${total} 个模块 · ${list.length} 类`
})

// 搜索时把命中的分组展开；清空搜索后回到默认折叠
watch(appliedQuery, (q) => {
  if (!q) { expanded.value = []; return }
  const keys = [
    ...ruleGroups.value.map((g) => g.key),
    ...providerGroups.value.map((g) => providerGroupKey(g)),
    ...snippetGroups.value.map((g) => snippetGroupKey(g)),
  ]
  for (const k of keys) if (!expanded.value.includes(k)) expanded.value.push(k)
})

const guides = computed(() => data.value?.guides || [])

const hasAnyResult = computed(() =>
  devices.value.length || clients.value.length || rules.value.length
  || ruleProviders.value.length || snippetGroups.value.length)

function platformLabel(p) { return PLATFORM_LABELS[p] || p }
function engineLabel(e) { return e === 'stash' ? 'Stash' : 'Mihomo' }
// 设备卡片标题：有独立配置文件时用文件名（去掉 .yaml），没有就用设备名。
// 文件名唯一，设备显示名可能重名；反过来设备名一眼可辨，所以两者分两行摆。
function hasOwnProfile(d) {
  return !!(d.display_name && d.display_name !== d.name)
}
function cardTitle(d) {
  return hasOwnProfile(d) ? d.name : (d.display_name || d.name)
}
// 头部摘要：当前生效的生产 / 测试版本
function releaseText(env) {
  const label = env === 'production' ? '生产版本' : '测试版本'
  const build = data.value?.release_state?.[env]
  return `${label} ${build ? `构建 #${build.id}` : '未发布'}`
}
function ruleLine(r) {
  if (['MATCH', 'FINAL'].includes(r.type)) return `MATCH,${r.target}`
  return `${r.type},${r.value},${r.target}${r.no_resolve ? ',no-resolve' : ''}`
}

async function copy(text, key) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    el.remove()
  }
  copied.value = key
  setTimeout(() => { if (copied.value === key) copied.value = '' }, 1600)
}

function copyRule(r, i) { copy(ruleLine(r), 'rule-' + i) }

// Stash 与 Mihomo/Clash 均支持 install-config URL Scheme 一键导入
function installUrl(d) {
  const scheme = d.engine === 'stash' ? 'stash' : 'clash'
  return `${scheme}://install-config?url=${encodeURIComponent(d.subscription_url)}`
}

async function showQr(d) {
  qrDevice.value = d.display_name || d.name
  qrText.value = d.subscription_url
  if (qrCache.has(d.subscription_url)) {
    qrUrl.value = qrCache.get(d.subscription_url)
    return
  }
  try {
    const url = await QRCode.toDataURL(d.subscription_url, { width: 440, margin: 1 })
    qrCache.set(d.subscription_url, url)
    qrUrl.value = url
  } catch {
    qrDevice.value = '二维码生成失败'
    qrText.value = ''
  }
}

function closeQr() { qrUrl.value = ''; qrText.value = ''; qrDevice.value = '' }

function startLockCountdown(seconds) {
  locked.value = true
  lockRemain.value = seconds
  clearInterval(lockTimer)
  lockTimer = setInterval(() => {
    lockRemain.value -= 1
    if (lockRemain.value <= 0) { locked.value = false; clearInterval(lockTimer) }
  }, 1000)
}

async function fetchData() {
  gateError.value = ''
  try {
    const resp = await fetch('/api/v1/portal/data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pin.value }),
    })
    // 未登录且未提供 PIN：停留在门禁页，不提示错误
    if (resp.status === 401) {
      pin.value = ''
      return
    }
    if (resp.status === 404) {
      gateError.value = 'Magic Panel 首页未启用，请联系维护者在后台设置 PIN'
      return
    }
    if (resp.status === 429) {
      startLockCountdown(600)
      return
    }
    const body = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      gateError.value = body.detail === 'PIN 不正确' ? 'PIN 不正确' : (body.detail || '加载失败')
      shaking.value = true
      setTimeout(() => { shaking.value = false }, 500)
      pin.value = ''
      return
    }
    if (pin.value) sessionStorage.setItem(PIN_KEY, pin.value)
    data.value = body
    document.title = CONTENT_TITLE
  } catch {
    gateError.value = '网络异常，请稍后重试'
  }
}

function submitPin() {
  if (pin.value.length >= 4) fetchData()
}

function onPinInput() {
  pin.value = pin.value.replace(/\D/g, '').slice(0, 6)
  // 4 位是当前规范；历史 6 位 PIN 仍然允许输入（散列照旧校验）
  if (pin.value.length === 4 || pin.value.length === 6) fetchData()
}

function exitPortal() {
  sessionStorage.removeItem(PIN_KEY)
  data.value = null
  pin.value = ''
  document.title = GATE_TITLE
  nextTick(() => pinInput.value?.focus())
}

function goLogin() { router.push('/admin/login') }
function goAdmin() { router.push('/admin') }

onMounted(async () => {
  // 已登录的维护者免 PIN 直接进入
  try {
    await api('/api/v1/auth/me')
    isMaintainer.value = true
  } catch { /* 未登录 */ }
  if (isMaintainer.value) {
    await fetchData()
  } else {
    const saved = sessionStorage.getItem(PIN_KEY)
    if (saved && /^\d{4}$/.test(saved)) {
      pin.value = saved
      await fetchData()
      if (!data.value) pin.value = ''
    }
  }
  if (!data.value) nextTick(() => pinInput.value?.focus())
})
</script>

<style scoped>
/* 首页自带深色视觉，不随后台主题切换 */
.pt-page {
  min-height: 100vh;
  background: #0b0e1a;
  color: #e8eaf2;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* PIN 门禁 */
.pt-gate {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(600px 400px at 20% 10%, rgba(88, 101, 242, 0.28), transparent),
    radial-gradient(500px 380px at 85% 80%, rgba(22, 163, 178, 0.22), transparent),
    #0b0e1a;
}
.pt-gate-card {
  width: 340px;
  max-width: 100%;
  text-align: center;
  padding: 40px 32px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(16px);
}
.pt-gate-card.shake { animation: pt-shake 0.45s ease; }
@keyframes pt-shake {
  0%, 100% { transform: translateX(0); }
  20%, 60% { transform: translateX(-8px); }
  40%, 80% { transform: translateX(8px); }
}
.pt-logo { font-size: 20px; font-weight: 700; letter-spacing: 1px; }
.pt-gate-logo { width: 56px; height: 56px; margin-bottom: 12px; }
.pt-gate-login {
  margin-top: 18px;
  padding: 8px 18px;
  font-size: 12.5px;
  color: #aab1c8;
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 8px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.pt-gate-login:hover { color: #fff; border-color: rgba(255, 255, 255, 0.45); }
.pt-gate-desc { color: #9aa0b5; font-size: 13px; margin: 10px 0 22px; }
.pt-pin {
  width: 180px;
  max-width: 100%;
  padding: 12px 0;
  text-align: center;
  font-size: 26px;
  letter-spacing: 14px;
  text-indent: 14px;
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  outline: none;
}
.pt-pin:focus { border-color: #6c7bff; box-shadow: 0 0 0 3px rgba(108, 123, 255, 0.25); }
.pt-gate-error { color: #ff7a72; font-size: 13px; margin: 14px 0 0; }

/* Hero */
.pt-hero {
  background:
    radial-gradient(700px 320px at 15% 0%, rgba(108, 123, 255, 0.35), transparent),
    radial-gradient(600px 300px at 90% 20%, rgba(34, 197, 183, 0.28), transparent),
    linear-gradient(180deg, #141834 0%, #0b0e1a 100%);
  padding: 16px 0 36px;
}
/* 横向内边距只在这里给，顶部与下方内容列左右严格对齐 */
.pt-hero-inner { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
.pt-hero-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.pt-hero-brand { font-weight: 700; letter-spacing: 1px; opacity: 0.9; display: inline-flex; align-items: center; gap: 8px; }
.pt-hero-logo { width: 22px; height: 22px; }
.pt-exit {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #c3c8dc;
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.pt-exit:hover { border-color: rgba(255, 255, 255, 0.5); color: #fff; }
/* 标题与品牌同一行，顶部整体收紧 */
.pt-hero h1.pt-hero-title {
  font-size: 18px;
  margin: 0;
  letter-spacing: 2px;
  font-weight: 600;
  opacity: 0.92;
  flex: 1;
  text-align: center;
}
/* 搜索框铺满内容列，右侧留出明确的搜索按钮 */
.pt-search {
  display: flex;
  gap: 10px;
  max-width: 100%;
  margin-top: 14px;
}
.pt-search-box { position: relative; flex: 1; min-width: 0; }
.pt-search input {
  width: 100%;
  padding: 11px 38px 11px 16px;
  font-size: 14px;
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 12px;
  outline: none;
}
.pt-search input:focus { border-color: #6c7bff; }
.pt-search input::placeholder { color: #6d7490; }
.pt-search-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.12);
  color: #aab1c8;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}
.pt-search-clear:hover { background: rgba(255, 255, 255, 0.22); color: #fff; }
.pt-search-btn {
  flex: none;
  padding: 0 24px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: linear-gradient(135deg, #6c7bff, #7c5cf0);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: filter 0.15s, transform 0.1s;
}
.pt-search-btn:hover { filter: brightness(1.12); }
.pt-search-btn:active { transform: translateY(1px); }
/* 统计信息放在搜索框下面 */
.pt-hero-sub { color: #9aa0b5; font-size: 12.5px; margin: 10px 0 0; }

/* 内容 */
.pt-main { max-width: 1080px; margin: -24px auto 0; padding: 0 20px 56px; }
.pt-sec-title {
  font-size: 17px;
  margin: 34px 0 14px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.pt-sec-title small { font-size: 12px; font-weight: 400; color: #79809a; }
/* 区块标题行：标题在左，右侧可以挂筛选标签 */
.pt-sec-head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin: 34px 0 14px;
}
.pt-sec-head .pt-sec-title { margin: 0; }
.pt-engine-title { font-size: 13px; color: #8f96b0; margin: 18px 0 10px; font-weight: 600; }

.pt-chips { display: flex; gap: 6px; flex-wrap: wrap; }

/* 平台色板：低饱和莫兰迪色系，颜色只出现在筛选标签、卡片侧条与平台文字三处 */
.pt-chip[data-platform='ios'] { --pc: #6ea8fe; }
.pt-chip[data-platform='android'] { --pc: #5fd08a; }
.pt-chip[data-platform='windows'] { --pc: #4fc3d9; }
.pt-chip[data-platform='macos'] { --pc: #a98bf0; }
.pt-chip[data-platform='tvos'] { --pc: #f0996a; }
.pt-chip[data-platform='linux'] { --pc: #d4b45a; }

.pt-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  line-height: 1.5;
  padding: 3px 10px;
  border-radius: 99px;
  white-space: nowrap;
  color: var(--pc);
  background: color-mix(in srgb, var(--pc) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--pc) 24%, transparent);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.pt-chip:hover { background: color-mix(in srgb, var(--pc) 20%, transparent); }
.pt-chip.active {
  background: color-mix(in srgb, var(--pc) 24%, transparent);
  border-color: color-mix(in srgb, var(--pc) 52%, transparent);
}
/* 当前没有设备的平台：标签保留但压暗，说明"支持但还没有" */
.pt-chip.empty { opacity: 0.4; }
.pt-chip.empty:hover { opacity: 0.7; }
.pt-chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--pc);
  opacity: 0.85;
}

.pt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.pt-card {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  padding: 16px 18px;
  backdrop-filter: blur(8px);
  animation: pt-rise 0.35s ease both;
  position: relative;
  overflow: hidden;
}
/* 卡片左侧的平台色条：不占布局宽度，用内阴影画 */
.pt-card[data-platform='ios'] { --pc: #6ea8fe; }
.pt-card[data-platform='android'] { --pc: #5fd08a; }
.pt-card[data-platform='windows'] { --pc: #4fc3d9; }
.pt-card[data-platform='macos'] { --pc: #a98bf0; }
.pt-card[data-platform='tvos'] { --pc: #f0996a; }
.pt-card[data-platform='linux'] { --pc: #d4b45a; }
.pt-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--pc, transparent);
  opacity: 0.7;
}
@keyframes pt-rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
.pt-link-card { text-decoration: none; color: inherit; transition: border-color 0.15s, transform 0.15s; display: block; }
.pt-link-card:hover { border-color: rgba(108, 123, 255, 0.6); transform: translateY(-2px); }
.pt-card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.pt-card-name { font-weight: 600; font-size: 15px; }
.pt-tag {
  font-size: 11px;
  padding: 2px 9px;
  border-radius: 99px;
  white-space: nowrap;
}
.pt-tag[data-env='production'] { background: rgba(63, 185, 128, 0.18); color: #4ade9d; }
.pt-tag[data-env='testing'] { background: rgba(250, 183, 82, 0.16); color: #f5c069; }
.pt-tag.soft { background: rgba(255, 255, 255, 0.1); color: #aab1c8; }
.pt-card-meta { color: #8f96b0; font-size: 12px; margin: 6px 0 0; }
.pt-plat { color: var(--pc, #8f96b0); }
.pt-card-note { color: #79809a; font-size: 12px; margin: 8px 0 0; }
.pt-url {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: #7e93c9;
  background: rgba(0, 0, 0, 0.28);
  border-radius: 8px;
  padding: 8px 10px;
  margin: 12px 0;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pt-card-actions { display: flex; gap: 10px; margin-top: 14px; }
.pt-btn {
  flex: 1;
  padding: 9px 0;
  font-size: 13px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.07);
  color: #dfe3f0;
  cursor: pointer;
  text-align: center;
  text-decoration: none;
  transition: background 0.15s, border-color 0.15s;
}
.pt-btn:hover:not(:disabled) { border-color: rgba(255, 255, 255, 0.4); }
.pt-btn.primary { background: #5468f0; border-color: #5468f0; color: #fff; }
.pt-btn.primary:hover:not(:disabled) { background: #6476f5; }
.pt-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 规则 */
.pt-rules { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.pt-rules li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 11px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.09);
  cursor: pointer;
  transition: border-color 0.15s;
}
.pt-rules li:hover { border-color: rgba(108, 123, 255, 0.55); }
.pt-rule-line {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12.5px;
  word-break: break-all;
}
.pt-rule-note { color: #79809a; font-size: 12px; white-space: nowrap; flex-shrink: 0; }

/* 功能模块 */
.pt-snippet-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
/* 分组头下面挂列表时留一点间距 */
.pt-prov-group .pt-rules,
.pt-prov-group .pt-prov-list,
.pt-prov-group .pt-snippet-group { margin-top: 8px; }

/* 规则来源 */
.pt-chip-toggle {
  color: #aab1c8;
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.16);
}
.pt-chip-toggle:hover { background: rgba(255, 255, 255, 0.14); }
.pt-chip-toggle.active {
  color: #fff;
  background: #5468f0;
  border-color: #5468f0;
}
.pt-prov-summary { color: #8f96b0; font-size: 12.5px; margin: 0 0 10px; }
.pt-prov-group { margin-bottom: 10px; }
.pt-prov-group-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  color: #c3c8dc;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s;
}
.pt-prov-group-head:hover { border-color: rgba(108, 123, 255, 0.55); }
.pt-prov-group-name { font-size: 13px; font-weight: 600; }
.pt-prov-group-meta { font-size: 12px; color: #79809a; }
.pt-prov-group-caret { margin-left: auto; color: #8ba0f8; font-size: 11px; }
.pt-prov-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.pt-prov-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.pt-prov-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.pt-prov-name {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px;
  color: #dfe3f0;
}
.pt-prov-desc {
  font-size: 12px;
  color: #8f96b0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pt-prov-meta { font-size: 12px; color: #79809a; white-space: nowrap; }
.pt-prov-kind { font-size: 11px; padding: 2px 9px; border-radius: 99px; white-space: nowrap; }
.pt-prov-kind[data-kind='remote'] { background: rgba(34, 197, 183, 0.16); color: #5fd8c8; }
.pt-prov-kind[data-kind='inline'] { background: rgba(250, 183, 82, 0.16); color: #f5c069; }
.pt-prov-actions { display: flex; gap: 6px; flex-shrink: 0; }
.pt-mini {
  font-size: 12px;
  padding: 5px 11px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.06);
  color: #dfe3f0;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s;
}
.pt-mini:hover:not(:disabled) { border-color: rgba(108, 123, 255, 0.6); }
.pt-mini:disabled { opacity: 0.4; cursor: not-allowed; }

/* 规则来源详情 */
.pt-modal-card.wide { width: 760px; max-width: 100%; text-align: left; }
.pt-detail-desc { color: #8f96b0; font-size: 13px; margin: 0 0 12px; }
.pt-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px 18px;
  margin: 0 0 14px;
}
.pt-detail-grid > div { display: flex; gap: 8px; font-size: 12.5px; align-items: baseline; }
.pt-detail-grid dt { color: #79809a; margin: 0; flex: none; }
.pt-detail-grid dd { margin: 0; color: #dfe3f0; word-break: break-all; }
.pt-detail-url {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: #7e93c9;
  background: rgba(0, 0, 0, 0.28);
  border-radius: 8px;
  padding: 8px 10px;
  margin: 0 0 12px;
  word-break: break-all;
  cursor: pointer;
}
.pt-detail-url.empty { color: #6d7490; cursor: default; }
.pt-detail-preview {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.6;
  color: #aab1c8;
  background: rgba(0, 0, 0, 0.32);
  border-radius: 10px;
  padding: 12px;
  margin: 0;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.pt-detail-note { color: #6d7490; font-size: 11.5px; margin: 8px 0 0; }
.pt-detail-actions { display: flex; gap: 10px; margin-top: 16px; }

.pt-empty {
  color: #79809a; font-size: 13px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 10px; padding: 14px 16px;
}
.pt-chip {
  font-size: 12.5px;
  padding: 5px 12px;
  border-radius: 99px;
  background: rgba(108, 123, 255, 0.14);
  border: 1px solid rgba(108, 123, 255, 0.3);
  color: #b9c2f5;
}
.pt-chip i { font-style: normal; color: #79809a; margin-left: 6px; font-size: 11px; }

/* 导入指引 */
.pt-guide {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 10px;
  margin-bottom: 10px;
  padding: 12px 16px;
}
.pt-guide summary { cursor: pointer; font-size: 14px; font-weight: 500; }
.pt-guide-title { font-size: 14px; font-weight: 500; }
.pt-guide ol { margin: 10px 0 2px; padding-left: 20px; color: #aab1c8; font-size: 13px; line-height: 2; }

.pt-footer {
  margin-top: 44px;
  text-align: center;
  color: #6d7490;
  font-size: 12px;
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}
.pt-footer a { color: #8ba0f8; text-decoration: none; }
.pt-noresult { text-align: center; color: #79809a; padding: 40px 0; font-size: 14px; }

/* 二维码弹层 */
.pt-modal {
  position: fixed;
  inset: 0;
  background: rgba(4, 6, 14, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 50;
}
.pt-modal-card {
  background: #171b2e;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 18px;
  padding: 24px;
  width: 320px;
  max-width: 100%;
  text-align: center;
}
.pt-modal-title { font-weight: 600; margin: 0 0 14px; }
.pt-modal-card img { width: 220px; height: 220px; border-radius: 10px; background: #fff; }
.pt-modal-card .pt-btn { margin-top: 6px; }

@media (max-width: 640px) {
  .pt-hero h1.pt-hero-title { font-size: 15px; letter-spacing: 1px; }
  .pt-hero-top { gap: 8px; }
  .pt-hero-sub { font-size: 12px; }
  .pt-search { max-width: 100%; }
  .pt-search-btn { padding: 0 16px; }
  .pt-grid { grid-template-columns: 1fr; }
  .pt-rules li { flex-direction: column; align-items: flex-start; gap: 4px; }
  .pt-prov-row { flex-wrap: wrap; }
  .pt-prov-meta { white-space: normal; }
  .pt-prov-actions { width: 100%; }
  .pt-prov-actions .pt-mini { flex: 1; }
  .pt-main { padding: 0 14px 44px; }
  .pt-hero-inner { padding: 0 14px; }
}
</style>

/* PIN 输入：form 布局，按钮跟输入框并排 */
.pt-pin-form {
  display: flex;
  gap: 8px;
  align-items: stretch;
  margin: 0;
}
.pt-pin-form { width: 100%; max-width: 280px; margin: 0 auto; }
.pt-pin-form .pt-pin { flex: 1 1 auto; min-width: 0; width: auto; }
.pt-pin-submit {
  flex: 0 0 auto;
  border: 1px solid var(--mp-border);
  border-radius: 8px;
  background: var(--mp-primary);
  color: #fff;
  font-size: 14px;
  padding: 0 16px;
  cursor: pointer;
}
.pt-pin-submit:disabled { opacity: .5; cursor: not-allowed; }
