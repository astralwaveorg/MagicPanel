import { store } from './store'

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message)
    this.status = status
    // 后端返回的结构化错误体（如"仍被引用"的引用明细），交给调用方判断
    this.data = data
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
    if (msg && typeof msg === 'object' && !Array.isArray(msg)) {
      // 后端结构化错误：{code, message, references...}
      msg = msg.message || msg.detail || `请求失败（${resp.status}）`
    }
    if (Array.isArray(msg)) {
      msg = msg.map((e) => {
        const text = e?.msg || JSON.stringify(e)
        // Pydantic 会给自定义校验消息加 "Value error, " 前缀，去掉更干净
        return String(text).replace(/^Value error,\s*/, '')
      }).join('；')
    }
    throw new ApiError(resp.status, String(msg), data)
  }
  return data
}
