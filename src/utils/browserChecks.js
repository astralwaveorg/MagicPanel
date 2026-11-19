// 当前网络由浏览器发起请求；跨域响应只能证明收到响应。
export const BROWSER_CHECKS = [
  // ai
  { id: 'gemini', name: 'Google Gemini', icon: '✦', category: 'ai',
    url: 'https://gemini.google.com/favicon.ico', site: 'https://gemini.google.com/' },
  { id: 'chatgpt', name: 'ChatGPT', icon: '◎', category: 'ai',
    url: 'https://chatgpt.com/favicon.ico', site: 'https://chatgpt.com/' },
  { id: 'claude', name: 'Claude', icon: '✳', category: 'ai',
    url: 'https://claude.ai/favicon.ico', site: 'https://claude.ai/' },
  { id: 'grok', name: 'Grok', icon: '𝕏', category: 'ai',
    url: 'https://grok.com/favicon.ico', site: 'https://grok.com/' },
  { id: 'perplexity', name: 'Perplexity', icon: '◈', category: 'ai',
    url: 'https://www.perplexity.ai/favicon.ico', site: 'https://www.perplexity.ai/' },
  { id: 'copilot', name: 'Copilot', icon: '⌘', category: 'ai',
    url: 'https://copilot.microsoft.com/favicon.ico', site: 'https://copilot.microsoft.com/' },
  // stream
  { id: 'netflix', name: 'Netflix', icon: 'N', category: 'stream',
    url: 'https://www.netflix.com/favicon.ico', site: 'https://www.netflix.com/' },
  { id: 'disney', name: 'Disney+', icon: 'D', category: 'stream',
    url: 'https://www.disneyplus.com/favicon.ico', site: 'https://www.disneyplus.com/' },
  { id: 'youtube_premium', name: 'YouTube Premium', icon: '▶', category: 'stream',
    url: 'https://www.youtube.com/favicon.ico', site: 'https://www.youtube.com/' },
  { id: 'spotify', name: 'Spotify', icon: '♫', category: 'stream',
    url: 'https://www.spotify.com/favicon.ico', site: 'https://www.spotify.com/' },
  { id: 'tiktok', name: 'TikTok', icon: '♪', category: 'stream',
    url: 'https://www.tiktok.com/favicon.ico', site: 'https://www.tiktok.com/' },
  { id: 'dazn', name: 'Dazn', icon: '▮', category: 'stream',
    url: 'https://www.dazn.com/favicon.ico', site: 'https://www.dazn.com/' },
  { id: 'biliintl', name: 'Bilibili 海外版', icon: 'B', category: 'stream',
    url: 'https://www.bilibili.tv/favicon.ico', site: 'https://www.bilibili.tv/' },
  { id: 'hbo', name: 'HBO Max', icon: '▣', category: 'stream',
    url: 'https://play.max.com/favicon.ico', site: 'https://play.max.com/' },
  // region
  { id: 'tvbanywhere', name: 'TVBAnywhere', icon: 'T', category: 'region',
    url: 'https://www.tvbanywhere.com/favicon.ico', site: 'https://www.tvbanywhere.com/' },
  { id: 'viu', name: 'Viu.com', icon: 'V', category: 'region',
    url: 'https://www.viu.com/favicon.ico', site: 'https://www.viu.com/' },
  // web
  { id: 'reddit', name: 'Reddit', icon: 'R', category: 'web',
    url: 'https://www.reddit.com/favicon.ico', site: 'https://www.reddit.com/' },
  { id: 'wikipedia', name: '维基百科', icon: 'W', category: 'web',
    url: 'https://zh.wikipedia.org/favicon.ico', site: 'https://zh.wikipedia.org/' },
]

export const BROWSER_TIMEOUT_MS = 8000

export async function probeOne(check, timeoutMs = BROWSER_TIMEOUT_MS) {
  const started = performance.now()
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let state = 'unknown'
  try {
    const options = {
      mode: 'no-cors', redirect: 'follow', cache: 'no-store',
      credentials: 'omit', referrerPolicy: 'no-referrer', signal: controller.signal,
    }
    try {
      await fetch(check.url, options)
    } catch (error) {
      // 请求被拒绝不一定是断网；同一站点的普通入口可以再试一次。
      if (controller.signal.aborted || !check.site || check.site === check.url) throw error
      await fetch(check.site, options)
    }
    state = 'reachable'
  } catch {
    if (controller.signal.aborted) state = 'timeout'
  } finally {
    clearTimeout(timer)
    controller.abort()
  }
  return { id: check.id, state, latency_ms: Math.round(performance.now() - started) }
}

/** 出口 IP 与国家（ipinfo.io 开放 CORS）。 */
export async function probeExitIp(timeoutMs = BROWSER_TIMEOUT_MS) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch('https://ipinfo.io/json', {
      signal: ctrl.signal, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer',
    })
    if (!resp.ok) throw new Error('查询失败')
    const data = await resp.json()
    return { ip: data.ip || '', country: data.country || '', org: data.org || '' }
  } catch {
    return { ip: '', country: '', org: '', error: '查询失败' }
  } finally {
    clearTimeout(timer)
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
