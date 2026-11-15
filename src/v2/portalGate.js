import { reactive } from 'vue'

export const validPortalPin = value => typeof value === 'string' && /^(?:\d{4}|\d{6})$/.test(value)

export function createPortalGate(send) {
  const state = reactive({ loading: false, error: null, data: null })
  let pending = null, sequence = 0
  return {
    state,
    submit(pin, { canSkipPin = false } = {}) {
      if (pending) return pending
      if (!validPortalPin(pin) && !(pin === '' && canSkipPin)) {
        return Promise.reject(new Error('请输入 4 或 6 位数字 PIN'))
      }
      const id = ++sequence
      state.loading = true
      state.error = null
      pending = Promise.resolve().then(() => send(pin)).then(data => {
        if (id !== sequence) return null
        state.data = data
        return data
      }).catch(error => {
        if (id !== sequence) return null
        state.error = error
        throw error
      }).finally(() => {
        if (id === sequence) { state.loading = false; pending = null }
      })
      return pending
    },
    reset() {
      ++sequence
      pending = null
      state.loading = false
      state.error = null
      state.data = null
    },
  }
}

// 只在后端给出的设备地址与授权方案内选择，不由来源名生成资源路径。
export function portalDeviceResource(device, variant, variants) {
  if (!Array.isArray(device.variants) || !device.variants.includes(variant)) return null
  const isDefault = variants.some(item => item.name === variant && item.id === 0)
  function selectUrl(address) {
    if (!address) return ''
    try {
      const url = new URL(address, window.location.origin)
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return ''
      if (isDefault) url.searchParams.delete('variant')
      else url.searchParams.set('variant', variant)
      return address.startsWith('/') && !address.startsWith('//')
        ? url.pathname + url.search + url.hash : url.href
    } catch { return '' }
  }
  const url = selectUrl(device.subscription_url)
  if (!url) return null
  return {
    url,
    previewUrl: selectUrl(device.preview_url),
    installUrl: `${device.engine === 'stash' ? 'stash' : 'clash'}://install-config?url=${encodeURIComponent(url)}`,
    downloadName: `${device.name}${isDefault ? '' : `@${variant}`}.yaml`,
  }
}
