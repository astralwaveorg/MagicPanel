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

export const PLATFORM_LABELS = {
  ios: 'iOS', macos: 'macOS', tvos: 'tvOS', windows: 'Windows', android: 'Android',
}

export const CHANNEL_LABELS = { stable: '稳定', candidate: '候选' }

export function sourceStatus(s) {
  if (!s.last_status || s.last_status === 'never') return { kind: 'muted', text: '从未抓取' }
  if (s.last_status === 'ok') return { kind: 'ok', text: '抓取成功' }
  return { kind: 'danger', text: '抓取失败' }
}
