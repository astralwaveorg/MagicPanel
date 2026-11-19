import { afterEach, describe, expect, it, vi } from 'vitest'
import { BROWSER_CHECKS, probeAll, probeExitIp, probeOne } from './browserChecks'

afterEach(() => vi.unstubAllGlobals())

describe('browserChecks 目录', () => {
  it('id 全局唯一', () => {
    const ids = BROWSER_CHECKS.map((c) => c.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('每个条目都有 url 与分类', () => {
    for (const c of BROWSER_CHECKS) {
      expect(c.url).toMatch(/^https:\/\//)
      expect(['ai', 'stream', 'region', 'web']).toContain(c.category)
    }
  })
})

describe('probeOne', () => {
  it('网络层成功 → reachable + 延迟', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({})))
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    expect(r.state).toBe('reachable')
    expect(r.latency_ms).toBeGreaterThanOrEqual(0)
  })

  it('网络层失败 → unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    expect(r.state).toBe('unreachable')
  })

  it('超时 → timeout（不再让 Promise 挂住）', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))   // 永不完成
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 30)
    expect(r.state).toBe('timeout')
  })

  it('no-cors 模式 + 不读缓存', async () => {
    const fetchMock = vi.fn(async () => ({}))
    vi.stubGlobal('fetch', fetchMock)
    await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    const arg = fetchMock.mock.calls[0][1]
    expect(arg.mode).toBe('no-cors')
    expect(arg.cache).toBe('no-store')
  })
})

describe('probeAll', () => {
  it('全部项都有结果且回调逐项触发', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('x') }))
    const seen = []
    const items = BROWSER_CHECKS.slice(0, 3)
    const results = await probeAll(items, (r) => seen.push(r.id))
    expect(Object.keys(results).length).toBe(3)
    expect(seen.sort()).toEqual(items.map((c) => c.id).sort())
  })

  it('fetch 异常不会中断整批', async () => {
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1
      if (calls === 1) throw new TypeError('boom')
      return {}
    }))
    const results = await probeAll(BROWSER_CHECKS.slice(0, 3))
    expect(Object.keys(results).length).toBe(3)
  })
})

describe('probeExitIp', () => {
  it('成功返回 ip/country/org', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ ip: '1.2.3.4', country: 'US', org: 'Test' }),
    })))
    expect(await probeExitIp()).toEqual({ ip: '1.2.3.4', country: 'US', org: 'Test' })
  })

  it('失败返回 error 而不抛', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('x') }))
    expect((await probeExitIp()).error).toBeTruthy()
  })
})

describe('probeOne 失败分类', () => {
  it('服务端已响应但跨域重定向不可读 → 判可达（服务是通的）', async () => {
    const err = new TypeError('Failed to load resource: net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin')
    vi.stubGlobal('fetch', vi.fn(async () => { throw err }))
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    expect(r.state).toBe('reachable')
    expect(r.reason).toBe('responded_redirect')
  })

  it('真网络失败 → 不可达（network_error）', async () => {
    const err = new TypeError('Failed to fetch')
    vi.stubGlobal('fetch', vi.fn(async () => { throw err }))
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    expect(r.state).toBe('unreachable')
    expect(r.reason).toBe('network_error')
  })

  it('CSP 拦截 → blocked_by_policy', async () => {
    const err = new TypeError("Refused to connect 'https://a.example/' because it violates the following Content Security Policy directive")
    vi.stubGlobal('fetch', vi.fn(async () => { throw err }))
    const r = await probeOne({ id: 'x', url: 'https://a.example/favicon.ico' }, 1000)
    expect(r.state).toBe('unreachable')
    expect(r.reason).toBe('blocked_by_policy')
  })
})
