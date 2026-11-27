<script lang="ts">
 import {onMount} from 'svelte'
 import {api,entries,type State,type Detail,type Form} from './net'
 import {act} from './actions'
 import Icon from './Icon.svelte'
 import Subscription from './Subscription.svelte'
 import Converter from './Converter.svelte'
 import RouteArt from './RouteArt.svelte'
 import Sheet from './Sheet.svelte'
 let s=$state<State|null>(null), d=$state<Detail|null>(null),page=$state('home'),asset=$state('规则'),pid=$state(''),tid=$state(''),net=$state('default'),query=$state(''),msg=$state(''),err=$state(''),busy=$state(false),ready=$state(false),form=$state<Form|null>(null)
 let selGroup=$state(''), serial=0;let timer:ReturnType<typeof setTimeout>
 const pages=[['home','订阅'],['converter','订阅转换'],['templates','平台模板'],['networks','线路方案'],['library','规则与节点'],['release','发布记录']]
 let theme=$state(document.documentElement.dataset.theme||'dark'),subInitial=$state('')
 function switchTheme(){theme=theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('studio.theme',theme)}catch{}}
 const osOrder=['windows','macos','tvos','ios','android']
 const orderProfiles=(x:State)=>entries(x.profiles).sort((a,b)=>osOrder.indexOf(a[1].platform)-osOrder.indexOf(b[1].platform))
 let profile=$derived(s?.profiles[pid]),network=$derived(s?.networks[net]),dirty=$derived(s?.revision!==s?.live.revision)
 const notify=(v:string)=>{msg=v;clearTimeout(timer);timer=setTimeout(()=>msg='',4800)}
 function route(v:string){if(v==='devices'){subInitial=pid;v='home'}else subInitial='';page=v;query='';err='';location.hash=v;window.scrollTo(0,0)}
 function readhash(){const h=location.hash.slice(1)||(location.pathname==='/tools/converter'?'converter':'home');page=h==='devices'?'home':pages.some(([k])=>k===h)||h==='platform'?h:'home'}
 async function reload(){const x=await api<State>('state');s=x;if(!x.profiles[pid])pid=orderProfiles(x)[0]?.[0]||'';if(!x.networks[net])net='default';await detail()}
 async function detail(){if(!s||!pid)return;const a=s.profiles[pid].adapters;tid=Object.values(a).includes(tid)?tid:Object.values(a)[0];const i=++serial;let result=await api<Detail>('templates/'+tid+'?network='+encodeURIComponent(net));if(i===serial){d=result;if(!result.groups.some(g=>g.name===selGroup))selGroup=result.groups[0]?.name||''}}
 async function choose(id:string){pid=id;tid='';await detail();route('platform')}
 async function go(action:string,id=''){if(!s||!d)return;err='';busy=true;try{await act(action,id,{s,d,profile:pid,target:tid,network:net,open:f=>form=f,refresh:reload,notify})}catch(e){err=(e as Error).message}finally{busy=false}}
 async function signin(e:SubmitEvent){e.preventDefault();err='';busy=true;try{await api('login',Object.fromEntries(new FormData(e.currentTarget as HTMLFormElement)));await reload()}catch(x){err=(x as Error).message}finally{busy=false}}
 onMount(()=>{readhash();window.addEventListener('hashchange',readhash);reload().catch(e=>{if(e.message!=='请登录')err=e.message}).finally(()=>ready=true);return()=>window.removeEventListener('hashchange',readhash)})
 async function logout(){await api('logout',{});s=null;d=null;form=null}
