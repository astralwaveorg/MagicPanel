/** 剪贴板兜底：全站唯一的复制实现（2026-11-18 从 6 处复制实现收拢）。

    优先 async clipboard API，失败回退 execCommand+textarea；
    两层都失败时抛错，由调用方提示用户手动复制。
    */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch { /* 继续走兜底 */ }
  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', '')
    el.style.position = 'fixed'
    el.style.left = '-9999px'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    el.remove()
    if (!ok) throw new Error('execCommand failed')
    return true
  } catch {
    throw new Error('浏览器拒绝了剪贴板权限，请手动复制')
  }
}
