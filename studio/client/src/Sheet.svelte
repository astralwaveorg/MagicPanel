<script lang="ts">
 import type {Form} from './net'
 import Ordered from './Ordered.svelte'
 import {onMount} from 'svelte'
 let {form,close}:{form:Form,close:()=>void}=$props()
 let dlg:HTMLDialogElement;let error=$state(''),busy=$state(false)
 onMount(()=>{dlg.showModal()})
 async function submit(e:SubmitEvent){e.preventDefault();let data=Object.fromEntries(new FormData(e.currentTarget as HTMLFormElement)) as Record<string,string>;busy=true;error='';try{await form.run(data);close()}catch(x){error=(x as Error).message}finally{busy=false}}
</script>
<dialog aria-labelledby="sheet-title" bind:this={dlg} oncancel={close}><form onsubmit={submit}><div class="sheettop"><h2 id="sheet-title">{form.title}</h2><button type="button" class="iconbtn" onclick={close} aria-label="关闭">×</button></div>{#if form.desc}<p class="intro">{form.desc}</p>{/if}
 {#each form.fields as f}<label>{f.label}
 {#if f.kind==='ordered'}<Ordered field={f}/>{:else if f.kind==='select'}<select name={f.key} required={f.required} value={f.value??f.options?.[0]?.[0]}>{#each f.options||[] as o}<option value={o[0]}>{o[1]}</option>{/each}</select>
 {:else if f.kind==='area'}<textarea rows="6" name={f.key} value={f.value||''} required={f.required}></textarea>
 {:else}<input type={f.kind==='password'?'password':'text'} name={f.key} value={f.value||''} required={f.required} autocomplete="off" />{/if}
 {#if f.hint}<small>{f.hint}</small>{/if}</label>{/each}
 {#if error}<p class="error" role="alert">{error}</p>{/if}<footer><button type="button" onclick={close}>取消</button><button class="solid" disabled={busy}>{busy?'处理中…':form.action||'保存草稿'}</button></footer></form></dialog>
