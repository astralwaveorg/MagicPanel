<script lang="ts">
 import {onMount} from 'svelte'
 import {api,type State} from './net'
 let {workspace,target,refresh,notify}:{workspace:State,target:string,refresh:()=>Promise<void>,notify:(v:string)=>void}=$props()
 type File={name:string,sha:string,content:string}
 let files=$state<string[]>([]),original=$state<File|null>(null),name=$state(''),body=$state(''),message=$state(''),token=$state(''),kind=$state('classical'),issue=$state(''),busy=$state(false),adding=$state(false)
 let review=$state<{digest:string,diff:string,truncated:boolean}|null>(null),history=$state<{sha:string,message:string}[]>([]),confirmApply=$state(false)
 let dirty=$derived(original!==null&&(original.content!==body||adding))
 let bound=$derived(workspace.resources.find(r=>r.name===name.replace(/\.ya?ml$/,'')))
 async function run(fn:()=>Promise<void>){if(busy)return;busy=true;issue='';try{await fn()}catch(e){issue=(e as Error).message}finally{busy=false}}
 function reset(){review=null;history=[];confirmApply=false;token='';message=''}
 async function list(){files=(await api('rule-repo')).files}
 onMount(()=>{void run(list)})
 async function read(n:string){
  const f=await api<File>('rule-repo/file?name='+encodeURIComponent(n))
  reset();original=f;adding=false;name=f.name;body=f.content
  kind=workspace.resources.find(r=>r.name===n.replace(/\.ya?ml$/,''))?.behavior||f.content.match(/^#\s*behavior:\s*(domain|classical|ipcidr)\s*$/m)?.[1]||'classical'
 }
 function discard(){return !dirty||window.confirm('放弃尚未提交的文件修改？')}
 function create(){if(!discard())return;reset();adding=true;original={name:'',content:'',sha:''};name='';body='payload:\n  - DOMAIN-SUFFIX,example.com\n';kind='classical'}
 const payload=()=>({name,content:body,sha:original?.sha||''})
 async function save(){const proof=review;if(!proof)return
  try{const r=await api('rule-repo/commit',{...payload(),message,token,digest:proof.digest});adding=false;original={...payload(),sha:''};notify('已提交 GitHub：'+r.commit.slice(0,9));review=null;await read(name);await list()}finally{token=''}
 }
</script>
<section class="panel repo-panel" aria-label="GitHub 规则仓库">
 <div class="sectionhead"><div><h2>magic-sets</h2><small>astralwaveorg / main / rule</small></div><div class="actions"><a class="button" href="https://github.com/astralwaveorg/magic-sets/tree/main/rule" target="_blank" rel="noreferrer">在 GitHub 查看</a><button disabled={busy} onclick={()=>run(list)}>刷新目录</button><button disabled={busy} onclick={create}>新建文件</button></div></div>
 {#if issue}<p class="error" role="alert">{issue}</p>{/if}
 <div class="repo-grid"><div class="file-list" aria-label="仓库文件">{#each files as n}<button disabled={busy} class:chosen={!adding&&name===n} onclick={()=>{if(discard())run(()=>read(n))}}>{n}</button>{/each}{#if !files.length}<small>{busy?'正在读取文件…':'没有可显示的文件。'}</small>{/if}</div>
 {#if original}<div class="repo-editor">
 <label>文件名<input readonly={!adding} disabled={busy} bind:value={name} oninput={()=>review=null} placeholder="文件名.yaml"></label>
 {#if !adding}<small>GitHub {original.sha.slice(0,9)} · {bound?.repo_sha?'草稿来源 '+bound.repo_sha.slice(0,9):bound?'已有本地快照，未记录 GitHub 版本':'尚未绑定到面板'}</small>{/if}
 <label>规则正文<textarea rows="9" spellcheck="false" disabled={busy} bind:value={body} oninput={()=>{review=null;confirmApply=false}}></textarea></label>
 <div class="actions"><button disabled={busy||!dirty} onclick={()=>run(async()=>{review=await api('rule-repo/review',payload())})}>预览提交差异</button>
 {#if !adding}<button disabled={busy} onclick={()=>run(async()=>{history=await api('rule-repo/history?name='+encodeURIComponent(name))})}>提交历史</button><button disabled={busy||dirty} onclick={()=>confirmApply=!confirmApply}>应用到草稿</button>{/if}</div>
 {#if review}<div class="review-block"><h3>待提交到 main</h3><pre>{review.diff}</pre>{#if review.truncated}<p>仅显示前 600 行差异。</p>{/if}
 <label>提交说明<input bind:value={message} disabled={busy}></label><label>GitHub 写入令牌<input type="password" autocomplete="off" bind:value={token} disabled={busy}></label><small>仅用于本次提交。使用限于 magic-sets、具有 Contents 写权限的令牌。</small>
 <div class="actions"><button class="solid" disabled={busy||!message.trim()||!token} onclick={()=>run(save)}>确认提交 GitHub</button><button disabled={busy} onclick={()=>{review=null;token=''}}>取消</button></div></div>{/if}
 {#if confirmApply&&!dirty}<div class="review-block"><h3>同步此版本到面板</h3><p>将 {name}（{original.sha.slice(0,9)}）绑定到当前模板，更新已有引用；未引用的文件不会自动参与分流。{workspace.auto.enabled?'自动发布已开启，校验通过后会生效。':'当前需要手动发布。'}</p>
 <label>规则类型<select bind:value={kind} disabled={busy||!!bound}><option value="domain">域名</option><option value="ipcidr">IP 网段</option><option value="classical">混合规则</option></select></label>
 <button disabled={busy} onclick={()=>run(async()=>{await api('rule-repo/apply',{name,sha:original!.sha,behavior:kind,revision:workspace.revision,template:target});confirmApply=false;await refresh();notify('规则集已写入草稿')})}>确认应用到草稿</button></div>{/if}
 {#each history as x}<p><a href={'https://github.com/astralwaveorg/magic-sets/commit/'+x.sha} target="_blank" rel="noreferrer">{x.sha.slice(0,9)}</a> · {x.message}</p>{/each}
 </div>{:else}<p>选择文件可查看正文、修改记录，或将该版本应用到当前模板。</p>{/if}</div>
</section>
