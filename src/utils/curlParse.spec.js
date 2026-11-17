import { describe, expect, it } from 'vitest'
import { parseCurl } from './curlParse'

describe('parseCurl', () => {
  it('解析地址与请求头（双引号）', () => {
    const r = parseCurl(`curl -H "Cookie: a=1" -H "User-Agent: Stash" https://sub.example.com/token?x=1`)
    expect(r.url).toBe('https://sub.example.com/token?x=1')
    expect(r.headers).toEqual([
      { name: 'Cookie', value: 'a=1' },
      { name: 'User-Agent', value: 'Stash' },
    ])
  })

  it('单引号与裸写法', () => {
    const r = parseCurl(`curl -H 'X-A: 1' --header X-B:2 https://a.com/s`)
    expect(r.headers).toEqual([
      { name: 'X-A', value: '1' },
      { name: 'X-B', value: '2' },
    ])
  })

  it('Host 由地址决定，忽略', () => {
    const r = parseCurl(`curl -H "Host: evil.example" https://a.com/s`)
    expect(r.headers).toEqual([])
  })

  it('没有地址时返回空 url', () => {
    expect(parseCurl('curl -H "A: b"').url).toBe('')
  })

  it('地址尾随引号被去掉', () => {
    const r = parseCurl(`curl 'https://a.com/s?token=1'`)
    expect(r.url).toBe('https://a.com/s?token=1')
  })
})