</script>
<svelte:head><title>MagicPanel Studio · 分流工作室</title></svelte:head>
{#snippet contextPicker()}
 <div class="filters"><label>平台模板<select aria-label="平台模板" bind:value={pid} onchange={()=>{tid='';detail()}}>{#each orderProfiles(s!) as [id,x]}<option value={id}>{x.name}</option>{/each}</select></label>
 {#if profile}<label>配置格式<select aria-label="配置格式" bind:value={tid} onchange={detail}>{#each entries(profile.adapters) as [eng,id]}<option value={id}>{eng==='mihomo'?'Mihomo':'Stash'}</option>{/each}</select></label>{/if}
 <label>线路方案<select aria-label="线路方案" bind:value={net} onchange={detail}>{#each entries(s!.networks) as [id,n]}<option value={id}>{n.name}</option>{/each}</select></label></div>
{/snippet}
{#snippet themeButton()}<button class="theme-button" aria-label={theme==='dark'?'切换浅色模式':'切换暗色模式'} title={theme==='dark'?'切换浅色模式':'切换暗色模式'} onclick={switchTheme}><Icon name={theme==='dark'?'sun':'moon'} size={18}/></button>{/snippet}
{#snippet brand()}<span class="brandmark"><svg viewBox="0 0 30 30" aria-hidden="true"><path d="m4 20 7-12 4 7 4-7 7 12M10 20l5-8 5 8" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round"/></svg></span><b>MagicPanel</b><span class="brand-sub">Studio</span>{/snippet}
{#if !s}
 <header><a href="#home" class="logo">{@render brand()}</a>{@render themeButton()}</header>
 <main class="entry"><section class="loginart"><span class="tile"><Icon name="networks"/></span><h1>配置与订阅</h1><p>管理分流规则，为设备生成订阅。</p><RouteArt/></section><div class="signin"><h2>登录</h2><form onsubmit={signin}><label>用户名<input name="username" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><button class="solid" disabled={busy||!ready}>{busy?'正在登录…':'登录'}</button></form>{#if err}<p class="error" role="alert">{err}</p>{/if}</div></main>
{:else}
 <header><a href="#home" class="logo">{@render brand()}</a><div class="user">{@render themeButton()}<span class="account">{s.user}</span><button class="logout" onclick={logout}>退出</button></div></header>
 <div class="layout"><aside class="sidebar"><small class="side-caption">工作区</small><nav aria-label="主导航">{#each pages as [key,name]}<button class:active={page===key||(key==='templates'&&page==='platform')} aria-current={page===key?'page':undefined} onclick={()=>route(key)}><Icon name={key}/><span>{name}</span></button>{/each}</nav><div class="sidehelp"><span class="dot"></span> 生效版本 #{s.live.id}</div></aside>
 <main class="workspace" id="main"><div class="crumb">工作区 <span>/</span> {page==='platform'?profile?.name:pages.find(x=>x[0]===page)?.[1]}</div>
 {#if err}<div class="error" role="alert">{err}</div>{/if}
 {#key page}<div class="page-body">
 {#if page==='home'}
 <Subscription initial={subInitial} release={s.live.id} {notify} rotate={()=>go('sub-rotate')}/>
 {:else if page==='converter'}
 <Converter {notify}/>
 {:else if page==='templates'}
 <div class="title"><div><h1>平台模板</h1><p>选择平台，调整规则、策略组或引擎设置。</p></div><div class="actions"><button class="solid" onclick={()=>go('profile-copy')}>新建模板</button><button onclick={()=>go('profile-import')}>导入 YAML</button></div></div>
 <div class="platforms">{#each orderProfiles(s) as [id,p]}<button class="platformcard" onclick={()=>choose(id)}><span class={'osicon '+p.platform}><Icon name={p.platform} size={25}/></span><strong>{p.name}</strong><small>{Object.keys(p.adapters).map(k=>k==='mihomo'?'Mihomo':'Stash').join(' / ')}</small><span class="cardfoot">管理模板 <Icon name="arrow" size={16}/></span></button>{/each}</div>
 <div class="sectionhead"><div><h2>常用操作</h2></div></div>
 <div class="quick"><button onclick={()=>route('networks')}><Icon name="networks"/><b>调整运营商线路</b><small>调整各线路的节点优先级</small></button><button onclick={()=>go('add-node')}><Icon name="library"/><b>粘贴节点</b><small>识别协议后加入策略组</small></button><button onclick={()=>route('devices')}><Icon name="devices"/><b>获取订阅地址</b><small>选择平台、客户端和线路</small></button></div>
 {:else if page==='platform'&&d&&profile}
 <div class="title"><div><h1>{profile.name}</h1><p>调整此平台的基础配置。线路偏好在「线路方案」中管理。</p></div><button onclick={()=>route('devices')}>获取订阅</button></div>{@render contextPicker()}
 <div class="actions"><button onclick={()=>go('rules-add')}>添加规则</button><button onclick={()=>go('group-new')}>新建策略组</button><button onclick={()=>go('add-node')}>导入节点</button><button onclick={()=>go('preview')}>预览差异</button></div>
 <div class="sectionhead"><h2>策略组 <small>{d.groups.length}</small></h2></div><div class="list">{#each d.groups as g}<article><div><b>{g.name}</b><small>{g.type} · {(g.proxies||[]).slice(0,4).join(' → ')}</small></div><button onclick={()=>go('group-edit',g.name)} disabled={net!=='default'}>编辑成员</button></article>{/each}</div>
 <details><summary>高级配置</summary><div class="actions"><button onclick={()=>go('yaml')}>查看生成的 YAML</button><button onclick={()=>go('advanced')} disabled={net!=='default'}>修改引擎设置</button></div></details>
 {:else if page==='networks'&&d&&network}
 <div class="title"><div><h1>线路方案</h1><p>选择运营商，调整这条线路使用的规则和节点。</p></div><button onclick={()=>go('network-new')}>＋ 新建方案</button></div>
 <div class="plans">{#each entries(s.networks) as [id,n]}<button class:chosen={net===id} onclick={()=>{net=id;detail()}}><Icon name="networks"/><b>{n.name}</b><small>{Object.keys(n.groups).length} 个策略组已调整</small></button>{/each}</div>
 <div class="sectionhead"><h2>{network.name}</h2><div class="actions"><button onclick={()=>go('network-rules')}>提前或排除规则</button><button onclick={()=>go('network-dest')}>修改规则去向</button></div></div>
 <div class="panel"><h3>候选节点优先级</h3><p>选定策略组后，排在前面的节点会优先参与故障切换。</p>
 <label>参考平台<select aria-label="参考平台" bind:value={pid} onchange={()=>{tid='';detail()}}>{#each orderProfiles(s) as [id,p]}<option value={id}>{p.name}</option>{/each}</select></label>
 <label>业务策略组<select aria-label="业务策略组" bind:value={selGroup}>{#each d.groups as g}<option value={g.name}>{g.name}</option>{/each}</select></label>
 <p class="route-preview">{(d.groups.find(x=>x.name===selGroup)?.proxies||[]).slice(0,8).join(' → ')||'候选节点由订阅来源提供'}</p><button class="solid" onclick={()=>go('network-group',selGroup)}>调整优先顺序</button></div>
 {:else if page==='library'&&d}
 <div class="title"><div><h1>规则与节点</h1><p>查找规则、维护节点或更新订阅来源。</p></div><button onclick={()=>go('ai')}><Icon name="spark" size={16}/> 配置助手</button></div>
 <div class="tabs">{#each ['规则','节点','订阅来源','规则资源'] as x}<button class:chosen={asset===x} onclick={()=>{asset=x;query=''}}>{x}</button>{/each}</div>{@render contextPicker()}
 <div class="searchline"><input aria-label="搜索" placeholder={'搜索'+asset} bind:value={query}><button class="solid" onclick={()=>go(({'规则':'rules-add','节点':'add-node','订阅来源':'source','规则资源':'resource-new'} as Record<string,string>)[asset])}>＋ 添加{asset}</button></div>
 <div class="list">{#if asset==='规则'}{#each d.order.map((k,i)=>({k,i,v:d!.resolved_rules?.[k]||s!.rules[k]})).filter(x=>x.v?.toLowerCase().includes(query.toLowerCase())) as x}<article><span class="num">{x.i+1}</span><div><b class="code">{x.v}</b></div><div class="rowbtn"><button onclick={()=>go('rule-edit',x.k)}>编辑</button><button onclick={()=>go('rule-del',x.k)}>删除</button></div></article>{/each}
 {:else if asset==='节点'}{#each d.nodes.filter(x=>x.name.includes(query)) as x}<article><div><b>{x.name}</b><small>{x.type}</small></div><button onclick={()=>go('node-remove',x.name)}>移除</button></article>{/each}
 {:else if asset==='订阅来源'}{#each s.sources.filter(x=>x.name.includes(query)) as x}<article><div><b>{x.name}</b><small>{x.managed?'自动刷新':'固定快照'} · {x.snapshot_count||0} 个节点</small></div><div class="rowbtn"><button onclick={()=>go('source',x.id)}>设置</button><button onclick={()=>go('source-refresh',x.id)}>刷新</button></div></article>{/each}
 {:else}{#each s.resources.filter(x=>x.name.includes(query)) as x}<article><div><b>{x.name}</b><small>{x.format} · {x.behavior}</small></div><div class="rowbtn">{#if x.format==='yaml'}<button onclick={()=>go('resource-edit',x.name)}>编辑</button>{/if}<button onclick={()=>go('resource-new',x.name)}>设置</button><button onclick={()=>go('resource-refresh',x.name)}>刷新</button></div></article>{/each}{/if}</div>
 {:else if page==='release'}
 <div class="title"><div><h1>发布记录</h1><p>查看已发布的配置，或恢复到以前的订阅版本。</p></div><button class="solid" onclick={()=>go('publish')}>校验并发布</button></div>
 <div class="panel"><h3>{dirty?'有草稿等待发布':'草稿与生效版本一致'}</h3><p>草稿 {s.revision} · 生效 #{s.live.id} · 自动发布{s.auto.enabled?'已开启':'已暂停'}</p><div class="actions"><button onclick={()=>go('auto')}>{s.auto.enabled?'暂停':'开启'}自动发布</button><button onclick={()=>go('preview')}>查看配置差异</button></div>{#if s.auto.error}<p class="error">{s.auto.error}</p>{/if}</div>{@render contextPicker()}
 <div class="list">{#each s.releases as r}<article><div><b>发布 #{r.id}</b><small>{new Date(r.at*1000).toLocaleString()} · {r.actor}</small></div>{#if r.id===s.live.id}<span class="tag">生效中</span>{:else if r.unified}<button onclick={()=>go('rollback',String(r.id))}>恢复</button>{:else}<small>仅供查阅</small>{/if}</article>{/each}</div>{/if}
 </div>{/key}</main></div>
{/if}
{#if form}{#key form}{@const active=form}<Sheet form={active} close={()=>{if(form===active)form=null}}/>{/key}{/if}
{#if msg}<div class="toast" role="status">{msg}</div>{/if}
