// 移动端判定：全局共享一份，避免每个组件各挂一个监听。
// 判定标准与 styles.css 里的断点保持一致（768px）。
import { ref } from 'vue'

const MOBILE_QUERY = '(max-width: 768px)'

const narrow = ref(
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(MOBILE_QUERY).matches
    : false,
)

let mql = null
let handler = null

function ensureListening() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  if (mql) return
  mql = window.matchMedia(MOBILE_QUERY)
  handler = (e) => { narrow.value = e.matches }
  narrow.value = mql.matches
  mql.addEventListener('change', handler)
}

/** 在 setup 里调用一次，返回一个 ref（true = 窄屏）。 */
export function useMobile() {
  ensureListening()
  return narrow
}
