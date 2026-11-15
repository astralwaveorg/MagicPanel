import { expect, test } from 'vitest'
import { evidenceLabel } from './status'

test.each([
  ['unknown', '未验证'],
  ['inconclusive', '证据不足'],
  ['stale', '证据陈旧'],
  ['skipped', '未执行'],
])('%s 保留证据状态，不显示节点失败', (state, label) => {
  expect(evidenceLabel(state)).toBe(label)
})

test.each([
  ['pass', '此项通过'],
  ['fail', '此项失败'],
  ['expired', '已过期'],
  ['blocked', '已阻塞'],
  ['cancelled', '已取消'],
])('%s 只描述当前证据或任务结果', (state, label) => {
  expect(evidenceLabel(state)).toBe(label)
})

test.each(['future_state', '', 'constructor', 'toString', '__proto__'])(
  '未登记的状态 %j 一律显示未验证', state => {
    expect(evidenceLabel(state)).toBe('未验证')
  },
)
