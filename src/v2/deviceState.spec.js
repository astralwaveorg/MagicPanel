import { test, expect } from 'vitest'
import { deviceState } from './deviceState'

test('周计划第三天无新拉取不代表故障，下载不代表加载', () => {
  const state = deviceState({
    expected_at: '2026-11-23T00:00:00Z',
    last_delivered_at: '2026-11-16T00:00:00Z',
    loaded_at: null, business_at: null,
    now: '2026-11-19T00:00:00Z',
  })
  expect(state.delivery).toBe('within_schedule')
  expect(state.loading).toBe('unknown')
  expect(state.business).toBe('unknown')
})

test('缺失计划时间不能推断 overdue', () => {
  expect(deviceState({ expected_at: null, now: '2026-11-19T00:00:00Z' }).delivery).toBe('unknown')
})
