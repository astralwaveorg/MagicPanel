import { store } from './store'

// 核心二进制直传，不走 api() 的 JSON 封装
export async function uploadCore(rawFile) {
  if (!rawFile) throw new Error('未选择文件')
  if (rawFile.size > 100 * 1024 * 1024) throw new Error('文件不能超过 100 MB')
  const resp = await fetch('/api/v1/core/upload', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/octet-stream', 'X-CSRF-Token': store.csrf },
    body: rawFile,
  })
  const d = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(d.detail || `上传失败（${resp.status}）`)
  return d
}
