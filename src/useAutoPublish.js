// 自动构建发布的共享状态与动作。
//
// 页面级的「立即发布」按钮（构建发布页标题行）与「自动运行配置」面板
// 共用同一份状态：面板里看到的状态、运行记录，与标题行按钮触发的是同一轮。
// 状态放在模块作用域，两个组件引用的是同一份。
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from './api'
import { confirmBox } from './confirm'
import { ENV_LABELS, RELEASE_ACTION_LABELS } from './format'

const status = ref({
  running: false, autostart: true, last_tick_at: '', last_result: null, last_error: '',
})
const releases = ref([])
const runs = ref([])
const saving = ref(false)
const triggering = ref(false)
const form = reactive({
  scheduler_enabled: true,
  auto_fetch_sources: true,
  auto_test_sources: true,
  auto_fetch_rules: true,
  auto_fetch_snippets: true,
  auto_build_enabled: true,
  auto_build_interval_hours: 12,
  auto_publish_enabled: true,
  auto_publish_env: 'production',
})

export { status, releases, runs, saving, triggering, form }

// 发布历史动作：发布/回滚带上环境，下线只写动作
export function releaseActionText(row) {
  const action = RELEASE_ACTION_LABELS[row.action] || row.action
  if (row.action === 'offline') return action
  return `${action}到${ENV_LABELS[row.env] || row.env}`
}

export function resultText(r) {
  if (!r) return '暂无运行记录'
  const parts = []
  if (r.sources_fetched || r.sources_failed) {
    parts.push(`节点抓取 ${r.sources_fetched} 成功 / ${r.sources_failed} 失败`)
  }
  if (r.rules_fetched || r.rules_failed) {
    parts.push(`规则抓取 ${r.rules_fetched} 成功 / ${r.rules_failed} 失败`)
  }
  if (r.snippets_fetched || r.snippets_failed) {
    parts.push(`拓展模块抓取 ${r.snippets_fetched} 成功 / ${r.snippets_failed} 失败`)
  }
  if (r.tests_run || r.tests_errors) {
    parts.push(`测速 ${r.tests_ok} 可用 / ${r.tests_failed} 失败`)
  }
  if (r.test_skipped) parts.push(r.test_skipped)
  if (r.build) {
    parts.push(typeof r.build === 'string'
      ? `构建：${r.build}`
      : `构建 #${r.build.id}（${r.build.status === 'success' ? '通过' : '失败'}）`)
  }
  if (r.published) parts.push(`已发布到${ENV_LABELS[r.published] || r.published}`)
  if (r.build_error) parts.push(`构建错误：${r.build_error}`)
  if (r.errors?.length) parts.push(`${r.errors.length} 个抓取/测速错误`)
  if (r.skipped) parts.push(r.skipped)
  if (!parts.length) {
    return r.trigger === 'manual' ? '强制执行完成，没有可处理的项目' : '本轮没有到期任务'
  }
  return parts.join('；')
}

const lastResultText = computed(() => resultText(status.value.last_result))
export { lastResultText }

function applySettings(s) {
  form.scheduler_enabled = s.scheduler_enabled === '1'
  form.auto_fetch_sources = s.auto_fetch_sources === '1'
  form.auto_test_sources = s.auto_test_sources === '1'
  form.auto_fetch_rules = s.auto_fetch_rules === '1'
  form.auto_fetch_snippets = s.auto_fetch_snippets !== '0'
  form.auto_build_enabled = s.auto_build_enabled === '1'
  form.auto_build_interval_hours = Number(s.auto_build_interval_hours) || 12
  form.auto_publish_enabled = s.auto_publish_enabled === '1'
  form.auto_publish_env = s.auto_publish_env === 'testing' ? 'testing' : 'production'
}

