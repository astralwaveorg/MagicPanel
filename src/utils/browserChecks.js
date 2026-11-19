/** 「你的网络」浏览器端检测（2026-11-18 新增）。

    谁打开网页测谁的网络环境：这些探测跑在**访问面板的浏览器**里，
    反映的是「你正在用的这台设备所在网络」的可达性；面板出口检测
    （服务端 unlock_check）反映的是路由器代理链的出口。

    准确性边界（刻意只做能做准的事）：
    * 可达性 —— fetch(url, {mode:'no-cors'})：请求在网络层完成即 resolve
      （opaque response），连接失败/超时才 reject。能准确回答
      「你的设备能不能连上这个服务」；HTTP 状态被 opaque 遮蔽，
      所以**不冒充「解锁」判定**——那需要读响应体，浏览器端做不到。
    * 出口 IP —— ipinfo.io 开放 CORS，返回访问者真实出口与国家。
    * 两个视角对照才有结论：面板出口「解锁」但你的网络「不可达」
      → 该域名的分流没把你的设备送进代理链，查客户端规则。

    目录 id 与服务端 unlock_check.CHECKS 对齐，同一服务两个视角可对照。
    */
export const BROWSER_CHECKS = [
  // ai
  { id: 'gemini', name: 'Google Gemini', icon: '✦', category: 'ai',
    url: 'https://gemini.google.com/favicon.ico' },
  { id: 'chatgpt', name: 'ChatGPT', icon: '◎', category: 'ai',
    url: 'https://chatgpt.com/favicon.ico' },
  { id: 'claude', name: 'Claude', icon: '✳', category: 'ai',
    url: 'https://claude.ai/favicon.ico' },
  { id: 'grok', name: 'Grok', icon: '𝕏', category: 'ai',
    url: 'https://grok.com/favicon.ico' },
  { id: 'perplexity', name: 'Perplexity', icon: '◈', category: 'ai',
    url: 'https://www.perplexity.ai/favicon.ico' },
  { id: 'copilot', name: 'Copilot', icon: '⌘', category: 'ai',
    url: 'https://copilot.microsoft.com/favicon.ico' },
  // stream
  { id: 'netflix', name: 'Netflix', icon: 'N', category: 'stream',
    url: 'https://www.netflix.com/favicon.ico' },
  { id: 'disney', name: 'Disney+', icon: 'D', category: 'stream',
    url: 'https://www.disneyplus.com/favicon.ico' },
  { id: 'youtube_premium', name: 'YouTube Premium', icon: '▶', category: 'stream',
    url: 'https://www.youtube.com/favicon.ico' },
  { id: 'spotify', name: 'Spotify', icon: '♫', category: 'stream',
    url: 'https://www.spotify.com/favicon.ico' },
  { id: 'tiktok', name: 'TikTok', icon: '♪', category: 'stream',
    url: 'https://www.tiktok.com/favicon.ico' },
  { id: 'dazn', name: 'Dazn', icon: '▮', category: 'stream',
    url: 'https://www.dazn.com/favicon.ico' },
  { id: 'biliintl', name: 'Bilibili 海外版', icon: 'B', category: 'stream',
    url: 'https://www.bilibili.tv/favicon.ico' },
  { id: 'hbo', name: 'HBO Max', icon: '▣', category: 'stream',
    url: 'https://play.max.com/favicon.ico' },
  // region
  { id: 'tvbanywhere', name: 'TVBAnywhere', icon: 'T', category: 'region',
    url: 'https://www.tvbanywhere.com/favicon.ico' },
  { id: 'viu', name: 'Viu.com', icon: 'V', category: 'region',
    url: 'https://www.viu.com/favicon.ico' },
  // web
  { id: 'reddit', name: 'Reddit', icon: 'R', category: 'web',
    url: 'https://www.reddit.com/favicon.ico' },
  { id: 'wikipedia', name: '维基百科', icon: 'W', category: 'web',
    url: 'https://zh.wikipedia.org/favicon.ico' },
]

export const BROWSER_TIMEOUT_MS = 8000

/** 单项可达性探测：resolve=可达（opaque），reject=不可达。返回结果对象。 */
export async function probeOne(check, timeoutMs = BROWSER_TIMEOUT_MS) {
  const started = performance.now()
  const timer = new Promise((resolve) =>
    setTimeout(() => resolve('timeout'), timeoutMs))
  try {
    const outcome = await Promise.race([
      fetch(check.url, { mode: 'no-cors', redirect: 'follow', cache: 'no-store' })
        .then(() => 'reachable')
        .catch((err) => ({ state: 'unreachable', err })),
      timer,
    ])
    const latency_ms = Math.round(performance.now() - started)
    if (outcome === 'reachable') {
      return { id: check.id, state: 'reachable', latency_ms }
    }
    if (outcome === 'timeout') {
      return { id: check.id, state: 'timeout', latency_ms }
    }
    // 失败原因区分（2026-11-19 修正）：
    // * NotSameOrigin / ERR_BLOCKED_BY_RESPONSE：服务器**已经响应**并要求
    //   跳转（跨域重定向在 no-cors 下不可跟随）——这恰恰证明服务是通的，
    //   判"不可达"是误判；
    // * 极快失败（<200ms）多为浏览器策略拦截或域名被立即拒绝；
    // * 其它慢失败才是真连不上。
    const msg = String(outcome?.err?.message || outcome?.err || '')
    if (/NotSameOrigin|ERR_BLOCKED_BY_RESPONSE/i.test(msg)) {
      return { id: check.id, state: 'reachable', latency_ms,
               reason: 'responded_redirect', detail: '服务有响应（跳转不可读）' }
    }
    // CSP 拦截有明确特征（Chrome: "violates the following Content Security
    // Policy directive"）；其它失败一律算网络层不可达
    if (/Content Security Policy|CSP/i.test(msg)) {
      return { id: check.id, state: 'unreachable', latency_ms,
               reason: 'blocked_by_policy', detail: '被浏览器内容安全策略拦截' }
    }
    return { id: check.id, state: 'unreachable', latency_ms,
             reason: 'network_error', detail: '网络不可达' }
  } catch (err) {
    return { id: check.id, state: 'unreachable',
             latency_ms: Math.round(performance.now() - started),
             reason: 'network_error', detail: String(err).slice(0, 80) }
  }
}

/** 出口 IP 与国家（ipinfo.io 开放 CORS）。 */
export async function probeExitIp(timeoutMs = BROWSER_TIMEOUT_MS) {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), timeoutMs)
    const resp = await fetch('https://ipinfo.io/json', { signal: ctrl.signal })
    clearTimeout(t)
    const data = await resp.json()
    return { ip: data.ip || '', country: data.country || '', org: data.org || '' }
  } catch {
    return { ip: '', country: '', org: '', error: '查询失败' }
  }
}

/** 批量探测：并发上限 6，逐项产出（onResult 回调便于界面增量刷新）。 */
export async function probeAll(checks, onResult, concurrency = 6) {
  const results = {}
  const queue = [...checks]
  const worker = async () => {
    while (queue.length) {
      const check = queue.shift()
      const result = await probeOne(check)
      results[result.id] = result
      if (onResult) onResult(result)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, checks.length) }, worker))
  return results
}
