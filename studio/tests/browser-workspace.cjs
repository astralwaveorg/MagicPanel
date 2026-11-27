// Run against an isolated Studio instance initialized with the fixture account below.
const assert=require('node:assert/strict'),{chromium}=require('playwright')
const origin=process.env.STUDIO_QA_ORIGIN
if(!origin||new URL(origin).hostname!=='127.0.0.1')throw Error('Use an isolated loopback fixture')
;(async()=>{const browser=await chromium.launch({channel:'chrome'})
try{
 for(const width of [320,390,768,1366]){
  const ctx=await browser.newContext({viewport:{width,height:850},permissions:['clipboard-read','clipboard-write']})
  const p=await ctx.newPage(),errors=[];p.setDefaultTimeout(7000);p.on('pageerror',e=>errors.push(e.message))
  const nav=n=>p.getByRole('navigation').getByRole('button',{name:n,exact:true}).click()
  const fits=async(stage)=>{assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow: '+stage+' '+width)}
  await p.goto(origin);await fits('login');await p.getByLabel('用户名').fill('review');await p.getByLabel('密码',{exact:true}).fill('fixture-browser-password');await p.getByRole('button',{name:'登录',exact:true}).click()
  await p.getByRole('button',{name:'复制订阅地址'}).waitFor();await fits('subscription')
  await p.getByRole('button',{name:'二维码',exact:true}).click();await p.waitForFunction(()=>document.querySelector('.qr-dialog canvas')?.width===240);await p.keyboard.press('Escape')
  await p.getByRole('button',{name:'切换浅色模式'}).click()
  await nav('订阅转换');await p.getByRole('heading',{name:'新建转换'}).waitFor();await fits('converter')
  await nav('平台模板');await fits('templates')
  assert(await p.locator('.title').evaluate(e=>e.offsetHeight<120),'page heading too tall')
  await p.getByRole('button',{name:'新建模板',exact:true}).click();await p.getByRole('dialog',{name:'创建平台模板'}).waitFor();await fits('dialog');await p.keyboard.press('Escape')
  await p.locator('.platformcard').filter({hasText:'iOS'}).click();await p.getByRole('heading',{name:'iOS',exact:true}).waitFor();await fits('template detail')
  await p.getByRole('button',{name:'查看客户端规则'}).click()
  await p.getByLabel('查看平台').selectOption('platform-ios');await p.getByLabel('输出格式',{exact:true}).selectOption('shadowrocket');await p.getByLabel('查看线路').selectOption('mobile')
  await p.waitForFunction(()=>document.querySelector('.rules-code')?.textContent.includes('FINAL,'));await fits('client rules')
  await p.getByRole('button',{name:'编辑此客户端的专属规则'}).click();await p.getByRole('textbox',{name:'Shadowrocket 专属规则'}).fill('DST-PORT,99999,DIRECT')
  await p.getByRole('button',{name:'保存到草稿'}).click();await p.getByRole('alert').filter({hasText:'不受此格式支持'}).waitFor()
  await p.getByRole('button',{name:'取消',exact:true}).click()
  // Use an isolated remote response for visual and cancel flows; never commit to the public repo.
  const sample='payload:\n  - DOMAIN-SUFFIX,example.org\n',name='sample.yaml',sha='a'.repeat(40)
  await p.route('**/api/rule-repo',r=>r.fulfill({json:{repo:'fixture',branch:'main',files:[name]}}))
  await p.route('**/api/rule-repo/file?*',r=>r.fulfill({json:{name,sha,content:sample}}))
  await p.route('**/api/rule-repo/review',r=>r.fulfill({json:{digest:'test-digest',truncated:false,diff:'- old\n+ new'}}))
  await p.getByRole('button',{name:'magic-sets',exact:true}).click()
  await p.getByRole('button',{name,exact:true}).click();await p.getByLabel('规则正文').fill(sample+'  - DOMAIN,example.net\n')
  await p.getByRole('button',{name:'预览提交差异'}).click();await p.getByRole('button',{name:'确认提交 GitHub'}).waitFor();assert(await p.getByRole('button',{name:'确认提交 GitHub'}).isDisabled())
  await fits('repository');await p.getByRole('button',{name:'取消',exact:true}).click()
  for(const tab of ['规则','节点','订阅来源','规则资源']){
   await p.getByRole('button',{name:tab,exact:true}).click();await fits(tab)
  }
  await nav('线路方案');await p.getByRole('button',{name:'调整优先顺序'}).click();await p.getByRole('dialog').waitFor();await fits('ordering');await p.keyboard.press('Escape')
  await nav('发布记录');await fits('release');await p.getByRole('button',{name:'查看配置差异'}).click();await p.getByRole('dialog').waitFor();await p.keyboard.press('Escape')
  await p.getByRole('button',{name:'退出',exact:true}).click();await p.getByRole('button',{name:'登录',exact:true}).waitFor();assert.deepEqual(errors,[])
  await ctx.close();console.log(width+'px: all pages, rule formats, repo review, dialogs, keyboard, sign-out passed')
 }
}finally{await browser.close()}})().catch(e=>{console.error(e.message);process.exit(1)})