export async function loadAutoPublish() {
  try {
    const [s, st, rel, runList] = await Promise.all([
      api('/api/v1/settings'), api('/api/v1/automation/status'),
      api('/api/v1/releases?auto_only=true'), api('/api/v1/automation/runs?limit=20'),
    ])
    applySettings(s)
    status.value = st
    releases.value = rel
    runs.value = runList
  } catch (e) {
    ElMessage.error(e.message)
  }
}

export async function refreshAutoStatus() {
  try {
    const [st, rel, runList] = await Promise.all([
      api('/api/v1/automation/status'),
      api('/api/v1/releases?auto_only=true'),
      api('/api/v1/automation/runs?limit=20'),
    ])
    status.value = st
    releases.value = rel
    runs.value = runList
  } catch { /* 状态刷新失败不打扰 */ }
}

export async function saveAutoSettings() {
  saving.value = true
  try {
    await api('/api/v1/settings', { method: 'PUT', body: { values: {
      scheduler_enabled: form.scheduler_enabled ? '1' : '0',
      auto_fetch_sources: form.auto_fetch_sources ? '1' : '0',
      auto_test_sources: form.auto_test_sources ? '1' : '0',
      auto_fetch_rules: form.auto_fetch_rules ? '1' : '0',
      auto_fetch_snippets: form.auto_fetch_snippets ? '1' : '0',
      auto_build_enabled: form.auto_build_enabled ? '1' : '0',
      auto_build_interval_hours: String(form.auto_build_interval_hours),
      auto_publish_enabled: form.auto_publish_enabled ? '1' : '0',
      auto_publish_env: form.auto_publish_env,
    } } })
    ElMessage.success('已保存')
    await refreshAutoStatus()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

// 强制跑一轮：按当前设置抓取 → 测速 → 构建检查 → 发布。
// 发布目标可能是生产（auto_publish_env 默认 production），先按设置确认再执行。
export async function runAutoNow() {
  if (triggering.value) return
  let settings = {}
  try {
    settings = await api('/api/v1/settings')
  } catch { /* 读不到设置时按默认全开确认 */ }
  const fetchOn = settings.auto_fetch_sources !== '0'
  const testOn = settings.auto_test_sources !== '0'
  const publishOn = settings.auto_publish_enabled !== '0'
  const env = settings.auto_publish_env === 'testing' ? 'testing' : 'production'
  const steps = []
  if (fetchOn) steps.push('抓取节点来源与规则')
  if (testOn) steps.push('测速')
  steps.push('创建构建并校验（策略未变化会跳过构建）')
  steps.push(publishOn ? `发布到${env === 'testing' ? '测试' : '生产'}` : '不发布（自动发布已关闭）')
  const ok = await confirmBox(
    `将按当前自动任务设置执行：${steps.join(' → ')}。`,
    '抓取并发布', { confirmButtonText: '执行', cancelButtonText: '取消' },
  )
  if (!ok) return
  triggering.value = true
  const beforeTick = status.value.last_tick_at
  try {
    await api('/api/v1/automation/run', { method: 'POST' })
    ElMessage.success('已开始执行，正在等待运行结果…')
    let seenRunning = false
    let finished = false
    // 抓取 + 测速 + 核心校验可能要几分钟，最多等 10 分钟；
    // 期间页面显示"运行中"，不再让用户对着一根转圈猜。
    const started = Date.now()
    while (Date.now() - started < 10 * 60 * 1000) {
      await new Promise((resolve) => setTimeout(resolve, 2000))
      await refreshAutoStatus()
      if (status.value.running) seenRunning = true
      if (!status.value.running && status.value.last_tick_at
          && status.value.last_tick_at !== beforeTick) {
        finished = true
        break
      }
      if (!status.value.running && !seenRunning) break
    }
    if (finished) {
      const published = status.value.last_result?.published
      ElMessage.success(published
        ? `执行完成，已发布到${ENV_LABELS[published] || published}`
        : '自动任务执行完成')
      await loadAutoPublish()
    } else {
      ElMessage.warning('未获取到本轮结果，请稍后刷新查看运行记录')
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    triggering.value = false
  }
}
