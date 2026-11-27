import type {Profile} from './net'
export const engineNames:Record<string,string>={mihomo:'Mihomo',stash:'Stash',surge:'Surge 6',surge5:'Surge 5 兼容',shadowrocket:'Shadowrocket'}
export function formats(p:Profile){
 const extra:Record<string,string[]>={macos:['surge','surge5'],ios:['mihomo','surge','surge5','shadowrocket'],tvos:['mihomo']}
 return [...new Set([...Object.keys(p.adapters),...(extra[p.platform]||[])])]
}
