import { ALL_SCOPE } from './scopeOptions'

export function fmtTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function shortSha(sha) {
  return sha ? sha.slice(0, 12) : '—'
}

// 专有名词展示（大小写必须规范）
export const ENGINE_LABELS = { stash: 'Stash', mihomo: 'Mihomo' }

export const PLATFORM_LABELS = {
  ios: 'iOS', macos: 'macOS', tvos: 'tvOS', windows: 'Windows', android: 'Android',
  linux: 'Linux',
}

// 构建生命周期状态（后端状态机的四种状态）
export const BUILD_STATUS_LABELS = {
  BUILT: '已构建', TESTING: '测试中', PRODUCTION: '生产中', OFFLINE: '已下线',
}

// 发布环境（生产 / 测试）
export const ENV_LABELS = { production: '生产环境', testing: '测试环境' }

// 发布历史里的动作
export const RELEASE_ACTION_LABELS = { publish: '发布', rollback: '回滚', offline: '下线' }

/** 构建状态对应的 el-tag 颜色。 */
export function buildStatusTagType(status) {
  if (status === 'PRODUCTION') return 'success'
  if (status === 'TESTING') return 'primary'
  return 'info'
}

/** 已下线的构建用暗灰，其余用默认浅色。 */
export function buildStatusTagEffect(status) {
  return status === 'OFFLINE' ? 'dark' : 'light'
}

export function sourceStatus(s) {
  if (!s.last_status || s.last_status === 'never') return { kind: 'muted', text: '从未抓取' }
  if (s.last_status === 'ok') return { kind: 'ok', text: '抓取成功' }
  // 抓取失败不影响已经抓到的内容：构建照旧用上一份快照
  const tip = s.rule_count
    ? '抓取失败（仍用上次抓到的内容）'
    : '抓取失败（还没有内容）'
  return { kind: 'danger', text: '抓取失败', tip }
}

/**
 * 适用范围摘要：表格里只显示一行，完整清单靠悬浮提示。
 * 设备是「包含所有」时不重复显示——平台范围已经覆盖了全部设备。
 */
export function scopeBrief(targets, devices) {
  const t = Array.isArray(targets) ? targets : []
  const d = Array.isArray(devices) ? devices : []
  const platform = !t.length ? '不适用'
    : t.includes(ALL_SCOPE) ? '全部平台'
      : `${t.length} 个平台`
  if (!d.length || d.includes(ALL_SCOPE)) return platform
  return `${platform} · ${d.length} 台设备`
}

/** 备注：最多显示 8 个字，超出用省略号，完整内容靠悬浮提示。 */
export const NOTE_BRIEF_MAX = 8

export function noteBrief(note) {
  const chars = Array.from(String(note || ''))
  if (chars.length <= NOTE_BRIEF_MAX) return chars.join('')
  return `${chars.slice(0, NOTE_BRIEF_MAX).join('')}...`
}
