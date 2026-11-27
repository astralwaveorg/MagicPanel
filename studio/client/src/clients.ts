export type Client={id:string,name:string,engine:string,os:string[],site:string,scheme?:string,importOn?:string[],help:string}
const desktops=['windows','macos','linux'],mobile=['ios','android']
export const clients:Client[]=[
 {id:'verge',name:'Clash Verge Rev',engine:'mihomo',os:desktops,site:'https://www.clashverge.dev/',scheme:'clash-verge',help:'在「订阅」中粘贴地址，然后选择导入的配置。'},
 {id:'flclash',name:'FlClash',engine:'mihomo',os:[...desktops,'android'],scheme:'flclash',site:'https://github.com/chen08209/FlClash',help:'在「配置」中添加 URL，粘贴地址并保存。'},
 {id:'cmfa',name:'Clash Meta for Android',engine:'mihomo',os:['android'],scheme:'clashmeta',site:'https://github.com/MetaCubeX/ClashMetaForAndroid',help:'在「配置」中从 URL 新建，保存后选择这份配置。'},
 {id:'stash',name:'Stash',engine:'stash',os:['ios','tvos','macos','android','windows'],scheme:'stash',importOn:['ios','macos','windows'],site:'https://stash.ws/download',help:'在 Stash 的配置列表中从 URL 下载配置，再将其设为当前配置。'},
 {id:'shadowrocket',name:'Shadowrocket',engine:'shadowrocket',os:['ios'],scheme:'shadowrocket',site:'https://apps.apple.com/app/id932747118',help:'在「配置」中添加远程配置，再选择使用。请勿把这个地址添加到首页的节点列表。'},
 {id:'surge',name:'Surge 6',engine:'surge',os:['ios','macos'],scheme:'surge',site:'https://nssurge.com/',help:'从 URL 安装托管配置。VLESS 需要 Surge iOS 6.0 或 Mac 6.12 及以上版本。'},
 {id:'surge5',name:'Surge 5 兼容配置',engine:'surge5',os:['ios','macos'],scheme:'surge',site:'https://nssurge.com/',help:'适用于较早版本的 Surge。从 URL 安装托管配置。此格式不包含 VLESS。'},
 {id:'clashmi',name:'Clash Mi',engine:'mihomo',os:[...desktops,...mobile,'tvos'],scheme:'clashmi',site:'https://clashmi.app',help:'在客户端添加远程配置，粘贴订阅地址。'},
 {id:'clashx',name:'ClashX.Meta',engine:'mihomo',os:['macos'],scheme:'clashx',site:'https://github.com/MetaCubeX/ClashX.Meta',help:'在菜单栏的配置菜单中添加远程配置。'},
 {id:'nyan',name:'Clash Nyanpasu',engine:'mihomo',os:desktops,scheme:'clash-nyanpasu',site:'https://github.com/libnyanpasu/clash-nyanpasu',help:'选择 Mihomo 内核，在配置列表中导入远程地址。'},
 {id:'party',name:'Clash Party',engine:'mihomo',os:desktops,scheme:'mihomo',site:'https://github.com/mihomo-party-org/clash-party',help:'在订阅管理中粘贴地址并导入。'},
 {id:'openclash',name:'OpenClash',engine:'mihomo',os:['openwrt'],site:'https://github.com/vernesong/OpenClash',help:'在路由器的 OpenClash 配置订阅中添加地址。DNS、监听端口和透明代理由路由器管理。'},
 {id:'nikki',name:'Nikki',engine:'mihomo',os:['openwrt'],site:'https://github.com/nikkinikki-org/OpenWrt-nikki',help:'在 Nikki 的配置订阅中添加地址。请在路由器上确认后再切换配置。'},
 {id:'mihomo',name:'其他 Mihomo 客户端',engine:'mihomo',os:[...desktops,...mobile,'tvos'],site:'https://wiki.metacubex.one/',help:'在应用中选择从 URL 添加完整配置，粘贴订阅地址。'}]
export function detected(){const ua=navigator.userAgent;return /Android/i.test(ua)?'android':/iPhone|iPad|iPod/i.test(ua)||(/Mac/i.test(ua)&&navigator.maxTouchPoints>1)?'ios':/Mac/i.test(ua)?'macos':/Windows/i.test(ua)?'windows':/Linux/i.test(ua)?'linux':'windows'}
export function isTextConfig(engine:string){return ['surge','surge5','shadowrocket'].includes(engine)}

type AddressOptions={base:string,platform:string,template:string,network:string,name:string,nodes:boolean,sorted:boolean,scv:string,tfo:string}
export function subscriptionAddress(engine:string, opts:AddressOptions){
 const {base,platform,template,network,name}=opts
 if(!base || !engine)return ''
 const q=new URLSearchParams({platform,type:engine,network})
 if(template!=='platform-'+platform)q.set('template',template)
 if(name.trim())q.set('name',name.trim())
 if(!isTextConfig(engine)){
  if(opts.nodes)q.set('list','true')
  if(opts.sorted)q.set('sort','true')
  if(opts.scv!=='inherit')q.set('scv',opts.scv)
  if(opts.tfo!=='inherit'&&engine==='mihomo')q.set('tfo',opts.tfo)
 }
 return base+'?'+q
}

export function install(c:Client,platform:string,url:string){
 if(!url||!c.scheme||!c.os.includes(platform)||platform==='tvos'||(c.importOn&&!c.importOn.includes(platform)))return ''
 const encoded=encodeURIComponent(url)
 if(c.scheme==='surge')return (platform==='macos'&&c.engine==='surge5'?'surgeconfig':'surge')+':///install-config?url='+encoded
 if(c.scheme==='shadowrocket')return 'shadowrocket://config/add/'+url
 return c.scheme+'://install-config?url='+encoded
}
