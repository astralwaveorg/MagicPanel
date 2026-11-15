import { afterEach, expect, test, vi } from 'vitest'
import { api, ApiError } from '../api'
import { store } from '../store'

afterEach(() => { vi.unstubAllGlobals(); store.csrf = ''; store.user = null })

test('请求取消信号传到 fetch 边界，CSRF 和 JSON 请求体保留', async () => {
  let options
  vi.stubGlobal('fetch', async (path, opts) => {
    options = opts
    return new Response('{"ok":true}', { status: 200 })
  })
  store.csrf = 'fixture-csrf'
  const controller = new AbortController()
  expect(await api('/api/v1/fixture', {
    method: 'POST', body: { scope: 4 }, signal: controller.signal,
  })).toEqual({ ok: true })
  expect(options.signal).toBe(controller.signal)
  expect(options.credentials).toBe('same-origin')
  expect(options.headers['X-CSRF-Token']).toBe('fixture-csrf')
  expect(JSON.parse(options.body)).toEqual({ scope: 4 })
})

test('AbortError 原样交回调用方，结构化 API 错误不丢 detail', async () => {
  const cancelled = new DOMException('cancelled', 'AbortError')
  vi.stubGlobal('fetch', async () => { throw cancelled })
  await expect(api('/api/v1/fixture')).rejects.toBe(cancelled)
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({
    detail: { code: 'stale_revision', message: '版本已改变', current_revision: 3 },
  }), { status: 409 }))
  const error = await api('/api/v1/fixture').catch(value => value)
  expect(error).toBeInstanceOf(ApiError)
  expect(error.status).toBe(409)
  expect(error.detail).toEqual({ code: 'stale_revision', message: '版本已改变', current_revision: 3 })
})

test('已取消请求迟到的 401 不会清除当前登录态', async () => {
  const controller = new AbortController()
  store.user = { username: 'fixture-current-user' }
  store.csrf = 'fixture-current-csrf'
  vi.stubGlobal('location', { pathname: '/admin', assign() {} })
  vi.stubGlobal('fetch', async () => {
    controller.abort()
    return new Response('{"detail":"expired"}', { status: 401 })
  })
  const error = await api('/api/v1/overview', { signal: controller.signal }).catch(value => value)
  expect(error.name).toBe('AbortError')
  expect(store.user).toEqual({ username: 'fixture-current-user' })
  expect(store.csrf).toBe('fixture-current-csrf')
})
