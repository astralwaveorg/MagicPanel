// YAML 源码着色。
//
// 为什么自己写而不是引 highlight.js/prism：
//   - 产物动辄四千多行，Prism 的通用 YAML 语法开销在这种体量下不划算；
//   - 面板只发 Clash/Stash/Mihomo 配置，语法形态很窄（键值、列表、引号串、
//     行内注释、空流式集合、锚点/别名），一个逐行词法扫描就能覆盖；
//   - 不引新依赖 = 不给构建体积和供应链再加一份东西。
//
// 输出是**已转义的 HTML 字符串**，配合 v-html 一次性插入——
// 四千行如果拆成上万个 Vue 节点，弹窗会明显卡；整段 innerHTML 交给浏览器
// 解析，快一个数量级。转义在 esc() 里做，配置里的节点名、URL 都是用户可写
// 的内容，不转义就是 XSS 口子。

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;' }

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ESC[c])
}

const RE_BOOL = /^(true|false|yes|no|on|off)$/i
const RE_NUM = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/
const RE_IP = /^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/
const RE_ANCHOR = /^[&*][\w-]+$/
const RE_URL = /^https?:\/\//i

// 纯量着色
function scalar(w) {
  if (!w) return ''
  if (RE_BOOL.test(w)) return `<span class="y-bool">${esc(w)}</span>`
  if (w === 'null' || w === '~') return `<span class="y-null">${esc(w)}</span>`
  if (RE_NUM.test(w)) return `<span class="y-num">${esc(w)}</span>`
  if (RE_IP.test(w)) return `<span class="y-ip">${esc(w)}</span>`
  if (RE_ANCHOR.test(w)) return `<span class="y-anchor">${esc(w)}</span>`
  if (RE_URL.test(w)) return `<span class="y-url">${esc(w)}</span>`
  if (w === '{}' || w === '[]') return `<span class="y-flow">${esc(w)}</span>`
  return esc(w)
}

// 找行内注释的起点：# 前面是空白（或行首）才算注释，
// 节点名里的 #（如 "abc#def"）不是。
function findCommentStart(s) {
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i]
    if (c === '"' || c === "'") {
      i = skipQuoted(s, i)
      continue
    }
    if (c === '#' && (i === 0 || /\s/.test(s[i - 1]))) return i
  }
  return -1
}

// 返回引号串结束位置（含右引号）
function skipQuoted(s, i) {
  const q = s[i]
  let j = i + 1
  while (j < s.length) {
    if (s[j] === '\\') { j += 2; continue }
    if (s[j] === q) return j + 1
    j += 1
  }
  return j
}

// 值部分。
// 注意 YAML 语义：纯量按空格分词是错的——`name: 🇭🇰 香港 06 [Home]`
// 是**一个**字符串，不是四个 token。所以只有「单个词」才按类型着色，
// 带空格的一律整体当字符串（节点名这类自由文本），否则会把名字里的
// "06" 染成数字，看着像端口号。
function scanValue(v) {
  const lead = /^\s*/.exec(v)[0]
  const rest = v.slice(lead.length)
  const ci = findCommentStart(rest)
  const body = ci >= 0 ? rest.slice(0, ci) : rest
  const comment = ci >= 0 ? rest.slice(ci) : ''
  const trimmed = body.trim()

  let out = esc(lead)
  if (!trimmed) {
    out += esc(body)
  } else if (trimmed[0] === '"' || trimmed[0] === "'") {
    const end = skipQuoted(trimmed, 0)
    out += `<span class="y-str">${esc(trimmed.slice(0, end))}</span>`
    out += esc(trimmed.slice(end))
  } else if (/\s/.test(trimmed)) {
    out += esc(trimmed)
  } else {
    out += scalar(trimmed)
  }
  if (comment) out += `<span class="y-cm">${esc(comment)}</span>`
  return out
}

// 找「键: 值」的分隔冒号。键里也可能带冒号（如 URL 形态的键），
// 所以要跳过引号内与流式集合内的冒号，并且只认「冒号+空格或行尾」。
function splitKeyValue(rest) {
  let quote = null
  let depth = 0
  for (let i = 0; i < rest.length; i += 1) {
    const c = rest[i]
    if (quote) {
      if (c === '\\') { i += 1; continue }
      if (c === quote) quote = null
      continue
    }
    if (c === '"' || c === "'") { quote = c; continue }
    if (c === '[' || c === '{') { depth += 1; continue }
    if (c === ']' || c === '}') { depth -= 1; continue }
    // 行内注释里的冒号不是键值分隔符
    if (c === '#' && i > 0 && rest[i - 1] === ' ') break
    if (c === ':' && depth === 0 && (i + 1 >= rest.length || rest[i + 1] === ' ')) {
      return [rest.slice(0, i), rest.slice(i + 1)]
    }
  }
  return [null, rest]
}

function highlightLine(raw) {
  const indent = /^(\s*)/.exec(raw)[1]
  let rest = raw.slice(indent.length)
  if (!rest) return esc(indent)

  // 整行注释
  if (rest.startsWith('#')) {
    return esc(indent) + `<span class="y-cm">${esc(rest)}</span>`
  }

  // 列表前缀（- / - - / -   ）
  let list = ''
  const lm = /^(-+\s+)([\s\S]*)$/.exec(rest)
  if (lm) {
    list = `<span class="y-punct">${esc(lm[1])}</span>`
    rest = lm[2]
  }

  const [key, value] = splitKeyValue(rest)
  if (key === null) {
    return esc(indent) + list + scanValue(rest)
  }
  return esc(indent) + list
    + `<span class="y-key">${esc(key)}</span>`
    + `<span class="y-punct">:</span>`
    + scanValue(value)
}

/** 把 YAML 文本转成已着色的 HTML 字符串（已转义，可直接 v-html）。 */
export function highlightYaml(text) {
  const lines = String(text || '').split('\n')
  const out = new Array(lines.length)
  for (let i = 0; i < lines.length; i += 1) out[i] = highlightLine(lines[i])
  return out.join('\n')
}

/** 行号栏：与代码行一一对应。 */
export function lineGutter(text) {
  const lines = String(text || '').split('\n')
  const out = new Array(lines.length)
  for (let i = 0; i < lines.length; i += 1) out[i] = String(i + 1)
  return out.join('\n')
}
