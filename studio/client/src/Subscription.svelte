<script lang="ts">
 import {onMount} from 'svelte'
 import {api,entries,type Profile} from './net'
 import {clients,detected,install} from './clients'
 import Icon from './Icon.svelte'
 import QrShare from './QrShare.svelte'
 import RouteArt from './RouteArt.svelte'
 let {notify,rotate,initial='',release}:{notify:(v:string)=>void,rotate:()=>void,initial?:string,release:number}=$props()
 let profiles=$state<Record<string,Profile>>({}),networks=$state<Record<string,string>>({}),stats=$state<Record<string,Record<string,{error?:string,nodes?:number,excluded?:number,empty?:number}>>>({})
 let pid=$state(''),app=$state(''),network=$state('default'),name=$state(''),base=$state(''),error=$state(''),shown=$state(false),sorted=$state(false),nodes=$state(false),scv=$state('inherit'),tfo=$state('inherit'),loaded=$state(false),justCopied=$state(false)
 let more=$state(false)
 const osOrder=['windows','macos','ios','android','tvos','linux','openwrt']
 let p=$derived(profiles[pid]),available=$derived(clients.filter(c=>p?.adapters[c.engine]&&c.os.includes(p.platform))),client=$derived(available.find(c=>c.id===app)),engine=$derived(client?.engine||''),native=$derived(['surge','surge5','shadowrocket'].includes(engine))
 let info=$derived(p&&stats[p.adapters[engine]]?.[network])
 function pick(id:string,wanted=''){pid=id;if(['linux','openwrt'].includes(profiles[id].platform))more=true;const pf=profiles[id],list=clients.filter(c=>c.os.includes(pf.platform)&&pf.adapters[c.engine]);const defaults:Record<string,string>={macos:'stash',ios:'stash',tvos:'stash',android:'flclash',windows:'verge',linux:'verge'};app=(list.find(c=>c.id===wanted)||list.find(c=>c.id===defaults[pf.platform])||list[0])?.id||'';shown=false;justCopied=false}
 async function load(){try{error='';const r=await api('subscription');profiles=r.deliveryProfiles||r.profiles;networks=r.networks;stats=r.stats||{};base=r.base;let prefs:any={};try{prefs=JSON.parse(localStorage.getItem('studio.delivery')||'{}')||{}}catch{}
 const start=initial||prefs.pid||'platform-'+detected();pick(profiles[start]?start:Object.keys(profiles)[0],prefs.app);network=networks[prefs.network]?prefs.network:'default';loaded=true}catch(e){error=(e as Error).message}}
 onMount(()=>{load()})
 $effect(()=>{if(loaded){try{localStorage.setItem('studio.delivery',JSON.stringify({pid,app,network}))}catch{}}})
 let url=$derived.by(()=>{if(!p||!client||!base||info?.error)return '';const q=new URLSearchParams({platform:p.platform,type:engine,network});if(pid!=='platform-'+p.platform)q.set('template',pid);if(name.trim())q.set('name',name.trim());if(!native){if(nodes)q.set('list','true');if(sorted)q.set('sort','true');if(scv!=='inherit')q.set('scv',scv);if(tfo!=='inherit'&&engine==='mihomo')q.set('tfo',tfo)}return base+'?'+q})
 let valid=$derived(!name.trim()||(/^[\p{L}\p{N}_ .()（）-]{1,80}$/u.test(name.trim())&&!['.','..'].includes(name.trim())))
 let link=$derived(client&&valid&&!(nodes&&!native)?install(client,p.platform,url):'')
 let timer:ReturnType<typeof setTimeout>
 async function copy(){try{await navigator.clipboard.writeText(url);justCopied=true;clearTimeout(timer);timer=setTimeout(()=>justCopied=false,2000);notify('已复制订阅地址')}catch{shown=true;notify('请在「地址与密钥」中选择地址并复制')}}
