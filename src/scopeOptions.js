// 多选列表里的「包含所有」哨兵，与后端 config.ALL_SCOPE 保持一致。
// 选中它表示"全部"：节点来源 = 所有来源（含以后新增的），
// 引擎平台 / 设备 = 全部。
export const ALL_SCOPE = '*'

// 选中「包含所有」时只留它一个；改选具体项时把它去掉。
export function normalizeScope(list, value) {
  const arr = Array.isArray(list) ? list : []
  if (arr.includes(value)) return [ALL_SCOPE]
  if (arr.includes(ALL_SCOPE)) return arr.filter((x) => x !== ALL_SCOPE)
  return arr
}

// 列表里是否含「包含所有」
export function hasAllScope(list) {
  return Array.isArray(list) && list.includes(ALL_SCOPE)
}

// 选满 = 包含所有：把逐项选全的列表归一为 ["*"]，
// 这样以后新增的项也会自动包含进来。
export function collapseIfComplete(list, allValues) {
  const arr = Array.isArray(list) ? list : []
  if (!arr.length || arr.includes(ALL_SCOPE)) return arr
  if (!Array.isArray(allValues) || !allValues.length) return arr
  const set = new Set(arr)
  if (allValues.every((v) => set.has(v))) return [ALL_SCOPE]
  return arr
}
