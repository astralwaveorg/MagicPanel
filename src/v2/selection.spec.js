import { test, expect } from 'vitest'
import { probeSelection } from './selection'

test('已选只包含选中节点和精确连接版本', () => {
  expect(probeSelection([
    { node_uid: 'n1', revision: 2 }, { node_uid: 'n3', revision: 1 },
  ])).toEqual([{ node_uid: 'n1', revision: 2 }, { node_uid: 'n3', revision: 1 }])
  expect(() => probeSelection([
    { node_uid: 'n1', revision: 1 }, { node_uid: 'n1', revision: 2 },
  ])).toThrow('node_revision_conflict')
})
