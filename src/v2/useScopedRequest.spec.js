import { expect, test } from 'vitest'
import { createScopedRequest } from './useScopedRequest'

function deferred() {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

test('旧方案即使忽略 abort 也不能覆盖新方案', async () => {
  const old = deferred()
  const request = createScopedRequest(scope => scope === 'A'
    ? old.promise : Promise.resolve({ scope: 'B' }))
  const pending = request.load('A')
  await request.load('B')
  old.resolve({ scope: 'A' })
  await pending
  expect(request.state.data).toEqual({ scope: 'B' })
  expect(request.state.loading).toBe(false)
  expect(request.state.error).toBeNull()
})

test('过期异常不能替换新请求的错误或提前结束加载', async () => {
  const a = deferred(), b = deferred()
  const request = createScopedRequest(scope => scope === 'A' ? a.promise : b.promise)
  const first = request.load('A')
  const second = request.load('B')
  a.reject(new Error('old failure'))
  await first
  expect(request.state.loading).toBe(true)
  expect(request.state.error).toBeNull()
  b.resolve({ scope: 'B' })
  await second
  expect(request.state.data).toEqual({ scope: 'B' })
})

test('新 scope 加载中不显示旧数据，取消后忽略迟到结果', async () => {
  const pending = deferred()
  let latestSignal
  const request = createScopedRequest((scope, signal) => {
    latestSignal = signal
    return scope === 'A' ? Promise.resolve('A data') : pending.promise
  })
  await request.load('A')
  const second = request.load('B')
  expect(request.state.data).toBeNull()
  request.cancel()
  expect(latestSignal.aborted).toBe(true)
  pending.resolve('B data')
  await second
  expect(request.state.data).toBeNull()
  expect(request.state.loading).toBe(false)
})

test('主动取消不显示错误，当前异常可由后续加载清除', async () => {
  let attempt = 0
  const request = createScopedRequest(() => {
    attempt += 1
    if (attempt === 1) throw new DOMException('cancelled', 'AbortError')
    if (attempt === 2) throw new Error('current failure')
    return Promise.resolve('recovered')
  })
  await request.load(1)
  expect(request.state.error).toBeNull()
  await request.load(2)
  expect(request.state.error.message).toBe('current failure')
  await request.load(3)
  expect(request.state.error).toBeNull()
  expect(request.state.data).toBe('recovered')
})
