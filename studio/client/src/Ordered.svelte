<script lang="ts">
 import type {Field} from './net'
 let {field}:{field:Field}=$props()
 let items=$state<string[]>([]);let pick=$state('')
 $effect(()=>{items=(field.value||'').split('\n').filter(Boolean)})
 function move(i:number,n:number){let a=[...items];[a[i],a[n]]=[a[n],a[i]];items=a}
</script>
<div class="ordered"><select aria-label="追加候选项" bind:value={pick} onchange={()=>{if(pick&&!items.includes(pick))items=[...items,pick];pick=''}}><option value="">选择要追加的候选项</option>{#each field.options||[] as [k,v]}<option value={k} disabled={items.includes(k)}>{v}</option>{/each}</select>
{#each items as v,i}<div><span>{i+1}. {field.options?.find(x=>x[0]===v)?.[1]||v}</span><button type="button" disabled={i===0} aria-label="上移" onclick={()=>move(i,i-1)}>↑</button><button type="button" disabled={i===items.length-1} aria-label="下移" onclick={()=>move(i,i+1)}>↓</button><button type="button" aria-label="移除候选" onclick={()=>items=items.filter(x=>x!==v)}>×</button></div>{/each}<input type="hidden" name={field.key} value={items.join('\n')}></div>
