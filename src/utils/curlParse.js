/** curl 命令解析（从 curl 导入订阅地址与请求头）。

    纯函数、无 DOM 依赖：抽出来单测——正则写错一个字符，
    CI 以前是拦不住的（2026-11-18 从 Sources.vue 抽出）。
    规则：
    * 地址取命令里第一个 http(s) 链接，去掉尾随引号；
    * -H/--header 支持 "…" / '…' / 裸 token 三种写法；
    * Host 由地址决定，忽略（用户重复设置没有意义）。
    */
export function parseCurl(text) {
  const urlMatch = text.match(/https?:\/\/[^\s'"]+/)
  const url = urlMatch ? urlMatch[0].replace(/['"]+$/, '') : ''
  const found = []
  const re = /(?:-H|--header)\s+(?:"([^"]*)"|'([^']*)'|([^\s]+))/g
  let m = re.exec(text)
  while (m !== null) {
    const raw = m[1] ?? m[2] ?? m[3] ?? ''
    const idx = raw.indexOf(':')
    if (idx > 0) {
      const name = raw.slice(0, idx).trim()
      const value = raw.slice(idx + 1).trim()
      // Host 由地址决定，重复设置没有意义
      if (name && !/^host$/i.test(name)) found.push({ name, value })
    }
    m = re.exec(text)
  }
  return { url, headers: found }
}