</script>
<div class="title"><div><h1>订阅</h1><p>选择设备和客户端，导入当前生效的配置。</p></div><span class="version"><i></i> 生效版本 #{release}</span></div>
{#if error}<div class="error" role="alert">{error} <button onclick={load}>重试</button></div>{:else if !loaded}<div class="panel placeholder">正在读取订阅…</div>{:else}
<div class="delivery-grid"><section class="setup-card">
 <div class="card-heading"><span class="tile"><Icon name="devices"/></span><h2>连接设备</h2></div>
 <fieldset class="platform-picker"><legend>设备平台</legend><div>{#each Object.keys(profiles).filter(k=>k==='platform-'+profiles[k].platform&&(more||!['linux','openwrt'].includes(profiles[k].platform))).sort((a,b)=>osOrder.indexOf(profiles[a].platform)-osOrder.indexOf(profiles[b].platform)) as id}<button aria-pressed={pid===id} class:chosen={pid===id} onclick={()=>pick(id)}><Icon name={profiles[id].platform} size={18}/>{profiles[id].name}</button>{/each}<button aria-expanded={more} onclick={()=>more=!more}>{more?'收起':'其他平台'}</button></div></fieldset>
 {#if entries(profiles).some(([id,pf])=>id!=='platform-'+pf.platform)}<label>平台模板<select aria-label="平台模板" value={pid} onchange={e=>pick(e.currentTarget.value)}>{#each entries(profiles) as [id,pf]}<option value={id}>{pf.name}</option>{/each}</select></label>{/if}
 <div class="choice-row"><label>客户端<select aria-label="客户端" bind:value={app} onchange={()=>{shown=false;justCopied=false}}>{#each available as c}<option value={c.id}>{c.name}</option>{/each}</select></label><label>线路方案<select aria-label="线路方案" bind:value={network}>{#each entries(networks) as [id,n]}<option value={id}>{n}</option>{/each}</select></label></div>
 {#if info?.error}<p class="error">这份配置无法导入：{info.error}</p>{/if}
 <div class="delivery-actions"><button class="solid" disabled={!valid||!url} onclick={copy}><Icon name={justCopied?'check':'copy'} size={17}/>{justCopied?'已复制':'复制订阅地址'}</button>{#if link}<a class="button secondary" href={link} rel="noreferrer"><Icon name="launch" size={16}/>打开客户端</a>{/if}<QrShare url={valid?url:''}/></div>
 {#if client}<div class="helper"><Icon name="info" size={16}/><span>{p.platform==='tvos'?'在电视端添加远程配置时，粘贴此地址。':client.help}</span></div>{/if}
</section>
<aside class="delivery-preview"><div class="preview-top"><span class="eyeline">配置预览</span><span class="filetype">{native?'CONF':'YAML'}</span></div><RouteArt/><div class="preview-name">{client?.name}</div><p>{p.name} <span> / </span> {networks[network]}</p>{#if info?.nodes!==undefined}<small>包含 {info.nodes} 个节点。{info.excluded?'已排除 '+info.excluded+' 个无法转换的节点。':''}{info.empty?'有 '+info.empty+' 个组没有可用节点，已设为拒绝连接。':''}</small>{/if}{#if client}<a href={client.site} target="_blank" rel="noreferrer">客户端官网 <Icon name="launch" size={13}/></a>{/if}</aside></div>
<div class="delivery-extra"><details><summary><Icon name="sliders" size={17}/>订阅选项</summary><label>配置名称<input placeholder="留空则使用平台名称" maxlength="80" bind:value={name}></label>{#if !valid}<p class="error">名称含有不支持的字符。</p>{/if}
{#if !native}<div class="choice-row"><label>配置内容<select aria-label="配置内容" bind:value={nodes}><option value={false}>完整配置</option><option value={true}>仅节点列表</option></select></label><label>节点顺序<select aria-label="节点顺序" bind:value={sorted}><option value={false}>保留原顺序</option><option value={true}>按名称排序</option></select></label><label>TLS 证书验证<select aria-label="TLS 证书验证" bind:value={scv}><option value="inherit">沿用节点设置</option><option value="false">验证证书</option><option value="true">跳过验证（降低安全性）</option></select></label>{#if engine==='mihomo'}<label>TCP Fast Open<select aria-label="TCP Fast Open" bind:value={tfo}><option value="inherit">沿用节点设置</option><option value="true">开启</option><option value="false">关闭</option></select></label>{/if}</div>{/if}</details>
<details open={shown||undefined}><summary><Icon name="key" size={17}/>地址与密钥</summary><p>持有地址的人可以获取已发布的配置与节点凭据。</p><div class="actions"><button onclick={()=>shown=!shown}>{shown?'隐藏地址':'显示地址'}</button><button onclick={rotate}>更换订阅密钥</button></div>{#if shown}<label>订阅地址<textarea rows="3" readonly value={url}></textarea></label>{/if}</details></div>{/if}
