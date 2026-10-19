import { store } from './store'

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const opts = { method, headers: { ...headers }, credentials: 'same-origin' }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  if (method !== 'GET' && store.csrf) {
    opts.headers['X-CSRF-Token'] = store.csrf
  }
  const resp = await fetch(path, opts)
  if (resp.status === 401 && !path.startsWith('/api/v1/auth') && !path.startsWith('/api/v1/setup')) {
    store.user = null
    store.csrf = ''
    if (!location.pathname.startsWith('/admin/login')) location.assign('/admin/login')
    throw new ApiError(401, '未登录或会话已过期')
  }
  const text = await resp.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text || '响应格式错误' } }
  if (!resp.ok) {
    let msg = data?.detail ?? `请求失败（${resp.status}）`
    if (Array.isArray(msg)) msg = msg.map((e) => e.msg || JSON.stringify(e)).join('；')
    throw new ApiError(resp.status, String(msg))
  }
  return data
}
