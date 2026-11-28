const byId=id=>document.getElementById(id), form=document.querySelector('form');
const clearResult=()=>{byId('actions').hidden=true;byId('link').value='';byId('download').removeAttribute('href');byId('status').textContent='生成后，把这里的地址添加到客户端的远程订阅中。';byId('error').textContent=''};
let generation=0;
form.addEventListener('input',()=>{generation++;clearResult();byId('content').hidden=!['clash','stash'].includes(byId('target').value)});
form.addEventListener('submit',async e=>{
 e.preventDefault();clearResult();const current=++generation;const btn=byId('generate'), choice=byId('target').value;
 btn.disabled=true;btn.textContent='正在转换…';
 try{const surge=choice.startsWith('surge'), data={sources:byId('sources').value,target:surge?'surge':choice,list:!byId('content').hidden&&byId('format').value==='list',...(surge?{ver:choice==='surge5'?'5':'6'}:{})};
  const res=await fetch('/api/links',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}), result=await res.json();
  if(!res.ok)throw new Error(result.error||'转换失败，请稍后重试。');if(current!==generation)return;
  const url=new URL(result.path,location.origin);byId('link').value=url.href;byId('download').href=url.href;byId('status').textContent='已写入 '+result.count+' 个节点。复制地址后，在客户端添加远程订阅。';byId('actions').hidden=false;
 }catch(err){if(current===generation)byId('error').textContent=err.message||'暂时无法连接转换服务。'}
 finally{btn.disabled=false;btn.textContent='生成更新地址'}
});
byId('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(byId('link').value);byId('status').textContent='已复制更新地址。'}catch{byId('link').select();byId('status').textContent='请手动复制所选地址。'}});
