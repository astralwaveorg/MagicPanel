<script lang="ts">
 import {onMount} from 'svelte'
 import {api} from './net'
 import Icon from './Icon.svelte'
 import QrShare from './QrShare.svelte'
 type Item={name:string,url:string,target:string,built:number,failed:boolean,input:number,selected:number,output?:number,ext:string}
 const targets:Record<string,string>={mihomo:'Mihomo',stash:'Stash',surge:'Surge 6',surge5:'Surge 5 兼容配置',shadowrocket:'Shadowrocket 配置', 'shadowrocket-nodes':'Shadowrocket 节点订阅',singbox:'sing-box',quanx:'Quantumult X',loon:'Loon',surfboard:'Surfboard',mixed:'混合节点链接',v2rayn:'v2rayN',v2rayng:'v2rayNG',ss:'Shadowsocks',trojan:'Trojan',vless:'VLESS',hysteria2:'Hysteria2'}
 let {notify}:{notify:(x:string)=>void}=$props()
 let sources=$state(''),target=$state('mihomo'),name=$state('转换订阅'),include=$state(''),exclude=$state(''),rename=$state(''),emoji=$state('keep'),preset=$state('manual'),rules=$state(''),nodes=$state(false),sort=$state(false),scv=$state(''),tfo=$state('')
 let result=$state<Item|null>(null),items=$state<Item[]>([]),issue=$state(''),busy=$state(false),pending=$state(''),remove=$state(''),old=$state(''),legacy=$state(false),fallback=$state(''),advanced=$state(false),importNote=$state('')
 let native=$derived(['mihomo','stash','surge','surge5','shadowrocket'].includes(target)),isYaml=$derived(['mihomo','stash'].includes(target))
 async function load(){try{items=await api('conversions')}catch(e){issue=(e as Error).message}}
 onMount(load)
 async function generate(e:SubmitEvent){e.preventDefault();busy=true;issue='';result=null;fallback=''
  try{result=await api('conversions',{sources,target,name,include,exclude,rename,emoji,sort,preset:native&&(preset!=='acl'||target==='mihomo')?preset:'manual',rules:native&&preset==='custom'?rules:'',...(isYaml&&nodes?{list:true}:{}),...(isYaml&&scv?{scv:scv==='true'}:{}),...(target==='mihomo'&&tfo?{tfo:tfo==='true'}:{})});await load();notify('转换地址已生成')}catch(e){issue=(e as Error).message}finally{busy=false}}
 async function copy(u:string){try{await navigator.clipboard.writeText(u);notify('已复制转换地址')}catch{fallback=u}}
 async function change(x:Item,action:'refresh'|'remove'){pending=x.url;issue=''
  try{const tok=new URL(x.url).pathname.split('/').at(-1);const updated=await api('conversions/'+tok+'/'+action,{});if(result?.url===x.url)result=action==='remove'?null:updated;remove='';notify(action==='refresh'?'已刷新转换结果':'转换地址已撤销')}catch(e){issue=(e as Error).message}finally{pending='';await load()}}
 function importOld(){try{const u=new URL(old);if(!['http:','https:'].includes(u.protocol)||u.pathname.replace(/\/$/,'').split('/').at(-1)!=='sub')throw Error();const q=u.searchParams,src=q.get('url');if(!src)throw Error();const t=q.get('target')||'clash'
 const mapped=t==='clash'?'mihomo':t==='surge'?(Number(q.get('ver')||5)>=6?'surge':'surge5'):t==='shadowrocket'?'shadowrocket-nodes':t
 if(!targets[mapped])throw Error();sources=src.split('|').join('\n');target=mapped;name=q.get('filename')||'转换订阅';include=q.get('include')||'';exclude=q.get('exclude')||'';rename=q.get('rename')||'';nodes=q.get('list')==='true';sort=q.get('sort')==='true';scv=['true','false'].includes(q.get('scv')||'')?q.get('scv')!:'';tfo=['true','false'].includes(q.get('tfo')||'')?q.get('tfo')!:'';emoji=q.get('emoji')==='true'?'region':'keep';preset='manual';rules='';const accepted=new Set(['url','target','ver','filename','include','exclude','rename','list','sort','scv','tfo','emoji']);const skipped=[...new Set([...q.keys()].filter(k=>!accepted.has(k)))];importNote=skipped.length?'未导入这些选项：'+skipped.join('、')+'。请核对后生成。':'已读入来源和选项，请核对后生成。';issue='';old='';legacy=false;advanced=true}catch{issue='无法识别此转换长链接，或其目标暂不支持。'}}
