const evidenceLabels = new Map([
  ['pass', '此项通过'],
  ['fail', '此项失败'],
  ['unknown', '未验证'],
  ['inconclusive', '证据不足'],
  ['stale', '证据陈旧'],
  ['expired', '已过期'],
  ['skipped', '未执行'],
  ['blocked', '已阻塞'],
  ['cancelled', '已取消'],
])

export function evidenceLabel(state) {
  return evidenceLabels.get(state) ?? '未验证'
}
