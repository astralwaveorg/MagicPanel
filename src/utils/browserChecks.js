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
/**
 * 浏览器端探测清单。
 *
 * 每项有两个 URL：
 *   url      —— fetch 用的轻量路径（favicon/根路径），no-cors 快但穿不过跨域重定向；
 *   frame_url—— iframe 用的主域名：iframe 是导航语义，跨域重定向能跟随
 *              （2026-11-19 线上实测：gemini 用 fetch 10 秒失败，同一浏览器
 *               导航它只用 4 秒——差别只在 no-cors 的重定向处理）。
 */
export const BROWSER_CHECKS = [
  // ai
  { id: 'gemini', name: 'Google Gemini', icon: '✦', category: 'ai',
    url: 'https://gemini.google.com/favicon.ico', frame_url: 'https://gemini.google.com/' },
  { id: 'chatgpt', name: 'ChatGPT', icon: '◎', category: 'ai',
    url: 'https://chatgpt.com/favicon.ico', frame_url: 'https://chatgpt.com/' },
  { id: 'claude', name: 'Claude', icon: '✳', category: 'ai',
    url: 'https://claude.ai/favicon.ico', frame_url: 'https://claude.ai/' },
  { id: 'grok', name: 'Grok', icon: '𝕏', category: 'ai',
    url: 'https://grok.com/favicon.ico', frame_url: 'https://grok.com/' },
  { id: 'perplexity', name: 'Perplexity', icon: '◈', category: 'ai',
    url: 'https://www.perplexity.ai/favicon.ico', frame_url: 'https://www.perplexity.ai/' },
  { id: 'copilot', name: 'Copilot', icon: '⌘', category: 'ai',
    url: 'https://copilot.microsoft.com/favicon.ico', frame_url: 'https://copilot.microsoft.com/' },
  // stream
  { id: 'netflix', name: 'Netflix', icon: 'N', category: 'stream',
    url: 'https://www.netflix.com/favicon.ico', frame_url: 'https://www.netflix.com/' },
  { id: 'disney', name: 'Disney+', icon: 'D', category: 'stream',
    url: 'https://www.disneyplus.com/favicon.ico', frame_url: 'https://www.disneyplus.com/' },
  { id: 'youtube_premium', name: 'YouTube Premium', icon: '▶', category: 'stream',
    url: 'https://www.youtube.com/favicon.ico', frame_url: 'https://www.youtube.com/' },
  { id: 'spotify', name: 'Spotify', icon: '♫', category: 'stream',
    url: 'https://www.spotify.com/favicon.ico', frame_url: 'https://www.spotify.com/' },
  { id: 'tiktok', name: 'TikTok', icon: '♪', category: 'stream',
    url: 'https://www.tiktok.com/favicon.ico', frame_url: 'https://www.tiktok.com/' },
  { id: 'dazn', name: 'Dazn', icon: '▮', category: 'stream',
    url: 'https://www.dazn.com/favicon.ico', frame_url: 'https://www.dazn.com/' },
  { id: 'biliintl', name: 'Bilibili 海外版', icon: 'B', category: 'stream',
    url: 'https://www.bilibili.tv/favicon.ico', frame_url: 'https://www.bilibili.tv/' },
  { id: 'hbo', name: 'HBO Max', icon: '▣', category: 'stream',
    url: 'https://play.max.com/favicon.ico', frame_url: 'https://play.max.com/' },
  // region
  { id: 'tvbanywhere', name: 'TVBAnywhere', icon: 'T', category: 'region',
    url: 'https://www.tvbanywhere.com/favicon.ico', frame_url: 'https://www.tvbanywhere.com/' },
  { id: 'viu', name: 'Viu.com', icon: 'V', category: 'region',
    url: 'https://www.viu.com/favicon.ico', frame_url: 'https://www.viu.com/' },
  // web
  { id: 'reddit', name: 'Reddit', icon: 'R', category: 'web',
    url: 'https://www.reddit.com/favicon.ico', frame_url: 'https://www.reddit.com/' },
  { id: 'wikipedia', name: '维基百科', icon: 'W', category: 'web',
    url: 'https://zh.wikipedia.org/favicon.ico', frame_url: 'https://zh.wikipedia.org/' },
]

export const BROWSER_TIMEOUT_MS = 8000

/**
 * 浏览器端「可达」探测。
 *
 * 为什么不能只用 fetch(no-cors)（2026-11-19 线上实测）：
 * no-cors 模式下浏览器**不跟随跨域重定向**——Google 系等站点会把
 * /favicon.ico 302 到另一个域，fetch 直接 reject（实测 gemini 10 秒后
 * "Failed to fetch"，而同一浏览器**导航**该站点只用 4 秒就成功）。
 * 于是"服务器明明有响应"被判成不可达，两视角对照全是假差异。
 *
 * 现在用双路径：
 * 1) fetch(no-cors) —— 快，覆盖不重定向的站点；
 * 2) 3 秒还没成功就用 iframe 探测 —— iframe 走导航语义，跨域重定向
 *    能跟随（与真实浏览一致），onload 即"服务器有响应"。
 * 两者并行取先到的确定结论。
 */