</script>
<div class="title"><div><h1>订阅转换</h1><p>合并订阅和节点，为客户端生成独立的更新地址。</p></div></div>
{#if issue}<div class="error" role="alert">{issue}</div>{/if}
<div class="tool-grid"><form class="setup-card convert-form" onsubmit={generate}>
 <div class="card-heading"><span class="tile"><Icon name="converter"/></span><h2>新建转换</h2></div>
 <label>订阅或节点<textarea required rows="5" maxlength="500000" bind:value={sources} placeholder="每行一个 HTTPS 订阅或节点链接，也可以粘贴节点 YAML。"></textarea></label>
 <button type="button" class="text-action" onclick={()=>legacy=!legacy} aria-expanded={legacy}>从旧转换长链接填写</button>
 {#if legacy}<div class="inline-tool"><label>原转换长链接<input type="url" bind:value={old} autocomplete="off"></label><button type="button" onclick={importOld}>读取选项</button><small>只在此浏览器解析，不访问原转换网站。</small></div>{/if}
 {#if importNote}<p role="status">{importNote}</p>{/if}
 <div class="choice-row"><label>输出格式<select aria-label="输出格式" bind:value={target} onchange={()=>{if(preset==='acl')preset='manual'}}>{#each Object.entries(targets) as [key,label]}<option value={key}>{label}</option>{/each}</select></label><label>配置名称<input required maxlength="64" bind:value={name}></label></div>
 {#if native}<label>分流模板<select aria-label="分流模板" bind:value={preset}><option value="manual">手动选择节点</option><option value="auto">自动选择低延迟节点</option><option value="custom">自定义分流规则</option>{#if target==='mihomo'}<option value="acl">ACL4SSR 公共分流模板</option>{/if}</select></label>{:else}<small>此格式由内网转换器生成。客户端不支持的协议可能被过滤。</small>{/if}
 {#if native&&preset==='custom'}<label>分流规则<textarea rows="4" required bind:value={rules} placeholder="DOMAIN-SUFFIX,example.org,DIRECT"></textarea></label><small>每行一条，去向可选 出口、DIRECT 或 REJECT。未匹配的连接走「出口」。</small>{/if}
 <details bind:open={advanced}><summary><Icon name="sliders" size={16}/>筛选和输出选项</summary>
 <div class="choice-row"><label>保留节点<input bind:value={include} placeholder="名称匹配的正则表达式"></label><label>排除节点<input bind:value={exclude} placeholder="名称匹配的正则表达式"></label></div>
 <label>节点重命名<input bind:value={rename} placeholder="正则表达式@新文字"></label>
 <div class="choice-row"><label>地区旗帜<select aria-label="地区旗帜" bind:value={emoji}><option value="keep">保留名称</option><option value="region">按常见地区补充旗帜</option><option value="remove">移除开头的地区旗帜</option></select></label><label>节点顺序<select aria-label="节点顺序" bind:value={sort}><option value={false}>保留原顺序</option><option value={true}>按名称排序</option></select></label>
 {#if isYaml}<label>配置内容<select aria-label="配置内容" bind:value={nodes}><option value={false}>完整配置</option><option value={true}>仅节点列表</option></select></label><label>TLS 证书验证<select aria-label="TLS 证书验证" bind:value={scv}><option value="">沿用节点设置</option><option value="false">验证证书</option><option value="true">跳过验证（降低安全性）</option></select></label>{/if}
 {#if target==='mihomo'}<label>TCP Fast Open<select aria-label="TCP Fast Open" bind:value={tfo}><option value="">沿用节点设置</option><option value="true">开启</option><option value="false">关闭</option></select></label>{/if}</div></details>
 <div class="delivery-actions"><button class="solid" disabled={busy||!sources.trim()}><Icon name="converter" size={17}/>{busy?'正在转换…':'生成转换地址'}</button></div>
</form><aside class="tool-aside"><div class="preview-top"><span class="eyeline">转换结果</span><Icon name="devices" size={20}/></div>
 {#if result}<h2>{result.name}</h2><p>{targets[result.target]} · {result.ext.toUpperCase()}</p><p>解析 {result.input} 个节点，筛选后 {result.selected} 个。{result.output===undefined?'输出数量由目标格式决定。':'最终写入 '+result.output+' 个。'}</p><button class="solid" onclick={()=>copy(result!.url)}><Icon name="copy" size={16}/>复制转换地址</button> <a class="button" href={result.url} download>下载配置</a> <QrShare url={result.url}/>
 {:else}<h2>客户端更新地址</h2><p>生成后可复制地址或下载配置。原始订阅和节点密码不会出现在地址栏。</p>{/if}
 <div class="helper"><Icon name="info" size={16}/><span>客户端取用地址时，如果配置已超过一小时，面板会重新转换。刷新失败时仍提供上次结果。</span></div></aside></div>
 {#if fallback}<label>请手动复制地址<input readonly value={fallback} onfocus={e=>e.currentTarget.select()}></label>{/if}
 <div class="sectionhead"><h2>已保存的转换 <small>{items.length}</small></h2></div>
 {#if !items.length}<p class="panel">转换成功后，地址会出现在这里。</p>{:else}<div class="list convert-list">{#each items as x}<article><div><b>{x.name}</b><small>{targets[x.target]} · {new Date(x.built*1000).toLocaleString()}{x.failed?' · 刷新失败，沿用上次结果':''}</small></div><div class="actions">{#if remove===x.url}<span>撤销后旧地址将失效。</span><button onclick={()=>remove=''}>取消</button><button disabled={!!pending} onclick={()=>change(x,'remove')}>确认撤销</button>{:else}<button onclick={()=>copy(x.url)}>复制</button><a class="button" href={x.url} download>下载</a><button disabled={!!pending} onclick={()=>change(x,'refresh')}>刷新</button><button onclick={()=>remove=x.url}>撤销</button>{/if}</div></article>{/each}</div>{/if}
