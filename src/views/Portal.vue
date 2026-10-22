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
            <button v-if="isMaintainer" class="pt-exit" @click="goAdmin">管理后台</button>
            <button v-else class="pt-exit" @click="exitPortal">退出查看</button>
          </div>
          <h1>订阅中心</h1>
          <p class="pt-hero-sub">
            {{ devices.length }} 台设备 · {{ data.rules.length }} 条个人规则 ·
            {{ data.rule_providers.length }} 个规则来源 ·
            {{ releaseText('production') }} · {{ releaseText('testing') }}
          </p>
          <div class="pt-search">
            <input v-model="query" placeholder="搜索订阅、规则、客户端…" aria-label="搜索">
          </div>
        </div>
      </header>

      <main class="pt-main">
        <!-- 核心配置 -->
        <section v-if="engineGroups.length">
          <h2 class="pt-sec-title">核心配置</h2>
          <div v-for="g in engineGroups" :key="g.engine" class="pt-engine">
            <h3 class="pt-engine-title">{{ g.label }}</h3>
            <div class="pt-grid">
              <article v-for="d in g.devices" :key="d.name" class="pt-card">
                <div class="pt-card-head">
                  <span class="pt-card-name">{{ d.display_name || d.name }}</span>
                  <span class="pt-tag" :data-env="d.env">
                    {{ d.env === 'production' ? '生产环境' : '测试环境' }}
                  </span>
                </div>
                <p class="pt-card-meta">
                  {{ platformLabel(d.platform) }} · {{ d.target_name }}
                  <template v-if="d.display_name && d.display_name !== d.name">
                    · 文件 {{ d.name }}.yaml
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
        </section>
        <p v-else-if="!query" class="pt-empty">
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

        <!-- 分流规则：默认折叠，搜索时自动展开匹配项 -->
        <section v-if="rules.length || (!query && ruleTotal)">
          <h2 class="pt-sec-title">分流规则<small>个人维护，点击复制</small></h2>
          <button
            v-if="!query && !rulesExpanded"
            class="pt-rules-toggle"
            @click="rulesExpanded = true"
          >共 {{ ruleTotal }} 条，点击展开</button>
          <ul v-else class="pt-rules">
            <li v-for="(r, i) in rules" :key="i" @click="copyRule(r, i)">
              <span class="pt-rule-line">{{ ruleLine(r) }}</span>
              <span class="pt-rule-note">{{ copied === 'rule-' + i ? '已复制' : (r.note || '') }}</span>
            </li>
          </ul>
          <button
            v-if="!query && rulesExpanded"
            class="pt-rules-toggle"
            @click="rulesExpanded = false"
          >收起</button>
        </section>

        <!-- 规则来源 -->
        <section v-if="ruleProviders.length">
          <h2 class="pt-sec-title">规则来源<small>已随配置下发</small></h2>
          <div class="pt-providers">
            <span v-for="p in ruleProviders" :key="p.name" class="pt-chip"
                  :title="`${p.behavior} · ${p.kind === 'inline' ? '内联' : '远程'}`">
              {{ p.name }}<i>{{ p.rule_count ?? 0 }} 条</i>
            </span>
          </div>
        </section>

        <!-- 功能模块 -->
        <section v-if="snippetGroups.length">
          <h2 class="pt-sec-title">功能模块<small>已随配置下发</small></h2>
          <div class="pt-snippets">
            <div v-for="g in snippetGroups" :key="g.category" class="pt-snippet-group">
              <span class="pt-snippet-cat">{{ g.label }}</span>
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

        <div v-if="query && !hasAnyResult" class="pt-noresult">
          没有匹配 “{{ query }}” 的内容
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
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
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
const query = ref('')
const copied = ref('')
const pinInput = ref(null)
const qrUrl = ref('')
const qrText = ref('')
const qrDevice = ref('')
const qrCache = new Map()
const rulesExpanded = ref(false)
let lockTimer = null

const CATEGORY_LABELS = {
  script: '脚本', rewrite: '复写', panel: '面板', dns: 'DNS', general: '通用',
}
const PLATFORM_LABELS = {
  ios: 'iOS', macos: 'macOS', tvos: 'tvOS', windows: 'Windows', android: 'Android',
  linux: 'Linux',
}
const ENGINE_LABELS = { stash: 'Stash', mihomo: 'Mihomo' }

const norm = (s) => (s || '').toLowerCase()
const hit = (...fields) => !query.value
  || fields.some((f) => norm(f).includes(norm(query.value)))

const devices = computed(() =>
  (data.value?.devices || []).filter((d) =>
    hit(d.name, d.display_name, d.platform, d.target_name, d.note)))

const engineGroups = computed(() => {
  const groups = {}
  for (const d of devices.value) {
    const key = d.engine || 'other'
    ;(groups[key] ||= []).push(d)
  }
  return Object.entries(groups).map(([engine, list]) => ({
    engine,
    label: ENGINE_LABELS[engine] || engine,
    devices: list,
  }))
})

const clients = computed(() =>
  (data.value?.clients || []).filter((c) => hit(c.name, c.desc, c.platform)))

const rules = computed(() =>
  (data.value?.rules || []).filter((r) => hit(r.type, r.value, r.target, r.note)))

const ruleTotal = computed(() => data.value?.rules?.length || 0)

const ruleProviders = computed(() =>
  (data.value?.rule_providers || []).filter((p) => hit(p.name, p.behavior, p.kind)))

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

const guides = computed(() => data.value?.guides || [])

const hasAnyResult = computed(() =>
  devices.value.length || clients.value.length || rules.value.length
  || ruleProviders.value.length || snippetGroups.value.length)

function platformLabel(p) { return PLATFORM_LABELS[p] || p }
function engineLabel(e) { return e === 'stash' ? 'Stash' : 'Mihomo' }
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
  padding: 22px 20px 44px;
}
.pt-hero-inner { max-width: 1080px; margin: 0 auto; }
.pt-hero-top { display: flex; justify-content: space-between; align-items: center; }
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
.pt-hero h1 { font-size: 30px; margin: 26px 0 8px; letter-spacing: 1px; }
.pt-hero-sub { color: #9aa0b5; font-size: 13px; margin: 0 0 22px; }
.pt-search input {
  width: 100%;
  padding: 13px 18px;
  font-size: 15px;
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 12px;
  outline: none;
}
.pt-search input:focus { border-color: #6c7bff; }
.pt-search input::placeholder { color: #6d7490; }

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
.pt-engine-title { font-size: 13px; color: #8f96b0; margin: 18px 0 10px; font-weight: 600; }

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
.pt-rules-toggle {
  width: 100%;
  padding: 11px 16px;
  font-size: 13px;
  text-align: left;
  color: #8ba0f8;
  background: rgba(255, 255, 255, 0.05);
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.pt-rules-toggle:hover { border-color: rgba(108, 123, 255, 0.55); }
.pt-rules-toggle + .pt-rules-toggle { margin-top: 8px; }
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
.pt-snippets { display: flex; flex-direction: column; gap: 12px; }
.pt-snippet-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pt-snippet-cat { font-size: 13px; color: #8f96b0; width: 44px; flex-shrink: 0; }
.pt-providers { display: flex; gap: 10px; flex-wrap: wrap; }
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
  .pt-hero h1 { font-size: 24px; }
  .pt-grid { grid-template-columns: 1fr; }
  .pt-rules li { flex-direction: column; align-items: flex-start; gap: 4px; }
  .pt-main { padding: 0 14px 44px; }
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
