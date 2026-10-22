// 功能模块常用预设。
//
// 内容按官方文档书写：
//   Stash  —— https://stash.wiki（配置样例 / HTTP 重写 / 面板 Tile / 管理脚本）
//   Mihomo —— https://wiki.metacubex.one/config/（general / dns / sniff）
// 约定：内容必须是非空 YAML 映射，且不能含 proxies / proxy-providers /
// proxy-groups / rule-providers / rules（这些由面板的对应页面维护）。
export const SNIPPET_PRESETS = [
  // ---------------- 通用 ----------------
  {
    key: 'general-ipv6',
    name: 'IPv6 支持',
    category: 'general',
    engine: 'all',
    note: '允许 IPv6 解析与连接；产物配置里写的是 ipv6: false，本模块优先级更高。',
    content: `ipv6: true
`,
  },
  {
    key: 'general-geo-update',
    name: 'Geo 数据自动更新',
    category: 'general',
    engine: 'mihomo',
    note: '启动时自动更新 GeoIP/GeoSite 数据，每 24 小时一次，避免分流规则命中过期数据。引擎默认配置里已内置同样的键，留着可以不改引擎默认就单独开关。',
    content: `geodata-mode: true
geo-auto-update: true
geo-update-interval: 24
`,
  },
  {
    key: 'general-sniffer',
    name: '嗅探域名（提升分流准确度）',
    category: 'general',
    engine: 'mihomo',
    note: '从 TLS/HTTP 流量里嗅探真实域名，弥补应用走 IP 直连导致的分流不准；不改写目标地址。引擎默认配置里已启用嗅探，这里可以再补端口与排除域名。',
    content: `sniffer:
  enable: true
  force-dns-mapping: true
  parse-pure-ip: true
  override-destination: false
  sniff:
    HTTP:
      ports:
        - 80
        - 8080-8880
    TLS:
      ports:
        - 443
        - 8443
  skip-domain:
    - "Mijia Cloud"
    - "+.push.apple.com"
`,
  },
  {
    key: 'general-profile',
    name: '持久化选择与 Fake-IP',
    category: 'general',
    engine: 'mihomo',
    note: '记住上次选的节点与 Fake-IP 映射，重启后不用重新选。引擎默认配置里已内置同样的键。',
    content: `profile:
  store-selected: true
  store-fake-ip: true
`,
  },
  {
    key: 'general-tun',
    name: 'TUN 模式（接管全部流量）',
    category: 'general',
    engine: 'mihomo',
    note: '默认停用：会接管设备全部流量，与客户端自带的 TUN 开关互斥，确认后再启用。',
    enabled: false,
    content: `tun:
  enable: true
  stack: mixed
  dns-hijack:
    - "any:53"
  auto-route: true
  auto-detect-interface: true
`,
  },

  // ---------------- DNS ----------------
  {
    key: 'dns-cn-policy',
    name: '国内域名走国内 DNS',
    category: 'dns',
    engine: 'mihomo',
    note: '按 GeoSite 分流解析：国内域名用阿里/腾讯 DoH，境外域名走 Cloudflare/Google，避免境外域名被污染。',
    content: `dns:
  nameserver-policy:
    "geosite:cn,private":
      - https://dns.alidns.com/dns-query
      - https://doh.pub/dns-query
    "geosite:geolocation-!cn":
      - https://dns.cloudflare.com/dns-query
      - https://dns.google/dns-query
`,
  },
  {
    key: 'dns-fake-ip-filter',
    name: 'Fake-IP 过滤（兼容图片/游戏/局域网）',
    category: 'dns',
    engine: 'mihomo',
    note: '把 STUN、NTP、游戏与推送域名排除在 Fake-IP 之外，避免 App 拿到假 IP 后连不上；局域网与基础 NTP 项内置已有，不重复添加。',
    content: `dns:
  fake-ip-filter:
    - "+.stun.*.*"
    - "+.stun.*.*.*"
    - "+.pool.ntp.org"
    - "+.n.n.srv.nintendo.net"
    - "+.xboxlive.com"
`,
  },
  {
    key: 'dns-leak-guard',
    name: 'DNS 泄漏防护',
    category: 'dns',
    engine: 'mihomo',
    note: 'DNS 请求按规则走（respect-rules），直连域名单独用国内 DoH 解析，避免泄漏与污染；引导用的默认 DNS 由面板内置，不重复配置。',
    content: `dns:
  respect-rules: true
  direct-nameserver:
    - https://dns.alidns.com/dns-query
`,
  },

  // ---------------- 面板（Stash 首页磁贴）----------------
  {
    key: 'panel-tile-ip',
    name: '首页磁贴：出口 IP',
    category: 'panel',
    engine: 'stash',
    note: 'Stash 首页磁贴，显示当前出口 IP 与所在地区；请求经代理发出。',
    content: `script-providers:
  tile-ip:
    interval: 86400
    payload: |
      $httpClient.get('https://api.ip.sb/geoip', function (error, response, data) {
        if (error || !data) {
          $done({ title: '出口 IP', content: '获取失败', backgroundColor: '#7f7f7f' });
          return;
        }
        var info = {};
        try { info = JSON.parse(data); } catch (e) { info = {}; }
        $done({
          title: info.country_code || '出口 IP',
          content: (info.ip || '') + (info.city ? ' · ' + info.city : ''),
          icon: 'network',
          backgroundColor: '#2f6feb',
        });
      });

tiles:
  - name: tile-ip
    interval: 600
    title: '出口 IP'
    content: '获取中…'
    icon: 'network'
    backgroundColor: '#2f6feb'
`,
  },
  {
    key: 'panel-tile-latency',
    name: '首页磁贴：连通性延迟',
    category: 'panel',
    engine: 'stash',
    note: 'Stash 首页磁贴，探测 generate_204 的往返延迟，判断当前节点是否通畅。',
    content: `script-providers:
  tile-latency:
    interval: 86400
    payload: |
      var started = Date.now();
      $httpClient.get('https://www.gstatic.com/generate_204', function (error, response, data) {
        var ms = Date.now() - started;
        if (error) {
          $done({ title: '连通性', content: '不通', backgroundColor: '#b34a4a' });
          return;
        }
        $done({
          title: '连通性',
          content: ms + ' ms',
          icon: 'speedometer',
          backgroundColor: '#2f9e5e',
        });
      });

tiles:
  - name: tile-latency
    interval: 300
    title: '连通性'
    content: '检测中…'
    icon: 'speedometer'
    backgroundColor: '#2f9e5e'
`,
  },
  {
    key: 'panel-tile-collapsed',
    name: '折叠磁贴：第三方服务可用性',
    category: 'panel',
    engine: 'stash',
    note: '默认停用：折叠进第三方服务面板，用当前节点探测该服务是否可用（例如流媒体解锁）。',
    enabled: false,
    content: `script-providers:
  tile-service:
    interval: 86400
    payload: |
      $httpClient.get('https://www.netflix.com/title/80018499', function (error, response, data) {
        if (error || !response) {
          $done({ title: 'Netflix', content: '不可用', backgroundColor: '#7f7f7f' });
          return;
        }
        var code = response.status ? response.status : 0;
        if (code >= 200 && code < 400) {
          $done({ title: 'Netflix', content: '可用', backgroundColor: '#2f9e5e' });
        } else {
          $done({ title: 'Netflix', content: '不可用', backgroundColor: '#b34a4a' });
        }
      });

tiles:
  - name: tile-service
    interval: 900
    title: 'Netflix'
    content: '检测中…'
    icon: 'play.rectangle'
    backgroundColor: '#7f7f7f'
    collapsed: true
`,
  },

  // ---------------- 脚本 ----------------
  {
    key: 'script-ua-mobile',
    name: '请求 UA 伪装为移动版 Safari',
    category: 'script',
    engine: 'stash',
    note: '默认停用：会改写全部请求的 User-Agent，部分站点可能因此触发风控。',
    enabled: false,
    content: `script-providers:
  ua-mobile:
    interval: 86400
    payload: |
      $request.headers["User-Agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
      $done();

script:
  - type: request
    name: ua-mobile
    match: "^https?://"
`,
  },
  {
    key: 'script-ua-apple',
    name: 'Apple 服务 UA（音乐/视频）',
    category: 'script',
    engine: 'stash',
    note: '默认停用：只对 Apple 系域名改写 UA，其它请求不动。',
    enabled: false,
    content: `script-providers:
  ua-apple:
    interval: 86400
    payload: |
      $request.headers["User-Agent"] = "AppleTV6,2/15.2";
      $done();

script:
  - type: request
    name: ua-apple
    match: '^https?://[a-z0-9-]+\\.(apple\\.com|mzstatic\\.com|icloud\\.com)/'

`,
  },
  {
    key: 'script-strip-headers',
    name: '请求头去跟踪',
    category: 'script',
    engine: 'stash',
    note: '默认停用：删掉 X-Client-*、X-Request-ID 之类的自有请求头，减少被跟踪。',
    enabled: false,
    content: `script-providers:
  strip-headers:
    interval: 86400
    payload: |
      $request.headers["X-Client-Version"] = undefined;
      $request.headers["X-Request-ID"] = undefined;
      $request.headers["X-Device-Id"] = undefined;
      $done();

script:
  - type: request
    name: strip-headers
    match: "^https?://"
`,
  },

  // ---------------- 复写 ----------------
  {
    key: 'rewrite-ad-block',
    name: '常见广告域名拦截',
    category: 'rewrite',
    engine: 'stash',
    note: '按 URL 正则拒绝常见广告与统计请求；命中即返回 404，不影响正常请求。',
    content: `http:
  url-rewrite:
    - '^https?://[a-z0-9-]+\\.doubleclick\\.net/.* - reject'
    - '^https?://[a-z0-9-]+\\.googlesyndication\\.com/.* - reject'
    - '^https?://[a-z0-9-]+\\.googleadservices\\.com/.* - reject'
    - '^https?://[a-z0-9-]+\\.adservice\\.google\\.com/.* - reject'
    - '^https?://[a-z0-9-]+\\.amazon-adsystem\\.com/.* - reject'
    - '^https?://[a-z0-9-]+\\.scorecardresearch\\.com/.* - reject'
    - '^https?://[a-z0-9-]+\\.ads-twitter\\.com/.* - reject'
`,
  },
  {
    key: 'rewrite-privacy-header',
    name: '隐私请求头（DNT）',
    category: 'rewrite',
    engine: 'stash',
    note: '给请求加上 Do Not Track 标头，并把 Referer 置空，减少被追踪。',
    content: `http:
  header-rewrite:
    - '^https?://.* request-add DNT 1'
    - '^https?://.* request-del Referer'
`,
  },
  {
    key: 'rewrite-force-http',
    name: '强制 HTTP 引擎（80 端口）',
    category: 'rewrite',
    engine: 'stash',
    note: '默认停用：让 80 端口的连接走 HTTP 引擎，才能对其做重写；部分 App 需要。',
    enabled: false,
    content: `http:
  force-http-engine:
    - "*:80"
`,
  },
]

export const PRESETS_BY_CATEGORY = SNIPPET_PRESETS.reduce((acc, p) => {
  (acc[p.category] = acc[p.category] || []).push(p)
  return acc
}, {})
