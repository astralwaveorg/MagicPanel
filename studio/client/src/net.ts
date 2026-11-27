export type Profile={name:string,platform:string,policy:string,adapters:Record<string,string>,native_rules?:Record<string,string[]>}
export type Network={name:string,rules:{first?:string[],omit?:string[],targets?:Record<string,string>},groups:Record<string,{prefer:string[],type:string}>}
export type Device={id:string,name:string,template:string,profile:string,network?:string,engine:string,enabled:boolean}
export type Group={name:string,type:string,proxies?:string[],use?:string[]}
export type Target={id:string,name:string,engine:string,platform:string,policy:string,groups:string[]}
export type Detail={name:string,engine:string,order:string[],resolved_rules?:Record<string,string>,nodes:{name:string,type:string}[],groups:Group[],settings:Record<string,unknown>}
export type State={user:string,revision:number,live:{id:number,revision:number},profiles:Record<string,Profile>,networks:Record<string,Network>,policies:Record<string,{name:string,order:string[]}>,templates:Target[],devices:Device[],rules:Record<string,string>,pool_count:number,sources:any[],resources:any[],releases:any[],auto:{enabled:boolean,error:string}}
export async function api<T=any>(path:string,body?:unknown):Promise<T>{
 const res=await fetch('/api/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Studio':'1'},body:JSON.stringify(body)})
 if(!res.ok){const r=await res.json().catch(()=>({}));throw Error(r.detail||(res.status===401?'请登录':'请求未完成'))}return res.json()
}
export type Option=[string,string]
export type Field={key:string,label:string,kind?:'select'|'area'|'password'|'text'|'ordered',options?:Option[],value?:string,hint?:string,required?:boolean}
export type Form={title:string,desc?:string,fields:Field[],action?:string,run:(v:Record<string,string>)=>Promise<void>|void}
export const entries=<T>(r:Record<string,T>)=>Object.entries(r)
export const choices=(arr:string[]):Option[]=>arr.map(x=>[x,x])
export const lines=(s:string)=>s.split('\n').map(x=>x.trim()).filter(Boolean)
