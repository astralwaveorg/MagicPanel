import {test} from 'node:test'
import assert from 'node:assert/strict'
import {clients, install, subscriptionAddress} from '../src/clients.ts'

const opts={base:'https://panel.example:8443/sub/test-key',platform:'macos',template:'office',network:'mobile',name:'工作 Mac （2）',nodes:false,sorted:true,scv:'false',tfo:'true'}
const client=id=>clients.find(c=>c.id===id)

test('each app receives the exact subscription for its engine, template and network',()=>{
 for(const c of clients){
  for(const platform of c.os){
   const address=subscriptionAddress(c.engine,{...opts,platform})
   const link=install(c,platform,address)
   if(!link)continue
   const target=new URL(link)
   const decoded=c.id==='shadowrocket'?link.slice('shadowrocket://config/add/'.length):target.searchParams.get('url')
   assert.equal(decoded,address)
   const q=new URL(decoded).searchParams
   assert.deepEqual([q.get('platform'),q.get('type'),q.get('template'),q.get('name'),q.get('network')],[platform,c.engine,'office','工作 Mac （2）','mobile'])
   assert.equal(q.has('tfo'),c.engine==='mihomo')
   assert.equal(q.has('sort'),['mihomo','stash'].includes(c.engine))
   assert.equal(q.has('scv'),q.has('sort'))
  }
 }
})

test('platform boundaries and scheme-specific forms',()=>{
 const url='https://panel.example/sub/test-key?type=surge&network=mobile'
 assert.match(install(client('stash'),'windows',url),/^stash:\/\/install-config\?url=https%3A/)
 assert.equal(install(client('stash'),'android',url),'')
 assert.equal(install(client('surge'),'windows',url),'')
 assert.equal(install(client('flclash'),'macos',''),'')
 assert.match(install(client('surge5'),'macos',url),/^surgeconfig:\/\/\/install-config/)
 assert.match(install(client('surge5'),'ios',url),/^surge:\/\/\/install-config/)
 assert.equal(install(client('shadowrocket'),'ios',url),'shadowrocket://config/add/'+url)
 for(const id of ['clashmi','stash','mihomo'])assert.equal(install(client(id),'tvos',url),'')
 for(const id of ['nikki','openclash'])assert.equal(install(client(id),'openwrt',url),'')
})
