// 当前网络由浏览器发起请求；跨域响应只能证明收到响应。
export const BROWSER_CHECKS = [
  // ai
  { id: 'gemini', name: 'Google Gemini', icon: '✦', category: 'ai',
    url: 'https://gemini.google.com/favicon.ico', site: 'https://gemini.google.com/' },
  { id: 'chatgpt', trace: true, name: 'ChatGPT', icon: '◎', category: 'ai',
    url: 'https://chatgpt.com/favicon.ico', site: 'https://chatgpt.com/' },
  { id: 'claude', trace: true, name: 'Claude', icon: '✳', category: 'ai',
    url: 'https://claude.ai/favicon.ico', site: 'https://claude.ai/' },
  { id: 'grok', trace: true, name: 'Grok', icon: '𝕏', category: 'ai',
    url: 'https://grok.com/favicon.ico', site: 'https://grok.com/' },
  { id: 'perplexity', trace: true, name: 'Perplexity', icon: '◈', category: 'ai',
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
    url: 'https://www.hbomax.com/favicon.ico', site: 'https://www.hbomax.com/' },
  { id: 'hulu', name: 'Hulu', icon: 'H', category: 'stream',
    url: 'https://www.hulu.com/', site: 'https://www.hulu.com/' },
  { id: 'primevideo', name: 'Prime Video', icon: 'P', category: 'stream',
    url: 'https://www.primevideo.com/', site: 'https://www.primevideo.com/' },
  { id: 'twitch', name: 'Twitch', icon: 'T', category: 'stream',
    url: 'https://www.twitch.tv/', site: 'https://www.twitch.tv/' },
  { id: 'bbc', name: 'BBC iPlayer', icon: 'B', category: 'stream',
    url: 'https://www.bbc.co.uk/iplayer', site: 'https://www.bbc.co.uk/iplayer' },
  // region
  { id: 'tvbanywhere', name: 'TVBAnywhere', icon: 'T', category: 'region',
    url: 'https://www.tvbanywhere.com/favicon.ico', site: 'https://www.tvbanywhere.com/' },
  { id: 'viu', name: 'Viu.com', icon: 'V', category: 'region',
    url: 'https://www.viu.com/favicon.ico', site: 'https://www.viu.com/' },
  // web
  { id: 'google_search', name: 'Google 搜索', icon: 'G', category: 'web',
    url: 'https://www.google.com/favicon.ico', site: 'https://www.google.com/' },
  { id: 'gmail_web', name: 'Gmail', icon: 'M', category: 'web',
    url: 'https://mail.google.com/mail/', site: 'https://mail.google.com/mail/' },
  { id: 'youtube_web', name: 'YouTube', icon: '▶', category: 'web',
    url: 'https://www.youtube.com/favicon.ico', site: 'https://www.youtube.com/' },
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

// 同域诊断接口允许跨域读取时才展示 IP，不能以通用查询站替代。
export async function probeServiceExit(check, timeoutMs = 2500) {
  const target = new URL('/cdn-cgi/trace', check.url)
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch(target.href, {
      mode: 'cors', redirect: 'error', cache: 'no-store', credentials: 'omit',
      referrerPolicy: 'no-referrer', signal: ctrl.signal,
    })
    if (!resp.ok || !resp.headers.get('content-type')?.startsWith('text/plain')) return null
    const reader = resp.body?.getReader()
    if (!reader) return null
    const decoder = new TextDecoder()
    let body = ''
    while (body.length <= 2048) {
      const { done, value } = await reader.read()
      if (done) break
      body += decoder.decode(value.subarray(0, 2049), { stream: true })
    }
    if (body.length > 2048) return null
    const fields = Object.fromEntries(body.split(/\r?\n/).filter(s => s.includes('='))
      .map(s => [s.slice(0, s.indexOf('=')), s.slice(s.indexOf('=') + 1)]))
    const ip = fields.ip || ''
    const ipv4 = /^(\d{1,3}\.){3}\d{1,3}$/.test(ip) && ip.split('.').every(p => Number(p) <= 255)
    const ipv6 = ip.includes(':') && /^[\da-f:]+$/i.test(ip)
      && new URL('http://[' + ip + ']').hostname.startsWith('[')
    if (fields.h?.toLowerCase() !== target.hostname || !(ipv4 || ipv6)) return null
    return { ip, domain: target.hostname, country: /^[A-Z]{2}$/.test(fields.loc || '') ? fields.loc : '' }
  } catch {
    return null
  } finally {
    clearTimeout(timer)
    ctrl.abort()
  }
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
      if (check.trace && result.state === 'reachable') {
        result.route = await probeServiceExit(check)
      }
      results[result.id] = result
      if (onResult) onResult(result)
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, checks.length) }, worker))
  return results
}