const FETCH_FAST_TIMEOUT_MS = 3000
// iframe 兜底的超时：只用来区分"服务器有响应"与"连不上"，5 秒足够
// iframe 兜底的超时：X-Frame-Options 会让跨域 iframe 直接不加载，
// 等太久只是拖慢整体（实测 Google 系全部带 SAMEORIGIN）
const FRAME_TIMEOUT_MS = 3500

function probeByFrame(url, timeoutMs) {
  // 探测项可指定 frame_url（主域名）：iframe 走导航语义，跨域重定向能跟随
  const target = url
  return new Promise((resolve) => {
    let frame = null
    let timer = null
    let settled = false
    const finish = (state, detail) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (frame) { try { frame.remove() } catch { /* 忽略 */ } }
      resolve({ state, detail })
    }
    timer = setTimeout(() => finish('timeout', '加载超时'), timeoutMs)
    try {
      frame = document.createElement('iframe')
      frame.setAttribute('aria-hidden', 'true')
      frame.style.cssText = 'position:absolute;width:1px;height:1px;opacity:0;border:0;left:-9999px'
      frame.onload = () => finish('reachable', '服务器有响应')
      frame.onerror = () => finish('unreachable', '网络不可达')
      frame.src = target
      document.body.appendChild(frame)
    } catch (err) {
      finish('unreachable', String(err).slice(0, 60))
    }
  })
}

/**
 * 组合两条探测路径的结论（纯函数，便于单测）。
 *
 * fetch(no-cors) 快但穿不过跨域重定向；iframe 能穿透但慢。
 * 判定优先级：任一路明确"服务器有响应" → 可达；两路都失败 → 不可达；
 * iframe 超时而 fetch 仍在飞 → 超时。
 */
export function combineProbeResults(fetchState, frameState) {
  if (fetchState === 'reachable' || frameState === 'reachable') {
    return { state: 'reachable', reason: frameState === 'reachable'
      ? 'responded_redirect' : '', detail: '' }
  }
  if (frameState === 'timeout' || fetchState === 'timeout') {
    return { state: 'timeout', reason: '', detail: '加载超时' }
  }
  return { state: 'unreachable', reason: 'network_error', detail: '网络不可达' }
}

/** 单项可达性探测：返回 {id, state, latency_ms, reason?, detail?}。 */
export async function probeOne(check, timeoutMs = BROWSER_TIMEOUT_MS) {
  const started = performance.now()
  const frameTarget = check.frame_url || check.url
  const fetchProbe = (async () => {
    try {
      await fetch(check.url, { mode: 'no-cors', redirect: 'follow', cache: 'no-store' })
      return { state: 'reachable', detail: '' }
    } catch (err) {
      return { state: 'failed', err, detail: String(err?.message || err).slice(0, 80) }
    }
  })()
  const fast = fetchProbe.then((r) => r)
  // fetch 3 秒内没结论就走 iframe（重定向站点只有它能穿透）
  const slow = new Promise((resolve) => setTimeout(() => resolve(null), FETCH_FAST_TIMEOUT_MS))
  const first = await Promise.race([fast, slow])
  if (first && first.state === 'reachable') {
    return { id: check.id, state: 'reachable',
             latency_ms: Math.round(performance.now() - started) }
  }
  if (first && first.state === 'failed') {
    // fetch 立刻失败（策略拦截等）：交给 iframe 复核
    const frame = await probeByFrame(frameTarget, Math.min(timeoutMs, FRAME_TIMEOUT_MS))
    const latency_ms = Math.round(performance.now() - started)
    const merged = combineProbeResults('failed', frame.state)
    return { id: check.id, ...merged, latency_ms }
  }
  // fetch 超过 3 秒仍无结论：并行启动 iframe，谁先给出确定结论用谁
  const frameP = probeByFrame(frameTarget, Math.min(timeoutMs, FRAME_TIMEOUT_MS))
  const outcome = await Promise.race([
    frameP,
    fetchProbe.then((r) => (r.state === 'reachable' ? { state: 'reachable' }
      : { state: 'failed', detail: r.detail })),
  ])
  const latency_ms = Math.round(performance.now() - started)
  const merged = combineProbeResults(
    outcome.state === 'reachable' ? 'reachable' : 'failed',
    outcome.state === 'failed' ? 'unreachable' : outcome.state)
  return { id: check.id, ...merged, latency_ms }
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

export async function probeAll(checks, onResult, concurrency = 6,
                                timeoutMs = BROWSER_TIMEOUT_MS) {
  const results = {}
  const queue = [...checks]
  const worker = async () => {
    while (queue.length) {
      const check = queue.shift()
      const result = await probeOne(check, timeoutMs)
      results[result.id] = result
      if (onResult) onResult(result)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, checks.length) }, worker))
  return results
}
