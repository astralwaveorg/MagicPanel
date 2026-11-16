export function probeSelection(entries) {
  const byUid = new Map()
  for (const entry of entries || []) {
    const key = String(entry?.node_uid || '')
    const revision = Number(entry?.revision)
    if (!key || !Number.isInteger(revision) || revision < 1) {
      throw new Error('invalid_node_key')
    }
    if (byUid.has(key) && byUid.get(key).revision !== revision) {
      throw new Error('node_revision_conflict')
    }
    byUid.set(key, { node_uid: key, revision })
  }
  return [...byUid.values()]
}
