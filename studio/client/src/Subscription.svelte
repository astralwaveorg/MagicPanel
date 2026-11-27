<script lang="ts">
 import {onMount} from 'svelte'
 import {api,entries,type Profile} from './net'
 let {notify,rotate,initial}:{notify:(v:string)=>void,rotate:()=>void,initial:string}=$props()
 let profiles=$state<Record<string,Profile>>({}),networks=$state<Record<string,string>>({}),pid=$state(''),engine=$state(''),network=$state('default'),name=$state(''),base=$state(''),error=$state(''),shown=$state(false),sorted=$state(false),nodes=$state(false),scv=$state('inherit'),tfo=$state('inherit')
 const defaults:Record<string,string>={windows:'mihomo',android:'mihomo',macos:'stash',ios:'stash',tvos:'stash'}
 function select(id:string){pid=id;const p=profiles[id];engine=p.adapters[defaults[p.platform]]?defaults[p.platform]:Object.keys(p.adapters)[0];tfo='inherit'}
 onMount(()=>{api('subscription').then(r=>{base=r.base;profiles=r.profiles;networks=r.networks;select(profiles[initial]?initial:(profiles['platform-windows']?'platform-windows':Object.keys(profiles)[0]))}).catch(e=>error=e.message)})
 let url=$derived.by(()=>{const p=profiles[pid];if(!base||!p)return '';let q=new URLSearchParams({platform:p.platform,type:engine,network});if(pid!=='platform-'+p.platform)q.set('template',pid);if(name.trim())q.set('name',name.trim());if(nodes)q.set('list','true');if(sorted)q.set('sort','true');if(scv!=='inherit')q.set('scv',scv);if(tfo!=='inherit'&&engine==='mihomo')q.set('tfo',tfo);return base+'?'+q.toString()})
 let valid=$derived(!name.trim()||(/^[\p{L}\p{M}\p{N}_ .()（）-]{1,80}$/u.test(name.trim())&&!['.','..'].includes(name.trim())))
 async function copy(){try{await navigator.clipboard.writeText(url);notify('订阅地址已复制')}catch{shown=true;notify('请长按或选中地址复制')}}
</script>
<div class="title"><div><small class="kicker">SUBSCRIPTION</small><h1>订阅地址</h1><p>共用一个基础地址。换设备或换运营商，只需改变参数，无需创建设备记录。</p></div></div>
{#if error}<p class="error" role="alert">{error}</p>{:else if !base}<p>正在读取已发布模板…</p>{:else}
<div class="panel"><h2>生成适合设备的地址</h2><div class="filters"><label>平台模板<select value={pid} onchange={e=>select(e.currentTarget.value)}>{#each entries(profiles) as [id,p]}<option value={id}>{p.name}</option>{/each}</select></label>
<label>客户端<select bind:value={engine}>{#each Object.keys(profiles[pid].adapters) as k}<option value={k}>{k==='mihomo'?'Mihomo':'Stash'}</option>{/each}</select></label>
<label>使用线路<select bind:value={network}>{#each entries(networks) as [id,n]}<option value={id}>{n}</option>{/each}</select></label></div>
<label>配置名称（可选）<input placeholder="例如 AstralWindows" maxlength="80" bind:value={name}></label>
<details><summary>高级参数</summary><div class="filters"><label>配置内容<select bind:value={nodes}><option value={false}>完整配置</option><option value={true}>仅节点列表</option></select></label><label>节点排序<select bind:value={sorted}><option value={false}>沿用发布顺序</option><option value={true}>按名称排序</option></select></label>
<label>TLS 证书验证<select bind:value={scv}><option value="inherit">沿用节点设置</option><option value="false">开启验证</option><option value="true">跳过验证（降低安全性）</option></select></label>
{#if engine==='mihomo'}<label>TCP Fast Open<select bind:value={tfo}><option value="inherit">沿用节点设置</option><option value="true">启用</option><option value="false">关闭</option></select></label>{/if}</div></details>
{#if !valid}<p class="error">请使用文字、数字、空格、点、括号、连字符或下划线作为名称。</p>{/if}
<div class="actions"><button class="solid" disabled={!valid||!url} onclick={copy}>复制订阅地址</button><button onclick={()=>shown=!shown}>{shown?'隐藏地址':'显示地址'}</button></div>
{#if shown}<label>当前地址<textarea rows="3" readonly value={url}></textarea></label>{/if}
<p>地址跟随最新成功发布。名称仅作文件名；运营商由所选线路决定。持有基础地址的人可以读取全部已发布模板，请只给可信设备使用。</p></div>
<details><summary>管理订阅密钥</summary><p>轮换后，使用这个基础地址的所有设备都需要更新一次地址。</p><button onclick={rotate}>轮换统一密钥</button></details>{/if}
