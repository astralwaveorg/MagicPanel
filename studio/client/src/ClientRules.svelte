<script lang="ts">
 import {api,entries,type State} from './net'
 import {engineNames,formats} from './formats'
 let {workspace,start,refresh,notify}:{workspace:State,start:string,refresh:()=>Promise<void>,notify:(v:string)=>void}=$props()
 let profile=$state(''),engine=$state(''),net=$state('default'),asset=$state(''),offset=$state(0),request=$state(0),err=$state(''),draft=$state(''),editing=$state(false),saving=$state(false),editRev=0
 let result=$state<{release:number,desktop_skipped?:number,lines?:string[],resources?:{key:string,name:string}[],count?:number,error?:string,binary?:boolean,bytes?:number}|null>(null)
 let pf=$derived(workspace.profiles[profile]),opts=$derived(pf?formats(pf):[]),native=$derived(['surge','surge5','shadowrocket'].includes(engine))
 $effect(()=>{if(!profile)pick(start||Object.keys(workspace.profiles)[0])})
 function pick(k:string){profile=k;const options=formats(workspace.profiles[k]);engine=options.includes(engine)?engine:options[0];reset()}
 function reset(){asset='';offset=0;editing=false;err=''}
 function edit(){editRev=workspace.revision;draft=(pf?.native_rules?.[engine]||[]).join('\n');editing=true}
 async function save(){saving=true;err='';try{await api('edit',{op:'native_rules',revision:editRev,data:{profile,engine,content:draft}});editing=false;await refresh();request++;notify('客户端规则已保存到草稿')}catch(e){err=(e as Error).message}finally{saving=false}}
 $effect(()=>{const params=new URLSearchParams({profile,engine,network:net,asset,offset:String(offset)});void request;void workspace.live.id;if(!profile||!engine)return
 let active=true;err='';result=null;api('released-rules?'+params).then(x=>{if(active)result=x}).catch(e=>{if(active)err=e.message});return()=>{active=false}})
</script>
<section class="panel rule-output">
 <div class="sectionhead"><div><h2>客户端分流规则</h2><small>查看正式订阅的匹配顺序和规则集内容。</small></div></div>
 <div class="filters"><label>查看平台<select aria-label="查看平台" value={profile} onchange={e=>pick(e.currentTarget.value)} disabled={editing}>{#each entries(workspace.profiles) as [k,p]}<option value={k}>{p.name}</option>{/each}</select></label>
 <label>输出格式<select aria-label="输出格式" bind:value={engine} onchange={reset} disabled={editing}>{#each opts as k}<option value={k}>{engineNames[k]}</option>{/each}</select></label>
 <label>查看线路<select aria-label="查看线路" bind:value={net} onchange={reset} disabled={editing}>{#each entries(workspace.networks) as [k,n]}<option value={k}>{n.name}</option>{/each}</select></label></div>
 {#if native&&!editing}<button onclick={edit}>编辑此客户端的专属规则</button>{/if}
 {#if editing}<div class="review-block"><label>{engineNames[engine]} 专属规则<textarea rows="6" bind:value={draft} disabled={saving} placeholder="DOMAIN-SUFFIX,example.com,DIRECT"></textarea></label>
 <p>每行填写「类型,匹配值,去向」，可用域名、关键词、IP 网段和 {engine==='shadowrocket'?'DST-PORT':'DEST-PORT'}。发布后优先于共享规则，作用于此模板下该客户端的所有线路。</p>
 <div class="actions"><button class="solid" disabled={saving} onclick={save}>保存到草稿</button><button disabled={saving} onclick={()=>editing=false}>取消</button></div></div>{/if}
 {#if err}<p class="error" role="alert">{err}</p><button onclick={()=>request++}>重试读取</button>{/if}
 {#if result}<div class="sectionhead"><h3>发布 #{result.release} · {asset?'规则集正文':'匹配顺序'}</h3>{#if asset}<button onclick={()=>{asset='';offset=0}}>返回规则</button>{/if}</div>
 {#if result.desktop_skipped}<p>此 iOS 配置已略过 {result.desktop_skipped} 条桌面进程规则。域名、端口及 IP 规则仍按下方顺序匹配。</p>{/if}
 {#if result.error}<p class="error">此格式未生成：{result.error}</p>{:else if result.binary}<p>MRS 二进制规则集 · {result.bytes} 字节。选择 Apple 文本格式可查看转换后的规则集。</p>
 {:else}<small>共 {result.count} 行{result.count?' · '+(offset+1)+'–'+Math.min(offset+100,result.count):''}</small><pre class="rules-code">{result.lines?.join('\n')}</pre>
 {#if (result.count||0)>100}<div class="actions"><button disabled={offset===0} onclick={()=>offset-=100}>上一页</button><button disabled={offset+100>=(result?.count||0)} onclick={()=>offset+=100}>下一页</button></div>{/if}
 {#if result.resources?.length}<details><summary>引用的规则集 · {result.resources.length}</summary><div class="actions">{#each result.resources as r}<button onclick={()=>{asset=r.key;offset=0}}>{r.name}</button>{/each}</div></details>{/if}{/if}{:else if !err}<p>正在读取发布结果…</p>{/if}
</section>
