<script lang="ts">
 import {tick} from 'svelte'
 import Icon from './Icon.svelte'
 let {url}:{url:string}=$props(), dialog:HTMLDialogElement, canvas:HTMLCanvasElement,err=$state('')
 async function show(){dialog.showModal();err='';await tick();try{const qr=await import('qrcode');await qr.toCanvas(canvas,url,{width:240,margin:4,errorCorrectionLevel:'M',color:{dark:'#122017',light:'#ffffff'}})}catch{err='二维码生成失败，请复制地址。'}}
</script>
<button type="button" disabled={!url} onclick={show}><Icon name="qr" size={16}/>二维码</button>
<dialog bind:this={dialog} aria-label="订阅二维码" class="qr-dialog"><div class="qr-title"><h2>在另一台设备打开</h2><button aria-label="关闭二维码" onclick={()=>dialog.close()}>×</button></div><p>使用设备扫描此码。请只向可以使用这份订阅的人展示。</p><canvas bind:this={canvas} aria-label="订阅地址二维码"></canvas>{#if err}<p class="error">{err}</p>{/if}</dialog>
