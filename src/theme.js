const KEY = 'mp-theme'

/** 默认暗色；仅当用户显式选择过时恢复亮色。 */
export function currentTheme() {
  return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
}

export function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark'
  localStorage.setItem(KEY, next)
  applyTheme(next)
  return next
}
