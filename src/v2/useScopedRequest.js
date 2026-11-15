import { reactive } from 'vue'

export function createScopedRequest(fetcher) {
  const state = reactive({ data: null, loading: false, error: null })
  let sequence = 0
  let controller
  async function load(scope) {
    const current = ++sequence
    controller?.abort()
    controller = new AbortController()
    state.data = null
    state.loading = true
    state.error = null
    try {
      const data = await fetcher(scope, controller.signal)
      if (current === sequence) state.data = data
    } catch (error) {
      if (current === sequence && error?.name !== 'AbortError') state.error = error
    } finally {
      if (current === sequence) state.loading = false
    }
  }
  function cancel() {
    sequence += 1
    controller?.abort()
    state.data = null
    state.error = null
    state.loading = false
  }
  return { state, load, cancel }
}
